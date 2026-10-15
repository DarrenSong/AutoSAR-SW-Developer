# -*- coding: utf-8 -*-
"""Entry point for ARXML Composition / Port Viewer."""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv
    app = QApplication(argv)
    app.setApplicationName("ARXML Composition Viewer")
    app.setOrganizationName("x_arxml")
    win = MainWindow()
    win.show()
    # optional CLI file
    if len(argv) > 1 and argv[1].lower().endswith(".arxml"):
        win.load_file(argv[1])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
