"""Entry point for the live-layout variant."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PyQt5.QtGui import QColor, QPalette
from PyQt5.QtWidgets import QApplication

from .mainwindow import LiveMainWindow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pymindmap.live",
        description="Live-layout mindmap — nodes auto-arrange as you add/edit.",
    )
    parser.add_argument("path", nargs="?", help="JSON file to open")
    args = parser.parse_args(argv)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    _apply_palette(app)

    win = LiveMainWindow()
    win.show()
    if args.path:
        p = Path(args.path)
        if p.exists():
            win.load_path(p)

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
