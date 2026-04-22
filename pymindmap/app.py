"""Application entry point."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PyQt5.QtWidgets import QApplication

from .mainwindow import MainWindow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pymindmap", description="Node-based mindmap editor")
    parser.add_argument("path", nargs="?", help="JSON file to open")
    args = parser.parse_args(argv)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    _apply_dark_palette(app)

    win = MainWindow()
    win.show()

    if args.path:
        p = Path(args.path)
        if p.exists():
            win.load_path(p)

    return app.exec_()


def _apply_dark_palette(app: QApplication) -> None:
    from PyQt5.QtGui import QColor, QPalette
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#0f0f12"))
    pal.setColor(QPalette.WindowText, QColor("#e6e6ea"))
    pal.setColor(QPalette.Base, QColor("#141418"))
    pal.setColor(QPalette.AlternateBase, QColor("#1a1a1e"))
    pal.setColor(QPalette.Text, QColor("#e6e6ea"))
    pal.setColor(QPalette.Button, QColor("#1a1a1e"))
    pal.setColor(QPalette.ButtonText, QColor("#e6e6ea"))
    pal.setColor(QPalette.Highlight, QColor("#6366f1"))
    pal.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ToolTipBase, QColor("#1a1a1e"))
    pal.setColor(QPalette.ToolTipText, QColor("#e6e6ea"))
    app.setPalette(pal)


if __name__ == "__main__":
    sys.exit(main())
