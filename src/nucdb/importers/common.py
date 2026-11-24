"""Gemeinsame Bausteine der Importer: Werte einsortieren, bevorzugte Werte bestimmen, Quellen."""

from __future__ import annotations

import datetime as _dt
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from .. import names
from ..fileformat import read_file, read_json, sha256_of, write_file
from ..locate import MANIFEST

#: Quellen, die beim Bestimmen des bevorzugten Werts immer vorgehen (bewusste Korrekturen)
MANUAL_SOURCES = ("manual",)

#: Abweichende Rangfolge für einzelne Größen; sonst gilt manifest.source_priority
QUANTITY_PRIORITY = {
    "mass_u": ["AME2020", "NUBASE2020"],
    "mass_excess_kev": ["AME2020", "NUBASE2020"],
    "binding_energy_per_nucleon_kev": ["AME2020"],
    "q_beta_minus_kev": ["AME2020"],
    "q_alpha_kev": ["AME2020"],
    "q_ec_kev": ["AME2020"],
}


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def download(url: str, target: Path) -> Path:
    """Datei herunterladen (ohne persönliche Angaben im User-Agent)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "nucdb-importer"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(target, "wb") as fh:
        fh.write(resp.read())
    return target


def _priority(root: Path, quantity: str) -> list[str]:
    base = []
    mp = root / MANIFEST
    if mp.is_file():
        base = list(read_json(mp).get("source_priority") or [])
    return list(MANUAL_SOURCES) + QUANTITY_PRIORITY.get(quantity, []) + [s for s in base if s not in
                                                                        QUANTITY_PRIORITY.get(quantity, [])]


def choose_preferred(values: list[dict], priority: list[str]) -> None:
    """Genau einen Wert als bevorzugt markieren: nach Quellenrang, bei Gleichstand der erste."""
    if not values:
        return
    rank = {s: i for i, s in enumerate(priority)}
    best = min(range(len(values)), key=lambda i: (rank.get(values[i].get("source"), len(rank)), i))
    for i, v in enumerate(values):
        if i == best:
            v["preferred"] = True
        else:
            v.pop("preferred", None)


def upsert_source(root: Path, record: dict) -> None:
    p = root / "sources.json"
    recs = read_file(p)[1] if p.is_file() else []
    recs = [r for r in recs if r.get("key") != record["key"]] + [record]
    write_file(p, "sources", recs)


def replace_nuclide_data(root: Path, source: str, nuclides: dict[str, dict],
                         values: dict[str, dict[str, list[dict]]]) -> tuple[int, int]:
    """Nuklide anlegen/ergänzen und alle Werte der Quelle ``source`` ersetzen.

    :param nuclides: Name → Stammdaten (z, a, isomer, stable, weitere Felder). Bestehende Felder
        werden nur ergänzt bzw. bei ``stable`` überschrieben.
    :param values: Name → Größe → Liste neuer Werte (ohne ``preferred``).
    :returns: (neu angelegte Nuklide, geschriebene Werte)
    """
    p = root / "nuclides.json"
    recs = read_file(p)[1] if p.is_file() else []
    by_name = {r["name"]: r for r in recs}
    created = 0
    for name, meta in nuclides.items():
        rec = by_name.get(name)
        if rec is None:
            rec = by_name[name] = {"name": name, "values": {}}
            created += 1
        for k, v in meta.items():
            if k in ("z", "a", "isomer", "stable") or k not in rec:
                rec[k] = v
    # alte Werte dieser Quelle entfernen, neue einfügen
    touched: set[tuple[str, str]] = set()
    for rec in by_name.values():
        for q, vals in list((rec.get("values") or {}).items()):
            keep = [v for v in vals if v.get("source") != source]
            if len(keep) != len(vals):
                touched.add((rec["name"], q))
            rec["values"][q] = keep
    written = 0
    for name, qs in values.items():
        rec = by_name[name]
        for q, vals in qs.items():
            rec.setdefault("values", {}).setdefault(q, []).extend(dict(v, source=source) for v in vals)
            touched.add((name, q))
            written += len(vals)
    prio_cache: dict[str, list[str]] = {}
    for name, q in touched:
        vals = by_name[name]["values"].get(q, [])
        if not vals:
            by_name[name]["values"].pop(q, None)
            continue
        if q not in prio_cache:
            prio_cache[q] = _priority(root, q)
        # Eine bewusste Festlegung in "manual" bleibt bestehen
        if not any(v.get("preferred") and v.get("source") in MANUAL_SOURCES for v in vals):
            choose_preferred(vals, prio_cache[q])
    write_file(p, "nuclides", by_name.values())
    return created, written


def replace_records(root: Path, file: str, source: str, new: Iterable[dict]) -> int:
    """Alle Datensätze einer Quelle in einer Listendatei ersetzen."""
    p = root / f"{file}.json"
    recs = read_file(p)[1] if p.is_file() else []
    new = [dict(r, source=source) for r in new]
    write_file(p, file, [r for r in recs if r.get("source") != source] + new)
    return len(new)


def log_import(root: Path, source: str, summary: str) -> None:
    p = root / "changelog.json"
    recs = read_file(p)[1] if p.is_file() else []
    recs.append({"changed_at": now(), "file": "*", "record": source, "field": None, "old": None,
                 "new": summary, "comment": f"Import {source}"})
    write_file(p, "changelog", recs)


def file_info(path: Path) -> dict:
    return {"file_name": path.name, "file_sha256": sha256_of(path)}


def group_by_parent(modes: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for m in modes:
        out[m["parent"]].append(m)
    return out


def nuclide_name(z: int, a: int, isomer: int = 0) -> str:
    return names.canonical_name(z, a, isomer)
