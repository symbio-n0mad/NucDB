"""Fundort der Datenbank und der Ergänzungsdatenbank (Spezifikation 2 und 8).

Bewusst ohne Umgebungsvariable und ohne Zusatzpakete. Unter Linux wird ``XDG_DATA_HOME``
beachtet, falls gesetzt, das entspricht dem Standard-Datenordner (sonst ``~/.local/share``).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

MANIFEST = "manifest.json"
PACKAGE_DATA = Path(__file__).with_name("data")


def _user_data_root() -> Path:
    if sys.platform.startswith("win"):
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def nucoffice_candidates() -> list[Path]:
    """Mögliche NucOffice-Datenordner: zuerst Benutzer-, dann systemweite Installation."""
    if sys.platform.startswith("win"):
        user = _user_data_root() / "NucOffice" / "data" / "nucdb"
        system = Path(os.environ.get("ProgramFiles") or r"C:\Program Files") / "NucOffice" / "data" / "nucdb"
    elif sys.platform == "darwin":
        user = _user_data_root() / "NucOffice" / "data" / "nucdb"
        system = Path("/Library/Application Support/NucOffice/data/nucdb")
    else:
        user = _user_data_root() / "nucoffice" / "data" / "nucdb"
        system = Path("/opt/nucoffice/data/nucdb")
    return [user, system]


def default_overlay_dir() -> Path:
    """Ordner der gemeinsamen Ergänzungsdatenbank aller Tools."""
    return _user_data_root() / "nucdb-user"


def is_database(path: Path) -> bool:
    return (Path(path) / MANIFEST).is_file()


def find_database(path: str | os.PathLike | None = None) -> Path:
    """Datenbankordner nach der Reihenfolge aus Spezifikation 2 bestimmen."""
    if path is not None:
        p = Path(path).expanduser()
        if p.is_file() and p.name == MANIFEST:
            p = p.parent
        if not is_database(p):
            raise FileNotFoundError(f"Keine NucDB-Datenbank (manifest.json fehlt): {p}")
        return p
    for cand in nucoffice_candidates():
        if is_database(cand):
            return cand
    if is_database(PACKAGE_DATA):
        return PACKAGE_DATA
    raise FileNotFoundError("Keine NucDB-Datenbank gefunden (weder NucOffice-Datenordner noch "
                            "mitgelieferte Momentaufnahme)")
