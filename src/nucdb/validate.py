"""Prüfung einer Datenbank (z. B. nach Bearbeitung mit einem anderen Tool): ``nucdb validate``."""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from . import names, schema
from .fileformat import FormatError, read_file, read_json, sha256_of
from .locate import MANIFEST


@dataclass(frozen=True)
class Issue:
    level: str          # "error" | "warning"
    file: str
    record: str
    message: str

    def __str__(self) -> str:
        where = f"{self.file}" + (f" [{self.record}]" if self.record else "")
        return f"{self.level.upper():7s} {where}: {self.message}"


def validate(path: str | Path, *, check_hashes: bool = True, overlay: bool = False,
             distributable: bool = False) -> list[Issue]:
    """Datenbankordner prüfen. ``overlay=True`` für eine Ergänzungsdatenbank (lockerere Regeln).

    ``distributable=True``: Fehler, wenn Daten aus Quellen mit ``redistributable: false`` enthalten
    sind (Pflicht für die mitgelieferte Momentaufnahme und jede Veröffentlichung).
    """
    root = Path(path)
    issues: list[Issue] = []

    def err(f, r, m):
        issues.append(Issue("error", f, r, m))

    def warn(f, r, m):
        issues.append(Issue("warning", f, r, m))

    if not (root / MANIFEST).is_file():
        err(MANIFEST, "", "fehlt")
        return issues
    try:
        manifest = read_json(root / MANIFEST)
    except FormatError as e:
        err(MANIFEST, "", str(e))
        return issues
    sv = str(manifest.get("schema_version", ""))
    try:
        if not schema.is_compatible(sv):
            err(MANIFEST, "", f"Schema {sv} ist nicht kompatibel mit {schema.SCHEMA_VERSION}")
    except ValueError as e:
        err(MANIFEST, "", str(e))

    data: dict[str, list[dict]] = {}
    for spec in schema.FILES.values():
        p = root / f"{spec.name}.json"
        if not p.is_file():
            if not overlay and spec.name in ("sources", "quantities", "nuclides"):
                err(p.name, "", "Datei fehlt")
            continue
        try:
            head, recs = read_file(p)
        except FormatError as e:
            err(p.name, "", str(e))
            continue
        if head.get("format") != schema.format_id(spec.name):
            warn(p.name, "", f"format ist {head.get('format')!r}, erwartet {schema.format_id(spec.name)!r}")
        data[spec.name] = recs
        for i, r in enumerate(recs):
            missing = [k for k in spec.required if r.get(k) is None]
            if missing:
                err(p.name, f"#{i}", f"Pflichtfeld(er) fehlen: {', '.join(missing)}")

    # Prüfsummen
    if check_hashes and not overlay:
        files = manifest.get("files") or {}
        for fname, info in files.items():
            p = root / fname
            if not p.is_file():
                err(MANIFEST, fname, "im Manifest aufgeführt, Datei fehlt")
            elif isinstance(info, dict) and info.get("sha256") and info["sha256"] != sha256_of(p):
                warn(MANIFEST, fname, "Prüfsumme stimmt nicht (Datei geändert?) – "
                                      "mit 'nucdb manifest' aktualisieren")
        for p in sorted(root.glob("*.json")):
            if p.name != MANIFEST and p.name not in files:
                warn(MANIFEST, p.name, "Datei fehlt im Manifest")

    # Quellen
    source_keys = {str(s.get("key")) for s in data.get("sources", [])}
    if overlay:
        source_keys.add("user")
    dup = _dups(str(s.get("key")) for s in data.get("sources", []))
    for k in dup:
        err("sources.json", k, "Quelle mehrfach definiert")

    blocked = {str(s.get("key")) for s in data.get("sources", []) if s.get("redistributable") is False}
    blocked_hits: dict[str, int] = {}

    def check_source(fname: str, rec_id: str, key) -> None:
        if key is not None and str(key) not in source_keys and not overlay:
            err(fname, rec_id, f"unbekannte Quelle {key!r}")
        if distributable and key is not None and str(key) in blocked:
            blocked_hits[fname] = blocked_hits.get(fname, 0) + 1

    # Größen
    quantities = {str(q.get("quantity")): q for q in data.get("quantities", [])}
    for q in quantities.values():
        if q.get("dtype") not in ("real", "int", "text"):
            err("quantities.json", str(q.get("quantity")), f"dtype {q.get('dtype')!r} unbekannt")

    # Nuklide
    nuclide_names: set[str] = set()
    stable: set[str] = set()
    for r in data.get("nuclides", []):
        name = str(r.get("name"))
        try:
            nid = names.parse(name)
        except names.NuclideNameError as e:
            err("nuclides.json", name, str(e))
            continue
        if nid.name != name:
            err("nuclides.json", name, f"Name nicht kanonisch, richtig wäre {nid.name}")
        if (r.get("z"), r.get("a"), r.get("isomer", 0)) != (nid.z, nid.a, nid.isomer):
            err("nuclides.json", name, f"z/a/isomer passen nicht zum Namen ({r.get('z')}/{r.get('a')}/"
                                       f"{r.get('isomer', 0)})")
        if nid.name in nuclide_names:
            err("nuclides.json", name, "doppelt")
        nuclide_names.add(nid.name)
        if r.get("stable"):
            stable.add(nid.name)
        ds = r.get("decay_source")
        if ds is not None:
            check_source("nuclides.json", name, ds)
        for q, vals in (r.get("values") or {}).items():
            if q not in quantities and not overlay:
                warn("nuclides.json", name, f"Größe {q!r} fehlt in quantities.json")
            if not isinstance(vals, list):
                err("nuclides.json", name, f"values.{q} muss eine Liste sein")
                continue
            prefs = sum(1 for v in vals if isinstance(v, dict) and v.get("preferred"))
            if len(vals) > 1 and prefs != 1:
                err("nuclides.json", name, f"{q}: {len(vals)} Werte, aber {prefs} bevorzugt (genau 1 nötig)")
            for v in vals:
                if not isinstance(v, dict) or "value" not in v:
                    err("nuclides.json", name, f"{q}: Wert ohne 'value'")
                    continue
                check_source("nuclides.json", name, v.get("source"))
                dtype = (quantities.get(q) or {}).get("dtype")
                val = v.get("value")
                if dtype in ("real", "int") and not (isinstance(val, (int, float)) and math.isfinite(val)):
                    err("nuclides.json", name, f"{q}: kein gültiger Zahlenwert {val!r}")
                if q == "half_life_s" and isinstance(val, (int, float)) and val <= 0:
                    err("nuclides.json", name, f"{q}: muss positiv sein")

    def known(n) -> bool:
        return n is None or overlay or _canon(n) in nuclide_names

    # Zerfallsarten
    sums: dict[tuple[str, str], float] = defaultdict(float)
    incomplete: set[tuple[str, str]] = set()     # Verzweigungen nicht vollständig bekannt
    parents: set[str] = set()
    for r in data.get("decay_modes", []):
        parent = _canon(r.get("parent"))
        rid = f"{parent} {r.get('mode', '?')}"
        parents.add(parent)
        check_source("decay_modes.json", rid, r.get("source"))
        if not known(parent):
            err("decay_modes.json", rid, "Mutter fehlt in nuclides.json")
        if parent in stable and r.get("branching_flag") != "?":
            warn("decay_modes.json", rid, "Mutter ist als stabil markiert (Zerfall nicht beobachtet?)")
        d = r.get("daughter")
        mode = str(r.get("mode") or "")
        if d is None and not (mode.endswith("SF") or "+" in mode.strip("+-").replace("EC+B+", "")
                              or r.get("branching_flag") == "?"):
            warn("decay_modes.json", rid, "keine Tochter angegeben")
        elif d is not None and not known(d):
            warn("decay_modes.json", rid, f"Tochter {d} fehlt in nuclides.json (Kette endet hier, "
                                          "die Tochter gilt nicht als stabil)")
        b = r.get("branching")
        if b is not None:
            if not isinstance(b, (int, float)) or not 0 <= b <= 1.000001:
                err("decay_modes.json", rid, f"branching {b!r} nicht in 0…1")
            elif not r.get("parent_mode"):
                sums[(parent, str(r.get("source")))] += b
        if not r.get("parent_mode") and (b is None or r.get("branching_flag") in ("<", ">", "?")):
            incomplete.add((parent, str(r.get("source"))))
    for (parent, src), s in sums.items():
        if (parent, src) not in incomplete and abs(s - 1.0) > 0.011:
            warn("decay_modes.json", parent, f"Summe der Verzweigungen ({src}) = {s:.4f}, erwartet ≈ 1")
    if not overlay:
        for n in sorted(nuclide_names - stable - parents, key=names.sort_key):
            r = next(x for x in data.get("nuclides", []) if _canon(x.get("name")) == n)
            if (r.get("values") or {}).get("half_life_s"):
                warn("nuclides.json", n, "instabil, aber keine Zerfallsart bekannt")

    # Strahlung
    for kind, fname in schema.EMISSION_FILES.items():
        for i, r in enumerate(data.get(fname, [])):
            rid = f"{_canon(r.get('nuclide'))} {r.get('energy_kev')}"
            check_source(f"{fname}.json", rid, r.get("source"))
            if not known(r.get("nuclide")):
                err(f"{fname}.json", rid, "Nuklid fehlt in nuclides.json")
            e = r.get("energy_kev")
            if not isinstance(e, (int, float)) or e <= 0:
                err(f"{fname}.json", rid, f"energy_kev {e!r} ungültig")
            it = r.get("intensity")
            limit = 10.0 if kind == "electron" else 2.2 if r.get("radiation") in ("ANN", "XL", "XK") else 1.0
            if it is not None and (not isinstance(it, (int, float)) or it < 0):
                err(f"{fname}.json", rid, f"intensity {it!r} ungültig")
            elif it is not None and it > limit * 1.05:
                warn(f"{fname}.json", rid, f"intensity {it:g} über {limit:g} (so in der Quelle; evtl. relative Angabe)")
            if kind == "beta":
                if r.get("type") not in ("B-", "B+"):
                    err(f"{fname}.json", rid, f"type {r.get('type')!r} (B- oder B+ erwartet)")
                me = r.get("mean_energy_kev")
                if isinstance(me, (int, float)) and isinstance(e, (int, float)) and me > e:
                    err(f"{fname}.json", rid, "mittlere Energie größer als Endpunktenergie")

    for i, r in enumerate(data.get("special_lines", [])):
        rid = f"{r.get('kind')} #{i}"
        check_source("special_lines.json", rid, r.get("source"))
        if r.get("kind") not in schema.SPECIAL_KINDS:
            warn("special_lines.json", rid, f"unbekannte Art {r.get('kind')!r}")

    for i, r in enumerate(data.get("prompt_gamma", [])):
        rid = f"{_canon(r.get('target'))} {r.get('energy_kev')}"
        check_source("prompt_gamma.json", rid, r.get("source"))
        if not known(r.get("target")):
            warn("prompt_gamma.json", rid, "Target fehlt in nuclides.json")

    for r in data.get("activation_gamma", []):
        check_source("activation_gamma.json", str(r.get("target")), r.get("source"))
    for r in data.get("elements", []):
        for k in ("atomic_weight_source", "sigma_capture_source"):
            if r.get(k):
                check_source("elements.json", str(r.get("symbol")), r.get(k))
    if distributable:
        for fname, n in blocked_hits.items():
            err(fname, "", f"{n} Einträge aus nicht weitergebbaren Quellen ({', '.join(sorted(blocked))})")
        if blocked and not blocked_hits:
            warn("sources.json", "", f"nicht weitergebbare Quelle(n) aufgeführt, aber ungenutzt: {', '.join(sorted(blocked))}")
    return issues


def _canon(n) -> str:
    try:
        return names.normalize(str(n))
    except names.NuclideNameError:
        return str(n)


def _dups(items) -> list[str]:
    seen, dup = set(), []
    for x in items:
        if x in seen and x not in dup:
            dup.append(x)
        seen.add(x)
    return dup
