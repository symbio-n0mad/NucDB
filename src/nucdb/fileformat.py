"""Lesen und kanonisches Schreiben der JSON-Dateien (Spezifikation 3.4).

Kanonische Form::

    {"format": "nucdb/<name>", "schema_version": "x.y.z",
     "records": [
    {…ein Datensatz pro Zeile, Schlüssel sortiert, null-Felder weggelassen…},
    {…}
    ]}

Damit zeigt ``git diff`` nur echte Änderungen. Gelesen wird jede gültige JSON-Datei mit
``records``, egal wie sie formatiert ist (z. B. nach Bearbeitung mit einem anderen Tool).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from . import schema


class FormatError(ValueError):
    """Datei ist kein gültiges NucDB-JSON."""


def _clean(obj: Any) -> Any:
    """``None`` in Objekten entfernen (fehlendes Feld = null), rekursiv."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj


def dumps_record(record: dict) -> str:
    return json.dumps(_clean(record), sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(", ", ": "))


def dumps_file(name: str, records: Iterable[dict], schema_version: str = schema.SCHEMA_VERSION,
               *, sort: bool = True) -> str:
    """Datensätze in die kanonische Textform bringen. ``name`` ist z. B. ``"nuclides"``."""
    recs = list(records)
    if sort:
        recs.sort(key=schema.sort_key_for(name))
    head = (f'{{"format": {json.dumps(schema.format_id(name))}, '
            f'"schema_version": {json.dumps(schema_version)},\n "records": [\n')
    body = ",\n".join(dumps_record(r) for r in recs)
    return head + body + ("\n" if recs else "") + "]}\n"


def atomic_write_text(path: Path, text: str) -> None:
    """Datei ersetzen, ohne dass bei einem Absturz eine halbe Datei zurückbleibt."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_file(path: Path, name: str, records: Iterable[dict],
               schema_version: str = schema.SCHEMA_VERSION) -> None:
    atomic_write_text(Path(path), dumps_file(name, records, schema_version))


def read_json(path: Path) -> Any:
    path = Path(path)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as e:
        raise FormatError(f"{path}: kein gültiges JSON ({e})") from None


def read_file(path: Path) -> tuple[dict, list[dict]]:
    """Datei lesen → (Kopf ohne ``records``, Liste der Datensätze)."""
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("records"), list):
        raise FormatError(f"{path}: erwartet ein Objekt mit Liste 'records'")
    records = data.pop("records")
    for i, r in enumerate(records):
        if not isinstance(r, dict):
            raise FormatError(f"{path}: Datensatz {i} ist kein Objekt")
    return data, records


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
