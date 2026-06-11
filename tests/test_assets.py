"""Unit tests for gui.assets model/asset resolution.

Validates: Requirement 8.1 — the vehicle detection model is located reliably
regardless of the current working directory.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from gui import assets


def test_resolve_model_finds_file_in_assets_models(tmp_path, monkeypatch):
    """A model placed in assets/models/ is found via app_base_dir."""
    base = tmp_path / "app"
    (base / "assets" / "models").mkdir(parents=True)
    model = base / "assets" / "models" / "yolov8n.pt"
    model.write_bytes(b"fake-weights")

    monkeypatch.setattr(assets, "app_base_dir", lambda: base)
    monkeypatch.setattr(assets, "bundled_base_dir", lambda: base)
    monkeypatch.delenv(assets.MODELS_DIR_ENV, raising=False)

    resolved = assets.resolve_model("yolov8n.pt")
    assert resolved == model


def test_resolve_model_returns_none_when_absent(tmp_path, monkeypatch):
    """When no model exists anywhere searched, resolution returns None."""
    base = tmp_path / "empty"
    base.mkdir()
    monkeypatch.setattr(assets, "app_base_dir", lambda: base)
    monkeypatch.setattr(assets, "bundled_base_dir", lambda: base)
    monkeypatch.delenv(assets.MODELS_DIR_ENV, raising=False)
    monkeypatch.chdir(base)

    assert assets.resolve_model("yolov8n.pt") is None


def test_resolve_model_env_override(tmp_path, monkeypatch):
    """LANESIGHT_MODELS_DIR is searched for the model file."""
    env_dir = tmp_path / "weights"
    env_dir.mkdir()
    model = env_dir / "yolov8n.pt"
    model.write_bytes(b"fake-weights")

    base = tmp_path / "app"
    base.mkdir()
    monkeypatch.setattr(assets, "app_base_dir", lambda: base)
    monkeypatch.setattr(assets, "bundled_base_dir", lambda: base)
    monkeypatch.setenv(assets.MODELS_DIR_ENV, str(env_dir))

    assert assets.resolve_model("yolov8n.pt") == model


def test_resolve_model_explicit_file_override_wins(tmp_path, monkeypatch):
    """An explicit existing file path is returned directly."""
    custom = tmp_path / "custom" / "my_model.pt"
    custom.parent.mkdir(parents=True)
    custom.write_bytes(b"fake-weights")

    assert assets.resolve_model("yolov8n.pt", override=str(custom)) == custom


def test_resolve_model_str_falls_back_to_filename(tmp_path, monkeypatch):
    """resolve_model_str returns the bare filename when nothing is found."""
    base = tmp_path / "empty"
    base.mkdir()
    monkeypatch.setattr(assets, "app_base_dir", lambda: base)
    monkeypatch.setattr(assets, "bundled_base_dir", lambda: base)
    monkeypatch.delenv(assets.MODELS_DIR_ENV, raising=False)
    monkeypatch.chdir(base)

    assert assets.resolve_model_str("yolov8n.pt") == "yolov8n.pt"
