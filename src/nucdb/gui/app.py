"""Start des Editors: ``nucdb editor [--db ORDNER] [--curation ORDNER]`` bzw. ``nucdb-editor``."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nucdb-editor", description="NucDB-Editor")
    p.add_argument("db", nargs="?", help="Datenbankordner (Standard: automatisch suchen)")
    p.add_argument("--curation", help="Kurationsordner für Änderungen an der zentralen Datenbank")
    p.add_argument("--no-overlay", action="store_true")
    args = p.parse_args(sys.argv[1:] if argv is None else argv)

    from PySide6.QtWidgets import QApplication

    from ..curation import Curation, default_curation_dir
    from ..db import NucDB
    from .main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    db = NucDB(args.db, overlay=not args.no_overlay)
    cur_dir = Path(args.curation) if args.curation else default_curation_dir()
    curation = Curation(cur_dir, db.location) if cur_dir and os.access(db.location, os.W_OK) else None
    w = MainWindow(db, curation)
    w.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
