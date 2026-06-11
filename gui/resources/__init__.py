"""Resource path helpers for the Opus LaneSight GUI.

Provides reliable paths to bundled assets (logo, icon) regardless of
the working directory at runtime.
"""

from pathlib import Path

_RESOURCES_DIR = Path(__file__).resolve().parent

LOGO_PATH: Path = _RESOURCES_DIR / "logo.png"
"""Path to the Opus logo PNG (horizontal, suitable for 36px+ height in header)."""

ICON_PATH: Path = _RESOURCES_DIR / "icon.ico"
"""Path to the application window icon (.ico, multi-size, derived from Opus logo)."""

FONTS_DIR: Path = _RESOURCES_DIR / "fonts"
"""Directory containing bundled Roboto TTF files (Apache-2.0 licensed)."""

FONT_PATHS: list[Path] = [
    FONTS_DIR / "Roboto-Regular.ttf",
    FONTS_DIR / "Roboto-Medium.ttf",
    FONTS_DIR / "Roboto-Bold.ttf",
]
"""Bundled Roboto font files registered with Qt at application startup so the
brand font renders consistently even when Roboto is not installed system-wide."""


def get_resource_path(filename: str) -> Path:
    """Return the absolute path to a named resource file.

    Args:
        filename: Name of the file within gui/resources/.

    Returns:
        Resolved Path object. Caller should check .exists() if needed.
    """
    return _RESOURCES_DIR / filename
