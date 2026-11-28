"""Pflege der zentralen Datenbank mit Quellenpflicht (Editor, Etappe 5).

Korrekturen und Ergänzungen an der zentralen Datenbank landen zuerst im **Kurationsordner**
(Standard: ``curation/`` im Repository) und werden dann in die Datenbank übernommen. Der Ordner
hat dasselbe Dateiformat wie die Datenbank (nur die nötigen Dateien) plus ``removals.json`` für
entfernte Einträge. ``nucdb build`` wendet ihn nach den Importern erneut an; so überstehen
Korrekturen jeden Neuaufbau aus den Rohdaten. Das Anwenden ist idempotent.

Regeln:

- Jeder Eintrag braucht eine **Quelle** aus ``sources.json`` (zentral oder im Kurationsordner). Die
  Quelle ``user`` ist verboten. Ein neuer Wert einer Quelle ersetzt den Wert derselben Quelle.
- Entfernen braucht eine **Begründung**.
- In eine weitergebbare Datenbank gelangen keine Einträge aus nicht weitergebbaren Quellen.
- Einträge der Ergänzungsdatenbank (Overlay) lassen sich mit einer echten Quelle übernehmen
  (:meth:`Curation.adopt`).

Wird vom Editor und von ``nucdb build`` verwendet, nicht von Konsumenten.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Sequence

from . import names, schema
from .fileformat import read_file, write_file
from .locate import PACKAGE_DATA
from .maintenance import update_manifest
from .overlay import USER_SOURCE, UserDB

if TYPE_CHECKING:  # pragma: no cover
    from .db import NucDB

#: Dateien, die der Kurationsordner enthalten darf (Reihenfolge = Reihenfolge beim Anwenden)
CURATION_FILES = ("sources", "quantities", "nuclides", "decay_modes", "isomer_feeding", "decay_gamma",
                  "decay_alpha", "decay_beta", "decay_electron", "special_lines")
REMOVALS = "removals"
_SOURCE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ekey(r: dict) -> tuple:
    return (str(r.get("nuclide")), str(r.get("source")), round(float(r.get("energy_kev", 0) or 0), 3))


_KEYS = {
    "sources": lambda r: (str(r.get("key")),),
    "quantities": lambda r: (str(r.get("quantity")),),
    "nuclides": lambda r: (str(r.get("name")),),
    "decay_modes": lambda r: (str(r.get("parent")), str(r.get("daughter")), str(r.get("mode")),
                              str(r.get("source"))),
    "isomer_feeding": lambda r: (str(r.get("parent")), str(r.get("isomer")), str(r.get("source"))),
    **{f: _ekey for f in schema.EMISSION_FILES.values()},
}


def record_key(file: str, rec: dict) -> tuple:
    """Schlüssel, unter dem ein kuratierter Datensatz einen vorhandenen ersetzt."""
    f = _KEYS.get(file)
    return f(rec) if f else (json.dumps(rec, sort_keys=True),)


def _kj(key: Iterable) -> str:
    return json.dumps(list(key))


def default_curation_dir() -> Path | None:
    """``curation/`` im Repository, wenn NucDB aus einem Quellcode-Checkout läuft, sonst ``None``."""
    repo = Path(__file__).resolve().parents[2]
    return repo / "curation" if (repo / "pyproject.toml").is_file() else None


def _load(base: Path, name: str) -> list[dict]:
    p = Path(base) / f"{name}.json"
    return read_file(p)[1] if p.is_file() else []


def _blocked_sources(*source_lists: Iterable[dict]) -> set[str]:
    return {str(s.get("key")) for lst in source_lists for s in lst if s.get("redistributable") is False}


# ------------------------------------------------------------------------------------------
# Anwenden
# ------------------------------------------------------------------------------------------
def _merge_nuclides(existing: list[dict], recs: list[dict], rems: list[dict]) -> list[dict]:
    by = {str(r.get("name")): r for r in existing}
    for rem in rems:
        n = by.get(str(rem["key"][0]))
        if n is None or not rem.get("quantity"):
            continue
        vals = (n.get("values") or {}).get(rem["quantity"])
        if isinstance(vals, dict):
            vals = [vals]
        if vals is not None:
            keep = [v for v in vals if v.get("source") != rem.get("value_source")]
            if keep:
                n["values"][rem["quantity"]] = keep
            else:
                n["values"].pop(rem["quantity"], None)
    for c in recs:
        name = str(c.get("name"))
        n = by.get(name)
        if n is None:
            by[name] = copy.deepcopy(c)
            continue
        for k, v in c.items():
            if k != "values":
                n[k] = copy.deepcopy(v)
        for q, cvals in (c.get("values") or {}).items():
            vals = (n.setdefault("values", {}).get(q)) or []
            if isinstance(vals, dict):
                vals = [vals]
            srcs = {v.get("source") for v in cvals}
            vals = [v for v in vals if v.get("source") not in srcs]
            if any(v.get("preferred") for v in cvals):
                for v in vals:
                    v.pop("preferred", None)
            n["values"][q] = vals + copy.deepcopy(cvals)
    return list(by.values())


def apply(curation_dir: str | Path, db_dir: str | Path, *, files: Iterable[str] | None = None,
          distributable: bool | None = None) -> dict[str, int]:
    """Kurationsordner auf eine Datenbank anwenden (idempotent). Liefert Anzahl je Datei.

    :param files: nur diese Dateien anwenden (``None`` = alle). Das Änderungsprotokoll wird immer
        übernommen.
    :param distributable: Einträge aus nicht weitergebbaren Quellen auslassen. ``None`` = selbst
        erkennen (die Datenbank enthält bisher keine nicht weitergebbare Quelle).
    """
    cur, root = Path(curation_dir), Path(db_dir)
    counts: dict[str, int] = {}
    if not cur.is_dir():
        return counts
    db_sources = _load(root, "sources")
    if distributable is None:
        distributable = not _blocked_sources(db_sources)
    blocked = _blocked_sources(db_sources, _load(cur, "sources")) if distributable else set()
    removals = _load(cur, REMOVALS)
    wanted = None if files is None else set(files)
    for name in CURATION_FILES:
        if wanted is not None and name not in wanted:
            continue
        recs = _load(cur, name)
        if name == "sources":
            recs = [r for r in recs if str(r.get("key")) not in blocked]
        elif name == "nuclides":
            recs = [_strip_blocked_values(r, blocked) for r in recs]
            recs = [r for r in recs if r is not None]
        else:
            recs = [r for r in recs if str(r.get("source")) not in blocked]
        rems = [r for r in removals if r.get("file") == name]
        if not recs and not rems:
            continue
        target = root / f"{name}.json"
        existing = read_file(target)[1] if target.is_file() else []
        if name == "nuclides":
            merged = _merge_nuclides(existing, recs, rems)
        else:
            drop = {_kj(record_key(name, r)) for r in recs} | {_kj(r["key"]) for r in rems}
            merged = [r for r in existing if _kj(record_key(name, r)) not in drop] + copy.deepcopy(recs)
        write_file(target, name, merged)
        counts[name] = len(recs) + len(rems)
    write_file(root / "changelog.json", "changelog", _load(cur, "changelog"))
    update_manifest(root)
    return counts


def _strip_blocked_values(rec: dict, blocked: set[str]) -> dict | None:
    if not blocked:
        return rec
    if rec.get("decay_source") in blocked:
        return None
    rec = copy.deepcopy(rec)
    for q in list((rec.get("values") or {})):
        rec["values"][q] = [v for v in rec["values"][q] if v.get("source") not in blocked]
        if not rec["values"][q]:
            del rec["values"][q]
    return rec


# ------------------------------------------------------------------------------------------
# Overlay-Einträge
# ------------------------------------------------------------------------------------------
@dataclass
class OverlayEntry:
    """Ein Eintrag der Ergänzungsdatenbank, wie ihn der Editor zum Übernehmen anbietet."""
    kind: str                   # nuclide | value | decays | gamma | alpha | beta | electron
    nuclide: str
    description: str
    record: dict = field(repr=False)
    quantity: str | None = None
    added_at: str | None = None


def overlay_entries(user: UserDB, central: "NucDB") -> list[OverlayEntry]:
    """Alle Einträge des Overlays. ``central`` = zentrale Datenbank ohne Overlay."""
    out: list[OverlayEntry] = []
    for rec in user._load("nuclides"):
        name = str(rec.get("name"))
        if not central.has_nuclide(name):
            hl = ((rec.get("values") or {}).get("half_life_s") or [{}])[0]
            desc = "eigenes Nuklid" + (", stabil" if rec.get("stable") else "")
            if hl.get("value") is not None:
                desc += f", T½ = {hl.get('text') or hl['value']}" + ("" if hl.get("text") else " s")
            out.append(OverlayEntry("nuclide", name, desc, rec))
            continue
        for q, vals in (rec.get("values") or {}).items():
            for v in vals if isinstance(vals, list) else [vals]:
                text = v.get("text") or f"{v.get('value')}"
                out.append(OverlayEntry("value", name, f"{q} = {text}", v, quantity=q))
    by_parent: dict[str, list[dict]] = {}
    for rec in user._load("decay_modes"):
        by_parent.setdefault(str(rec.get("parent")), []).append(rec)
    for parent, recs in by_parent.items():
        if not central.has_nuclide(parent):
            continue                      # Zerfallswege eigener Nuklide gehören zum Nuklid-Eintrag
        desc = "eigene Zerfallswege: " + ", ".join(
            f"→ {r.get('daughter')} " + ("?" if r.get("branching") is None else f"{float(r['branching']):.4g}")
            for r in recs)
        out.append(OverlayEntry("decays", parent, desc, {"parent": parent, "modes": recs}))
    for kind, fname in schema.EMISSION_FILES.items():
        for rec in user._load(fname):
            e = rec.get("energy_kev")
            it = rec.get("intensity")
            desc = f"{kind} {e:g} keV" + (f", I = {it:.4g}" if isinstance(it, (int, float)) else ", I unbekannt")
            if rec.get("note"):
                desc += f" – {rec['note']}"
            out.append(OverlayEntry(kind, str(rec.get("nuclide")), desc, rec, added_at=rec.get("added_at")))
    return out


def remove_overlay_entry(user: UserDB, entry: OverlayEntry, *, comment: str | None = None) -> None:
    """Eintrag aus der Ergänzungsdatenbank löschen (eigenes Nuklid, eigener Wert oder eigene Linie)."""
    if entry.kind == "nuclide":
        user.remove_nuclide(entry.nuclide, comment=comment)
    elif entry.kind == "decays":
        user.remove_decays(entry.nuclide, comment=comment)
    elif entry.kind in schema.EMISSION_FILES:
        user.remove_emission(entry.kind, entry.nuclide, float(entry.record["energy_kev"]), comment=comment)
    elif entry.kind == "value":
        with user._locked():
            out = []
            for r in user._load("nuclides"):
                if r.get("name") == entry.nuclide:
                    vals = (r.get("values") or {}).get(entry.quantity) or []
                    vals = [v for v in (vals if isinstance(vals, list) else [vals]) if v != entry.record]
                    if vals:
                        r["values"][entry.quantity] = vals
                    else:
                        r.get("values", {}).pop(entry.quantity, None)
                    if not r.get("values") and set(r) <= {"name", "z", "a", "isomer", "values"}:
                        continue
                out.append(r)
            user._save("nuclides", out)
            user._log([{"changed_at": _now(), "file": "nuclides", "record": entry.nuclide, "field": entry.quantity,
                        "old": entry.record.get("value"), "new": None, "comment": comment}])
        user._db.reload()
    else:
        raise ValueError(f"Unbekannte Art {entry.kind!r}")


# ------------------------------------------------------------------------------------------
# Kuration
# ------------------------------------------------------------------------------------------
class Curation:
    """Schreibzugriff auf die zentrale Datenbank über den Kurationsordner.

    :param path: Kurationsordner (wird bei Bedarf angelegt).
    :param db_dir: Datenbank, in die sofort übernommen wird.
    :param distributable: ``None`` = selbst erkennen (siehe :func:`apply`).
    """

    def __init__(self, path: str | Path, db_dir: str | Path, *, distributable: bool | None = None):
        self.location = Path(path)
        self.db_dir = Path(db_dir)
        if distributable is None:
            distributable = (self.db_dir.resolve() == PACKAGE_DATA.resolve()
                             or not _blocked_sources(_load(self.db_dir, "sources")))
        self.distributable = distributable
        self._central: "NucDB | None" = None

    # --- Hilfen ---------------------------------------------------------------------------
    @property
    def central(self) -> "NucDB":
        """Zentrale Datenbank ohne Overlay (zum Prüfen)."""
        if self._central is None:
            from .db import NucDB
            self._central = NucDB(self.db_dir, overlay=False)
        return self._central

    def _save(self, name: str, records: Iterable[dict]) -> None:
        write_file(self.location / f"{name}.json", name, records)

    def _commit(self, files: Sequence[str], log: Sequence[dict]) -> None:
        entries = _load(self.location, "changelog")
        entries.extend(log)
        self._save("changelog", entries)
        apply(self.location, self.db_dir, files=files, distributable=self.distributable)
        self.central.reload()

    def sources(self) -> dict[str, dict]:
        """Alle Quellen, die für Einträge zur Wahl stehen (zentral + Kurationsordner)."""
        out = {str(s.get("key")): s for s in _load(self.db_dir, "sources")}
        out.update({str(s.get("key")): s for s in _load(self.location, "sources")})
        out.pop(USER_SOURCE, None)
        return out

    def _check_source(self, key: str | None) -> str:
        if not key or not str(key).strip():
            raise ValueError("Bitte eine Quelle angeben (Quellenpflicht für die zentrale Datenbank)")
        key = str(key).strip()
        if key == USER_SOURCE:
            raise ValueError("Die Quelle 'user' gehört in die Ergänzungsdatenbank, nicht in die zentrale. "
                             "Bitte die tatsächliche Quelle angeben bzw. anlegen.")
        src = self.sources().get(key)
        if src is None:
            raise ValueError(f"Unbekannte Quelle {key!r}. Bitte zuerst anlegen (add_source).")
        if self.distributable and src.get("redistributable") is False:
            raise ValueError(f"Quelle {key} ist nicht weitergebbar und darf nicht in diese (verteilte) "
                             "Datenbank. Für eigene Zwecke eine lokale Datenbank verwenden.")
        return key

    @staticmethod
    def _need_comment(comment: str | None) -> str:
        if not comment or not comment.strip():
            raise ValueError("Bitte eine Begründung angeben")
        return comment.strip()

    @staticmethod
    def _log(file: str, record: str, field: str | None, old: Any, new: Any, source: str | None,
             comment: str | None) -> dict:
        text = " – ".join(x for x in (f"Quelle {source}" if source else None, comment) if x)
        return {"changed_at": _now(), "file": file, "record": record, "field": field, "old": old, "new": new,
                "comment": text or None}

    def _canon_central(self, nuclide: str) -> str:
        canon = names.normalize(nuclide)
        if not self.central.has_nuclide(canon):
            raise ValueError(f"{canon} steht nicht in der zentralen Datenbank. Zuerst mit add_nuclide anlegen.")
        return canon

    # --- Quellen ---------------------------------------------------------------------------
    def add_source(self, key: str, *, title: str, citation: str | None = None, redistributable: bool = True,
                   comment: str | None = None, **fields: Any) -> dict:
        """Neue Quelle anlegen (oder eine kuratierte ändern). Weitere Felder nach Spezifikation 4.2,
        z. B. ``url``, ``doi``, ``year``, ``authors``, ``publisher``, ``license``, ``notes``."""
        key = (key or "").strip()
        if not _SOURCE_KEY_RE.match(key):
            raise ValueError("Kurzname der Quelle: Buchstaben, Ziffern, . _ + - (z. B. 'DDEP-2024')")
        if key == USER_SOURCE:
            raise ValueError("Der Kurzname 'user' ist für die Ergänzungsdatenbank reserviert")
        if any(str(s.get("key")) == key for s in _load(self.db_dir, "sources")) and \
                not any(str(s.get("key")) == key for s in _load(self.location, "sources")):
            raise ValueError(f"Quelle {key} gibt es schon (aus einem Import)")
        if not (title or "").strip():
            raise ValueError("Bitte einen Titel angeben")
        rec = {"key": key, "title": title.strip(), "citation": (citation or "").strip() or None,
               "redistributable": bool(redistributable), **{k: v for k, v in fields.items() if v not in ("", None)}}
        self.location.mkdir(parents=True, exist_ok=True)
        srcs = [s for s in _load(self.location, "sources") if str(s.get("key")) != key] + [rec]
        self._save("sources", srcs)
        self._commit(["sources"], [self._log("sources", key, None, None, "angelegt", None, comment)])
        return rec

    # --- Werte -------------------------------------------------------------------------------
    def add_value(self, nuclide: str, quantity: str, value: Any, *, source: str, unc: Any = None,
                  preferred: bool = True, comment: str | None = None) -> dict:
        """Wert einer Größe mit Quelle setzen. Ersetzt den Wert derselben Quelle."""
        canon = self._canon_central(nuclide)
        source = self._check_source(source)
        if quantity not in self.central.quantities():
            raise ValueError(f"Unbekannte Größe {quantity!r}")
        v, u, text = UserDB._parse_value(quantity, value, unc)
        old = next((x.value for x in self.central.nuclide(canon).values(quantity) if x.source == source), None)
        nid = names.parse(canon)
        nucs = _load(self.location, "nuclides")
        rec = next((r for r in nucs if r.get("name") == canon), None)
        if rec is None:
            rec = {"name": canon, "z": nid.z, "a": nid.a, "isomer": nid.isomer}
            nucs.append(rec)
        vals = [x for x in rec.setdefault("values", {}).get(quantity, []) if x.get("source") != source]
        if preferred:
            for x in vals:
                x.pop("preferred", None)
        vals.append({"value": v, "unc": u, "text": text, "source": source, "preferred": preferred or None})
        rec["values"][quantity] = vals
        removals = [r for r in _load(self.location, REMOVALS)
                    if not (r.get("file") == "nuclides" and r["key"] == [canon] and r.get("quantity") == quantity
                            and r.get("value_source") == source)]
        self.location.mkdir(parents=True, exist_ok=True)
        self._save("nuclides", nucs)
        self._save(REMOVALS, removals)
        self._commit(["nuclides"], [self._log("nuclides", canon, quantity, old, v, source, comment)])
        return vals[-1]

    def remove_value(self, nuclide: str, quantity: str, source: str, *, comment: str) -> None:
        """Wert einer Quelle aus der zentralen Datenbank entfernen (Begründung Pflicht)."""
        canon = self._canon_central(nuclide)
        comment = self._need_comment(comment)
        old = next((x.value for x in self.central.nuclide(canon).values(quantity) if x.source == source), None)
        if old is None:
            raise ValueError(f"{canon} hat keinen Wert {quantity} aus Quelle {source}")
        nucs = _load(self.location, "nuclides")
        for r in nucs:
            if r.get("name") == canon and quantity in (r.get("values") or {}):
                r["values"][quantity] = [x for x in r["values"][quantity] if x.get("source") != source]
                if not r["values"][quantity]:
                    del r["values"][quantity]
        removals = _load(self.location, REMOVALS)
        removals.append({"file": "nuclides", "key": [canon], "quantity": quantity, "value_source": source,
                         "comment": comment, "changed_at": _now()})
        self._save("nuclides", nucs)
        self._save(REMOVALS, removals)
        self._commit(["nuclides"], [self._log("nuclides", canon, quantity, old, None, source, comment)])

    # --- Nuklide und Zerfallswege -----------------------------------------------------------
    def add_nuclide(self, name: str, *, source: str, half_life: float | str | None = None,
                    half_life_unc: float | str | None = None, stable: bool = False, decays: Sequence[tuple] = (),
                    note: str | None = None, comment: str | None = None) -> str:
        """Neues Nuklid in der zentralen Datenbank anlegen (oder ein kuratiertes ersetzen)."""
        canon = names.normalize(name)
        nid = names.parse(canon)
        source = self._check_source(source)
        curated = {str(r.get("name")) for r in _load(self.location, "nuclides") if r.get("decay_source") and "z" in r}
        if self.central.has_nuclide(canon) and canon not in curated:
            raise ValueError(f"{canon} steht schon in der zentralen Datenbank. Für Korrekturen add_value() "
                             "bzw. add_decay_mode() verwenden.")
        if stable and decays:
            raise ValueError("Ein stabiles Nuklid hat keine Zerfallswege")
        modes = []
        for d in decays:
            daughter, frac, *rest = d
            dcanon = names.normalize(daughter)
            if dcanon != canon and not self.central.has_nuclide(dcanon):
                raise ValueError(f"Tochter {dcanon} steht nicht in der zentralen Datenbank")
            modes.append({"parent": canon, "daughter": dcanon, "branching": float(frac), "source": source,
                          "mode": (str(rest[0]) if rest and rest[0] else None)})
        rec: dict[str, Any] = {"name": canon, "z": nid.z, "a": nid.a, "isomer": nid.isomer, "stable": bool(stable),
                               "decay_source": source, "note": note or None, "values": {}}
        if half_life is not None:
            v, u, text = UserDB._parse_value("half_life_s", half_life, half_life_unc)
            rec["values"]["half_life_s"] = [{"value": v, "unc": u, "text": text, "source": source,
                                             "preferred": True}]
        self.location.mkdir(parents=True, exist_ok=True)
        self._save("nuclides", [r for r in _load(self.location, "nuclides") if r.get("name") != canon] + [rec])
        self._save("decay_modes", [r for r in _load(self.location, "decay_modes")
                                   if not (r.get("parent") == canon and r.get("source") == source)] + modes)
        self._commit(["nuclides", "decay_modes"],
                     [self._log("nuclides", canon, None, None, "angelegt", source, comment)])
        return canon

    def add_decay_mode(self, parent: str, daughter: str, branching: float | None, *, source: str,
                       mode: str | None = None, branching_unc: float | None = None,
                       comment: str | None = None) -> dict:
        """Zerfallsweg setzen (ersetzt denselben Weg derselben Quelle)."""
        p = self._canon_central(parent)
        d = self._canon_central(daughter)
        source = self._check_source(source)
        if branching is not None and not 0 <= float(branching) <= 1:
            raise ValueError("Verzweigung als Bruchteil 0…1 angeben")
        rec = {"parent": p, "daughter": d, "mode": mode or None, "source": source,
               "branching": None if branching is None else float(branching),
               "branching_unc": None if branching_unc is None else float(branching_unc)}
        key = _kj(record_key("decay_modes", rec))
        self.location.mkdir(parents=True, exist_ok=True)
        self._save("decay_modes", [r for r in _load(self.location, "decay_modes")
                                   if _kj(record_key("decay_modes", r)) != key] + [rec])
        self._save(REMOVALS, [r for r in _load(self.location, REMOVALS)
                              if not (r.get("file") == "decay_modes" and _kj(r["key"]) == key)])
        self._commit(["decay_modes"], [self._log("decay_modes", f"{p} → {d}", "branching", None,
                                                 rec["branching"], source, comment)])
        return rec

    def set_decays(self, parent: str, decays: Sequence[tuple], *, source: str,
                   comment: str | None = None) -> list[dict]:
        """Alle Zerfallswege eines Nuklids aus einer Quelle setzen und diese Quelle bevorzugen.

        Schreibt die Zweige (``(Tochter, Anteil[, Art[, Unsicherheit]])``) unter ``source`` und setzt
        ``decay_source`` des Nuklids auf diese Quelle; die Zweige anderer Quellen bleiben erhalten,
        werden aber nicht mehr gewählt (Spezifikation 4.5).
        """
        p = self._canon_central(parent)
        source = self._check_source(source)
        if not decays:
            raise ValueError("Keine Zerfallswege angegeben")
        modes = []
        for d in decays:
            daughter, frac, *rest = d
            dc = self._canon_central(daughter)
            if frac is not None and not 0 <= float(frac) <= 1:
                raise ValueError("Verzweigung als Bruchteil 0…1 angeben")
            modes.append({"parent": p, "daughter": dc, "mode": (str(rest[0]) if rest and rest[0] else None),
                          "branching": None if frac is None else float(frac), "source": source,
                          "branching_unc": (float(rest[1]) if len(rest) > 1 and rest[1] is not None else None)})
        keys = {_kj(record_key("decay_modes", m)) for m in modes}
        self.location.mkdir(parents=True, exist_ok=True)
        self._save("decay_modes", [r for r in _load(self.location, "decay_modes")
                                   if not (r.get("parent") == p and r.get("source") == source)] + modes)
        self._save(REMOVALS, [r for r in _load(self.location, REMOVALS)
                              if not (r.get("file") == "decay_modes" and _kj(r["key"]) in keys)])
        nucs = _load(self.location, "nuclides")
        rec = next((r for r in nucs if r.get("name") == p), None)
        if rec is None:
            nucs.append({"name": p, "decay_source": source})
        else:
            rec["decay_source"] = source
        self._save("nuclides", nucs)
        desc = ", ".join(f"{m['daughter']} " + ("?" if m["branching"] is None else f"{m['branching']:g}")
                         for m in modes)
        self._commit(["nuclides", "decay_modes"],
                     [self._log("decay_modes", p, "decay_source", None, desc, source, comment)])
        return modes

    def remove_decay_mode(self, parent: str, daughter: str | None, mode: str | None, source: str, *,
                          comment: str) -> None:
        """Zerfallsweg einer Quelle aus der zentralen Datenbank entfernen (Begründung Pflicht)."""
        p = names.normalize(parent)
        comment = self._need_comment(comment)
        key = _kj(record_key("decay_modes", {"parent": p, "daughter": daughter, "mode": mode, "source": source}))
        if not any(_kj(record_key("decay_modes", r)) == key for r in _load(self.db_dir, "decay_modes")):
            raise ValueError(f"Kein Zerfallsweg {p} → {daughter} ({mode}) aus Quelle {source}")
        self._save("decay_modes", [r for r in _load(self.location, "decay_modes")
                                   if _kj(record_key("decay_modes", r)) != key])
        removals = _load(self.location, REMOVALS)
        removals.append({"file": "decay_modes", "key": json.loads(key), "comment": comment, "changed_at": _now()})
        self._save(REMOVALS, removals)
        self._commit(["decay_modes"], [self._log("decay_modes", f"{p} → {daughter}", None, "vorhanden", None,
                                                 source, comment)])

    # --- Linien ------------------------------------------------------------------------------
    def add_emission(self, kind: str, nuclide: str, energy: float | str, *, source: str,
                     intensity: float | str | None = None, energy_unc: float | str | None = None,
                     intensity_unc: float | str | None = None, note: str | None = None,
                     comment: str | None = None, **fields: Any) -> dict:
        """Linie bzw. Zweig mit Quelle hinzufügen; ersetzt dieselbe Linie (±1 eV) derselben Quelle."""
        if kind not in schema.EMISSION_FILES:
            raise ValueError(f"Unbekannte Strahlungsart {kind!r}")
        canon = self._canon_central(nuclide)
        source = self._check_source(source)
        e, eu, et = UserDB._energy(energy, energy_unc)
        if not e > 0:
            raise ValueError(f"Energie muss positiv sein, nicht {e}")
        it, itu = UserDB._fraction(intensity, intensity_unc)
        if it is not None and not 0 <= it <= 10:
            raise ValueError(f"Intensität {it} ist kein Bruchteil pro Zerfall (z. B. 0.455 oder '45,5 %')")
        if kind == "gamma":
            fields.setdefault("radiation", "G")
        if kind == "beta" and fields.get("type") not in ("B-", "B+"):
            raise ValueError("Beta-Zweige brauchen type='B-' oder type='B+'")
        if kind == "electron" and not fields.get("type"):
            raise ValueError("Elektronen brauchen einen type (z. B. 'CE K' oder 'Auger K')")
        rec = {"nuclide": canon, "energy_kev": e, "energy_kev_unc": eu, "energy_kev_text": et, "intensity": it,
               "intensity_unc": itu, "source": source, "note": note or None,
               **{k: v for k, v in fields.items() if v not in ("", None)}}
        fname = schema.EMISSION_FILES[kind]
        key = _kj(record_key(fname, rec))
        self.location.mkdir(parents=True, exist_ok=True)
        self._save(fname, [r for r in _load(self.location, fname) if _kj(record_key(fname, r)) != key] + [rec])
        self._save(REMOVALS, [r for r in _load(self.location, REMOVALS)
                              if not (r.get("file") == fname and _kj(r["key"]) == key)])
        self._commit([fname], [self._log(fname, f"{canon} {e:g} keV", None, None, "angelegt", source, comment)])
        return rec

    def remove_emission(self, kind: str, nuclide: str, energy_kev: float, source: str, *, comment: str) -> None:
        """Linie einer Quelle aus der zentralen Datenbank entfernen (Begründung Pflicht)."""
        fname = schema.EMISSION_FILES[kind]
        canon = names.normalize(nuclide)
        comment = self._need_comment(comment)
        key = _kj(record_key(fname, {"nuclide": canon, "source": source, "energy_kev": energy_kev}))
        present = [r for r in _load(self.db_dir, fname) if _kj(record_key(fname, r)) == key]
        if not present:
            raise ValueError(f"Keine {kind}-Linie von {canon} bei {energy_kev:g} keV aus Quelle {source}")
        self._save(fname, [r for r in _load(self.location, fname) if _kj(record_key(fname, r)) != key])
        removals = _load(self.location, REMOVALS)
        removals.append({"file": fname, "key": json.loads(key), "comment": comment, "changed_at": _now()})
        self._save(REMOVALS, removals)
        self._commit([fname], [self._log(fname, f"{canon} {energy_kev:g} keV", None, "vorhanden", None, source,
                                         comment)])

    # --- Übernahme aus dem Overlay ----------------------------------------------------------
    def adopt(self, user: UserDB, entry: OverlayEntry, *, source: str, comment: str | None = None,
              remove_from_overlay: bool = True) -> None:
        """Overlay-Eintrag mit echter Quelle in die zentrale Datenbank übernehmen.

        Bei einem eigenen Nuklid kommen seine Werte, Zerfallswege und Linien aus dem Overlay mit.
        Danach wird der Eintrag (standardmäßig) aus dem Overlay entfernt.
        """
        source = self._check_source(source)
        comment = comment or "aus Ergänzungsdatenbank übernommen"
        rec = entry.record
        if entry.kind == "value":
            self.add_value(entry.nuclide, str(entry.quantity), rec.get("text") or rec.get("value"),
                           unc=None if rec.get("text") else rec.get("unc"), source=source,
                           preferred=bool(rec.get("preferred", True)), comment=comment)
            if remove_from_overlay:
                remove_overlay_entry(user, entry, comment=f"in die zentrale Datenbank übernommen (Quelle {source})")
        elif entry.kind in schema.EMISSION_FILES:
            fields = {k: v for k, v in rec.items() if k not in (
                "nuclide", "energy_kev", "energy_kev_unc", "energy_kev_text", "intensity", "intensity_unc",
                "source", "note", "added_at")}
            self.add_emission(entry.kind, entry.nuclide, rec["energy_kev"], source=source,
                              intensity=rec.get("intensity"), energy_unc=rec.get("energy_kev_unc"),
                              intensity_unc=rec.get("intensity_unc"), note=rec.get("note"), comment=comment,
                              **fields)
            if remove_from_overlay:
                self._overlay_edit(user, schema.EMISSION_FILES[entry.kind], lambda r: r != rec,
                                   f"{entry.nuclide} {rec['energy_kev']:g} keV", source)
        elif entry.kind == "nuclide":
            self._adopt_nuclide(user, entry, source, comment, remove_from_overlay)
        elif entry.kind == "decays":
            self.set_decays(entry.nuclide, [(m.get("daughter"), m.get("branching"), m.get("mode"),
                                             m.get("branching_unc")) for m in rec["modes"]],
                            source=source, comment=comment)
            if remove_from_overlay:
                self._overlay_edit(user, "decay_modes", lambda r: r.get("parent") != entry.nuclide,
                                   entry.nuclide, source)
        else:
            raise ValueError(f"Unbekannte Art {entry.kind!r}")
        user._db.reload()

    def _adopt_nuclide(self, user: UserDB, entry: OverlayEntry, source: str, comment: str,
                       remove_from_overlay: bool) -> None:
        name = entry.nuclide
        rec = entry.record
        modes = [m for m in user._load("decay_modes") if m.get("parent") == name]
        for m in modes:
            d = str(m.get("daughter"))
            if d != name and not self.central.has_nuclide(d):
                raise ValueError(f"Tochter {d} steht nur in der Ergänzungsdatenbank. Bitte zuerst {d} übernehmen.")
        hl = ((rec.get("values") or {}).get("half_life_s") or [None])[0]
        self.add_nuclide(name, source=source, stable=bool(rec.get("stable")), note=rec.get("note"),
                         half_life=None if hl is None else (hl.get("text") or hl.get("value")),
                         half_life_unc=None if hl is None or hl.get("text") else hl.get("unc"),
                         decays=[(m["daughter"], m.get("branching") if m.get("branching") is not None else 0.0,
                                  m.get("mode")) for m in modes], comment=comment)
        for q, vals in (rec.get("values") or {}).items():
            if q == "half_life_s":
                continue
            for v in vals if isinstance(vals, list) else [vals]:
                self.add_value(name, q, v.get("value"), unc=v.get("unc"), source=source, comment=comment)
        lines = [(k, r) for k, f in schema.EMISSION_FILES.items() for r in user._load(f) if r.get("nuclide") == name]
        for kind, r in lines:
            self.adopt(user, OverlayEntry(kind, name, "", r), source=source, comment=comment,
                       remove_from_overlay=remove_from_overlay)
        if remove_from_overlay:
            def edit():
                user._save("nuclides", [r for r in user._load("nuclides") if r.get("name") != name])
                user._save("decay_modes", [r for r in user._load("decay_modes") if r.get("parent") != name])
            self._overlay_tx(user, edit, "nuclides", name, source)

    # --- Overlay ändern (unter Sperre) -------------------------------------------------------
    @staticmethod
    def _overlay_tx(user: UserDB, edit, file: str, record: str, source: str) -> None:
        with user._locked():
            edit()
            user._log([{"changed_at": _now(), "file": file, "record": record, "field": None, "old": "vorhanden",
                        "new": None, "comment": f"in die zentrale Datenbank übernommen (Quelle {source})"}])
        user._db.reload()

    def _overlay_edit(self, user: UserDB, file: str, keep, record: str, source: str) -> None:
        self._overlay_tx(user, lambda: user._save(file, [r for r in user._load(file) if keep(r)]),
                         file, record, source)

    # --- Lesen -------------------------------------------------------------------------------
    def changelog(self) -> list[dict]:
        return _load(self.location, "changelog")

    def removals(self) -> list[dict]:
        return _load(self.location, REMOVALS)
