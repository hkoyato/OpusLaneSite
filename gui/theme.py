"""Opus brand theme constants and stylesheet generator."""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


class BrandTheme:
    """Opus brand theme constants and stylesheet generator."""

    # Colors
    TEAL_DARK = "#004851"
    TEAL = "#00968F"
    GREEN = "#93D500"
    BLUE = "#00A0E0"
    ORANGE = "#FF8200"
    CHARCOAL = "#131E29"
    GRAY = "#54565A"
    BG = "#F4F7F7"
    WHITE = "#FFFFFF"
    CARD_BORDER = "rgba(19, 30, 41, 0.08)"

    # Gradient
    HEADER_GRADIENT = (
        "qlineargradient(x1:0, y1:0, x2:1, y2:1, "
        "stop:0 #004851, stop:0.58 #00968F, stop:1 #93D500)"
    )

    @staticmethod
    def get_stylesheet() -> str:
        """Return the full application QSS stylesheet."""
        return f"""
            /* Base background */
            QMainWindow, QWidget {{
                background-color: {BrandTheme.BG};
                font-family: "Roboto", "Arial", "Segoe UI", sans-serif;
                color: {BrandTheme.CHARCOAL};
            }}

            /* Card-style frames */
            QFrame[card="true"] {{
                background-color: {BrandTheme.WHITE};
                border: 1px solid {BrandTheme.CARD_BORDER};
                border-radius: 14px;
                padding: 20px;
            }}

            /* Primary button */
            QPushButton {{
                background-color: {BrandTheme.TEAL};
                color: {BrandTheme.WHITE};
                border: none;
                border-radius: 14px;
                padding: 10px 24px;
                font-size: 14px;
                font-weight: 600;
            }}

            QPushButton:hover {{
                background-color: #007A75;
            }}

            QPushButton:pressed {{
                background-color: {BrandTheme.TEAL_DARK};
            }}

            QPushButton:disabled {{
                background-color: {BrandTheme.GRAY};
                color: #AAAAAA;
            }}

            /* Labels */
            QLabel {{
                color: {BrandTheme.CHARCOAL};
                background: transparent;
                border: none;
            }}

            QLabel[secondary="true"] {{
                color: {BrandTheme.GRAY};
            }}

            /* Type hierarchy. min-height guards against environments where the
               resolved font reports a degenerate (clipped) line height. */
            QLabel[role="page-title"] {{
                font-size: 40px;
                font-weight: 700;
                min-height: 48px;
            }}

            QLabel[role="section-title"] {{
                font-size: 26px;
                font-weight: 700;
                min-height: 34px;
            }}

            QLabel[role="card-title"] {{
                font-size: 17px;
                font-weight: 600;
                min-height: 24px;
            }}

            QLabel[role="body"] {{
                font-size: 15px;
                font-weight: 400;
                min-height: 22px;
            }}

            QLabel[role="metric"] {{
                font-size: 42px;
                font-weight: 700;
                color: {BrandTheme.TEAL_DARK};
                min-height: 50px;
            }}

            QLabel[role="caption"] {{
                font-size: 12px;
                font-weight: 400;
                color: {BrandTheme.GRAY};
                min-height: 18px;
            }}

            /* Header area */
            QFrame[header="true"] {{
                background: {BrandTheme.HEADER_GRADIENT};
                border: none;
                border-radius: 0px;
            }}

            QFrame[header="true"] QLabel {{
                color: {BrandTheme.WHITE};
            }}

            /* Progress bar */
            QProgressBar {{
                border: 1px solid {BrandTheme.CARD_BORDER};
                border-radius: 7px;
                background-color: #E8EDED;
                text-align: center;
                font-size: 12px;
                color: {BrandTheme.CHARCOAL};
                min-height: 14px;
            }}

            QProgressBar::chunk {{
                background-color: {BrandTheme.TEAL};
                border-radius: 6px;
            }}

            /* Slider */
            QSlider::groove:horizontal {{
                border: none;
                height: 6px;
                background: #E8EDED;
                border-radius: 3px;
            }}

            QSlider::handle:horizontal {{
                background: {BrandTheme.TEAL};
                width: 16px;
                height: 16px;
                margin: -5px 0;
                border-radius: 8px;
            }}

            QSlider::sub-page:horizontal {{
                background: {BrandTheme.TEAL};
                border-radius: 3px;
            }}

            /* Table */
            QTableWidget {{
                background-color: {BrandTheme.WHITE};
                border: 1px solid {BrandTheme.CARD_BORDER};
                border-radius: 14px;
                gridline-color: {BrandTheme.CARD_BORDER};
                font-size: 14px;
            }}

            QTableWidget::item {{
                padding: 8px;
            }}

            QHeaderView::section {{
                background-color: {BrandTheme.BG};
                color: {BrandTheme.CHARCOAL};
                font-weight: 600;
                font-size: 13px;
                border: none;
                border-bottom: 1px solid {BrandTheme.CARD_BORDER};
                padding: 8px;
            }}

            /* Scroll bars */
            QScrollBar:vertical {{
                width: 8px;
                background: transparent;
            }}

            QScrollBar::handle:vertical {{
                background: #C4C8CB;
                border-radius: 4px;
                min-height: 20px;
            }}

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}

            /* Combo box */
            QComboBox {{
                border: 1px solid {BrandTheme.CARD_BORDER};
                border-radius: 8px;
                padding: 6px 12px;
                background-color: {BrandTheme.WHITE};
                font-size: 14px;
            }}

            /* Spin box */
            QSpinBox {{
                border: 1px solid {BrandTheme.CARD_BORDER};
                border-radius: 8px;
                padding: 6px 12px;
                background-color: {BrandTheme.WHITE};
                font-size: 14px;
            }}

            /* Toggle / checkbox */
            QCheckBox {{
                font-size: 14px;
                spacing: 8px;
            }}

            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border-radius: 4px;
                border: 1px solid {BrandTheme.GRAY};
            }}

            QCheckBox::indicator:checked {{
                background-color: {BrandTheme.TEAL};
                border-color: {BrandTheme.TEAL};
            }}
        """

    # Cached name of the registered font family (resolved at apply()).
    _FONT_FAMILY: str | None = None

    @staticmethod
    def _register_fonts() -> str:
        """Register bundled Roboto TTFs with Qt and return the family name.

        Falls back to "Roboto" (or system sans-serif) if the bundled files are
        missing or cannot be loaded. Registering an application font guarantees
        correct font metrics even on systems where Qt cannot locate any system
        fonts (which otherwise produces clipped text from a degenerate line
        height).
        """
        if BrandTheme._FONT_FAMILY is not None:
            return BrandTheme._FONT_FAMILY

        family = "Roboto"
        try:
            from gui.resources import FONT_PATHS

            loaded_families: list[str] = []
            for path in FONT_PATHS:
                if not path.exists():
                    continue
                font_id = QFontDatabase.addApplicationFont(str(path))
                if font_id != -1:
                    loaded_families.extend(QFontDatabase.applicationFontFamilies(font_id))
            if loaded_families:
                family = loaded_families[0]
        except Exception:  # pragma: no cover - defensive; fall back to default
            family = "Roboto"

        BrandTheme._FONT_FAMILY = family
        return family

    @staticmethod
    def apply(app: QApplication) -> None:
        """Apply theme: register Roboto, set the app font, apply stylesheet."""
        family = BrandTheme._register_fonts()
        font = QFont()
        font.setFamilies([family, "Roboto", "Arial", "Segoe UI"])
        font.setPointSize(10)
        font.setWeight(QFont.Weight.Normal)
        app.setFont(font)
        app.setStyleSheet(BrandTheme.get_stylesheet())

    @staticmethod
    def card_style() -> str:
        """Return inline QSS for card styling (14px radius, white bg, border)."""
        return (
            f"background-color: {BrandTheme.WHITE}; "
            f"border: 1px solid {BrandTheme.CARD_BORDER}; "
            f"border-radius: 14px; "
            f"padding: 20px;"
        )
