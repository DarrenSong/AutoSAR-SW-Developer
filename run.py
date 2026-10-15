# -*- coding: utf-8 -*-
"""Launch viewer from inside this folder or from project root.

Usage (cwd = arxml_viewer):
  pip install -r requirements.txt
  python run.py
  python run.py ..\\ZCUD_CP_26R3_arxml_export_v2.0_beta0.7.arxml

Usage (cwd = x_arxml_v2.0):
  python -m arxml_viewer ZCUD_CP_26R3_arxml_export_v2.0_beta0.7.arxml
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(here)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    # Resolve relative ARXML paths: prefer cwd, then project root (parent)
    argv = list(sys.argv)
    if len(argv) > 1 and argv[1].lower().endswith(".arxml"):
        p = argv[1]
        if not os.path.isabs(p) and not os.path.isfile(p):
            cand = os.path.join(parent, p)
            if os.path.isfile(cand):
                argv[1] = cand

    from arxml_viewer.app import main as app_main

    return app_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
