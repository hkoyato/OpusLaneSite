"""Asset and model location for the Opus LaneSight application.

Resolves runtime assets (ML model weights and other files under ``assets/``)
in a way that works regardless of the current working directory or whether the
app runs from source or as a packaged (PyInstaller) build.

This is distinct from :mod:`gui.resources`, which exposes bundled UI assets
(logo, window icon, fonts) that always ship inside the ``gui/resources/``
package directory.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Default vehicle detection model filename (Requirement 8.1).
DEFAULT_VEHICLE_MODEL = "yolov8n.pt"

# Environment variable allowing an explicit models directory override.
MODELS_DIR_ENV = "LANESIGHT_MODELS_DIR"


def is_frozen() -> bool:
    """Return True when running from a PyInstaller (or similar) frozen build."""
    return bool(getattr(sys, "frozen", False))


def app_base_dir() -> Path:
    """Return the application base directory for external (on-disk) assets.

    - Frozen build: the directory containing the executable. External assets
      placed next to the executable (e.g. ``assets/models/``) are found here.
    - Source run: the repository root (the parent of the ``gui`` package).
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    # gui/assets.py -> gui/ -> repo root
    return Path(__file__).resolve().parent.parent


def bundled_base_dir() -> Path:
    """Return the base directory for assets bundled inside a frozen build.

    PyInstaller extracts bundled data to ``sys._MEIPASS`` at runtime. For a
    source run this is the same as :func:`app_base_dir`.
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return app_base_dir()


def assets_dir() -> Path:
    """Return the ``assets/`` directory next to the application."""
    return app_base_dir() / "assets"


def models_dir() -> Path:
    """Return the ``assets/models/`` directory next to the application."""
    return assets_dir() / "models"


def _candidate_model_dirs(override: str | None) -> list[Path]:
    """Build the ordered list of directories to search for a model file."""
    candidates: list[Path] = []

    # 1. Explicit override directory (from settings/CLI), if it is a directory.
    if override:
        override_path = Path(override)
        candidates.append(override_path if override_path.is_dir() else override_path.parent)

    # 2. Environment variable override.
    env_dir = os.environ.get(MODELS_DIR_ENV)
    if env_dir:
        candidates.append(Path(env_dir))

    # 3. assets/models/ next to the application.
    candidates.append(models_dir())

    # 4. Bundled assets/models (frozen builds) and application base directory.
    candidates.append(bundled_base_dir() / "assets" / "models")
    candidates.append(app_base_dir())
    candidates.append(bundled_base_dir())

    # 5. Current working directory (legacy behaviour).
    candidates.append(Path.cwd())

    # De-duplicate while preserving order.
    seen: set[Path] = set()
    unique: list[Path] = []
    for directory in candidates:
        try:
            resolved = directory.resolve()
        except OSError:
            resolved = directory
        if resolved not in seen:
            seen.add(resolved)
            unique.append(directory)
    return unique


def resolve_model(
    filename: str = DEFAULT_VEHICLE_MODEL,
    override: str | None = None,
) -> Path | None:
    """Return the first existing path for *filename*, or ``None`` if not found.

    *override* may be a full file path or a directory. A full file path that
    exists is returned directly; otherwise its parent directory is searched.

    Validates: Requirement 8.1
    """
    # An override pointing directly at an existing file wins outright.
    if override:
        override_path = Path(override)
        if override_path.is_file():
            return override_path

    for directory in _candidate_model_dirs(override):
        candidate = directory / filename
        if candidate.is_file():
            return candidate
    return None


def resolve_model_str(
    filename: str = DEFAULT_VEHICLE_MODEL,
    override: str | None = None,
) -> str:
    """Resolve a model and return a string path.

    Falls back to *filename* unchanged when the file cannot be located, so that
    callers (e.g. Ultralytics ``YOLO``) retain their existing behaviour of
    treating a bare name as a downloadable/auto-resolved model.
    """
    resolved = resolve_model(filename, override)
    return str(resolved) if resolved is not None else filename


def resolve_asset(*parts: str) -> Path | None:
    """Return the first existing path for an asset under ``assets/``.

    Example: ``resolve_asset("models", "yolov8n.pt")``. Searches the on-disk
    ``assets/`` directory and the bundled location for frozen builds.
    """
    relative = Path(*parts)
    for base in (assets_dir(), bundled_base_dir() / "assets"):
        candidate = base / relative
        if candidate.exists():
            return candidate
    return None
