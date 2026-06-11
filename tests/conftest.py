"""Shared pytest fixtures for the Opus LaneSight GUI test suite.

Forces the headless ``offscreen`` Qt platform so tests run without a display
server, and provides a session-scoped ``QApplication`` required for any test
that constructs Qt objects (QImage, QThread, signals).
"""

from __future__ import annotations

import os

# Must be set before any QApplication is created.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Eagerly import the real PySide6 bindings so they occupy sys.modules before any
# test module attempts to stub them via ``sys.modules.setdefault`` (e.g.
# test_theme.py). This keeps test_theme's optional Qt stub a no-op when the real
# bindings are installed, so module collection order cannot shadow the genuine
# package for tests that need it (e.g. test_worker.py).
try:  # pragma: no cover - environment dependent
    import PySide6  # noqa: F401
    import PySide6.QtCore  # noqa: F401
    import PySide6.QtGui  # noqa: F401
    import PySide6.QtWidgets  # noqa: F401
except ImportError:
    pass

import pytest


@pytest.fixture(scope="session")
def qapp():
    """Provide a single QApplication instance for the whole test session."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
