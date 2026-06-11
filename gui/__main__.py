"""Application entry point for the Opus LaneSight GUI.

Run with ``python -m gui``. Initializes a QApplication, applies the Opus
Brand_Theme, constructs the MainWindow, and starts the Qt event loop.

Startup failures are handled gracefully (Requirement 1.6):
- A missing PySide6 dependency prints a clear message and exits with code 1.
- Any other unrecoverable startup error shows a critical dialog (when a
  QApplication is available) before exiting with code 1.
"""

from __future__ import annotations

import os
import sys

# --- PySide6 import guard (Requirement 1.6) -------------------------------
# PySide6 is the critical runtime dependency. If it is missing we cannot show
# a Qt dialog, so fall back to a clear console message and exit.
try:
    from PySide6.QtWidgets import QApplication, QMessageBox
except ImportError as exc:  # pragma: no cover - exercised only without PySide6
    _missing = "PySide6"
    sys.stderr.write(
        f"Opus LaneSight could not start: required dependency '{_missing}' is "
        f"not installed.\n"
        f"Install it with: pip install {_missing}\n"
        f"Details: {exc}\n"
    )
    sys.exit(1)


def main() -> int:
    """Initialize the application and run the Qt event loop.

    Returns the process exit code.
    """
    # Allow headless/CI environments to opt into the offscreen platform plugin
    # by setting QT_QPA_PLATFORM before launch. We never force offscreen here
    # so normal desktop runs render a real window.
    if not os.environ.get("QT_QPA_PLATFORM"):
        # Leave unset: Qt selects the native platform plugin (windows).
        pass

    app = QApplication.instance() or QApplication(sys.argv)

    try:
        from gui.theme import BrandTheme

        BrandTheme.apply(app)

        from gui.main_window import MainWindow

        window = MainWindow()
        window.show()
    except Exception as exc:  # noqa: BLE001 - surface any startup failure to user
        # Unrecoverable startup error: show a dialog if we can, then exit (1).
        message = (
            "Opus LaneSight failed to start.\n\n"
            f"{type(exc).__name__}: {exc}"
        )
        sys.stderr.write(message + "\n")
        try:
            QMessageBox.critical(None, "Opus LaneSight — startup error", message)
        except Exception:  # noqa: BLE001 - dialog is best-effort only
            pass
        return 1

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
