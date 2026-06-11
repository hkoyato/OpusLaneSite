"""Unit tests for BrandTheme string outputs (no PySide6/QApplication required)."""

import sys
import types
from unittest.mock import MagicMock

# Stub PySide6 so gui.theme can be imported without the real Qt bindings.
_pyside6 = types.ModuleType("PySide6")
_qtgui = types.ModuleType("PySide6.QtGui")
_qtwidgets = types.ModuleType("PySide6.QtWidgets")
_qtgui.QFont = MagicMock()
_qtwidgets.QApplication = MagicMock()
sys.modules.setdefault("PySide6", _pyside6)
sys.modules.setdefault("PySide6.QtGui", _qtgui)
sys.modules.setdefault("PySide6.QtWidgets", _qtwidgets)

import pytest  # noqa: E402

from gui.theme import BrandTheme  # noqa: E402


class TestGetStylesheet:
    """Verify get_stylesheet() contains expected color hex values."""

    @pytest.mark.parametrize(
        "color",
        [
            "#004851",  # teal-dark
            "#00968F",  # teal
            "#93D500",  # green (via HEADER_GRADIENT in stylesheet)
            "#131E29",  # charcoal
            "#54565A",  # gray
            "#F4F7F7",  # bg
            "#FFFFFF",  # white
        ],
    )
    def test_stylesheet_contains_color(self, color: str) -> None:
        """Validates: Requirements 7.1"""
        sheet = BrandTheme.get_stylesheet()
        assert color in sheet, f"Expected {color} in stylesheet"

    def test_blue_constant_defined(self) -> None:
        """Validates: Requirements 7.1 — BLUE available for informational elements."""
        assert BrandTheme.BLUE == "#00A0E0"

    def test_orange_constant_defined(self) -> None:
        """Validates: Requirements 7.1 — ORANGE available for warning states."""
        assert BrandTheme.ORANGE == "#FF8200"

    def test_stylesheet_contains_roboto_font(self) -> None:
        """Validates: Requirements 7.2"""
        sheet = BrandTheme.get_stylesheet()
        assert "Roboto" in sheet


class TestHeaderGradient:
    """Verify gradient string matches spec."""

    def test_gradient_contains_stop_0(self) -> None:
        """Validates: Requirements 7.6"""
        assert "stop:0 #004851" in BrandTheme.HEADER_GRADIENT

    def test_gradient_contains_stop_058(self) -> None:
        """Validates: Requirements 7.6"""
        assert "stop:0.58 #00968F" in BrandTheme.HEADER_GRADIENT

    def test_gradient_contains_stop_1(self) -> None:
        """Validates: Requirements 7.6"""
        assert "stop:1 #93D500" in BrandTheme.HEADER_GRADIENT


class TestCardStyle:
    """Verify card_style() returns expected CSS properties."""

    def test_card_style_has_border_radius(self) -> None:
        """Validates: Requirements 7.1"""
        style = BrandTheme.card_style()
        assert "border-radius: 14px" in style

    def test_card_style_has_white_background(self) -> None:
        """Validates: Requirements 7.1"""
        style = BrandTheme.card_style()
        assert BrandTheme.WHITE in style
        assert "background-color:" in style
