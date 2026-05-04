"""Entry point for the live-layout variant."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PyQt5.QtCore import QSettings, Qt
from PyQt5.QtGui import QColor, QIcon, QPalette
from PyQt5.QtWidgets import QApplication

from .mainwindow import LiveMainWindow


ICON_PATH = Path(__file__).with_name("resources") / "icon.png"
# Identifiers used for QSettings so the "recent file" entry lands in a
# stable location on every platform.
ORG_NAME = "pymindmap"
APP_NAME = "pymindmap-live"
RECENT_KEY = "recent_path"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pymindmap.live",
        description="Live-layout mindmap — nodes auto-arrange as you add/edit.",
    )
    parser.add_argument("path", nargs="?", help="JSON file to open")
    args = parser.parse_args(argv)

    # Consistent rendering across displays with different DPIs. Must be set
    # BEFORE the QApplication is constructed.
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # QSettings (used by the main window to persist the last-opened file)
    # picks up these identifiers automatically.
    app.setOrganizationName(ORG_NAME)
    app.setApplicationName(APP_NAME)
    _apply_palette(app)

    icon = QIcon(str(ICON_PATH)) if ICON_PATH.exists() else QIcon()
    if not icon.isNull():
        app.setWindowIcon(icon)

    win = LiveMainWindow()
    if not icon.isNull():
        win.setWindowIcon(icon)
    win.show()

    # Open precedence: explicit CLI arg → most recently opened file.
    path_to_open: Path | None = None
    if args.path:
        p = Path(args.path)
        if p.exists():
            path_to_open = p
    else:
        settings = QSettings()
        recent = settings.value(RECENT_KEY, "", type=str)
        if recent:
            p = Path(recent)
            if p.exists():
                path_to_open = p
    if path_to_open is not None:
        win.load_path(path_to_open)

    return app.exec_()


def _apply_palette(app: QApplication) -> None:
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#0b0b10"))
    pal.setColor(QPalette.WindowText, QColor("#e9e9ef"))
    pal.setColor(QPalette.Base, QColor("#12121a"))
    pal.setColor(QPalette.AlternateBase, QColor("#1a1a24"))
    pal.setColor(QPalette.Text, QColor("#e9e9ef"))
    pal.setColor(QPalette.Button, QColor("#17171f"))
    pal.setColor(QPalette.ButtonText, QColor("#e9e9ef"))
    pal.setColor(QPalette.Highlight, QColor("#7c7cf5"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor("#1a1a24"))
    pal.setColor(QPalette.ToolTipText, QColor("#e9e9ef"))
    pal.setColor(QPalette.PlaceholderText, QColor("#6b6b7c"))
    app.setPalette(pal)


if __name__ == "__main__":
    sys.exit(main())
