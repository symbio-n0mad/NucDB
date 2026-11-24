"""Schreibzugriff auf die Ergänzungsdatenbank (Overlay) der Nutzer (Spezifikation 8).

Die zentrale Datenbank wird nie verändert. Eigene Nuklide, Werte und Zerfallswege landen im
Overlay-Ordner und sind für alle Tools sichtbar, die die Lese-API verwenden.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import functools
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Sequence

from . import names, schema, units
from .fileformat import read_file, write_file, atomic_write_text
from .locate import MANIFEST

if TYPE_CHECKING:  # pragma: no cover
    from .db import NucDB

USER_SOURCE = "user"

_USER_SOURCE_RECORD = {
    "key": USER_SOURCE,
    "title": "Eigene Einträge (Ergänzungsdatenbank)",
    "citation": "Eigener Eintrag des Nutzers",
    "license": "—",
    "redistributable": False,
    "notes": "Wird vom Overlay automatisch angelegt.",
}

# Größen, deren Eingabe als Text mit Einheit gelesen wird: quantity -> Größenart für units
_QUANTITY_INPUT_KIND = {"half_life_s": "half_life"}


#: Strahlungsarten, die ins Overlay geschrieben werden können → Datei
_EMISSION_FILES = schema.EMISSION_FILES
LOCK_NAME = ".lock"
LOCK_TIMEOUT_S = 10.0
LOCK_STALE_S = 60.0


class OverlayLockedError(RuntimeError):
    """Ein anderes Programm schreibt gerade in die Ergänzungsdatenbank."""


def _writes(method):
    """Schreibende Methode: unter Sperre ausführen, danach Zwischenspeicher verwerfen."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._locked():
            result = method(self, *args, **kwargs)
        self._db.reload()
        return result
    return wrapper


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class UserDB:
    """Ergänzungsdatenbank; erreichbar als ``db.user``."""

    def __init__(self, db: "NucDB", path: Path):
        self._db = db
        self.location = Path(path)

    # --- Hilfen ---------------------------------------------------------------------------
    @contextlib.contextmanager
    def _locked(self):
        """Sperrdatei im Overlay-Ordner, damit zwei Tools nicht gleichzeitig schreiben.

        Wartet bis ``LOCK_TIMEOUT_S``; eine Sperre, die älter als ``LOCK_STALE_S`` ist (abgestürztes
        Programm), wird übernommen.
        """
        self.location.mkdir(parents=True, exist_ok=True)
        lock = self.location / LOCK_NAME
        deadline = time.monotonic() + LOCK_TIMEOUT_S
        while True:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {_now()}\n".encode())
                os.close(fd)
                break
            except FileExistsError:
                try:
                    if time.time() - lock.stat().st_mtime > LOCK_STALE_S:
                        lock.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if time.monotonic() > deadline:
                    raise OverlayLockedError(
                        f"Die Ergänzungsdatenbank {self.location} wird gerade von einem anderen Programm "
                        "geändert. Bitte gleich noch einmal versuchen.") from None
                time.sleep(0.05)
        try:
            yield
        finally:
            lock.unlink(missing_ok=True)

    def _load(self, name: str) -> list[dict]:
        p = self.location / f"{name}.json"
        return read_file(p)[1] if p.is_file() else []

    def _save(self, name: str, records: Iterable[dict]) -> None:
        write_file(self.location / f"{name}.json", name, records)

    def _ensure_base(self) -> None:
        self.location.mkdir(parents=True, exist_ok=True)
        if not (self.location / MANIFEST).is_file():
            import json
            atomic_write_text(self.location / MANIFEST, json.dumps(
                {"format": "nucdb/manifest", "schema_version": schema.SCHEMA_VERSION, "overlay": True,
                 "created_at": _now()}, ensure_ascii=False, indent=1) + "\n")
        srcs = self._load("sources")
        if not any(s.get("key") == USER_SOURCE for s in srcs):
            srcs.append(dict(_USER_SOURCE_RECORD))
            self._save("sources", srcs)

    def _log(self, entries: Sequence[dict]) -> None:
        log = self._load("changelog")
        log.extend(entries)
        self._save("changelog", log)

    @staticmethod
    def _parse_value(quantity: str, value: Any, unc: Any) -> tuple[Any, float | None, str | None]:
        """Zahl oder Text mit Einheit → (Wert in Basiseinheit, Unsicherheit, Originaltext)."""
        if isinstance(value, str):
            kind = _QUANTITY_INPUT_KIND.get(quantity)
            if kind is None:
                v, u = units.parse_number(value)
                return v, (u if unc is None else float(unc)), value
            q = units.parse_quantity(value, kind)
            u2 = q.unc
            if unc is not None:
                u2 = units.parse_quantity(unc, kind).value if isinstance(unc, str) else float(unc)
            return q.value, u2, value
        return value, (None if unc is None else float(unc)), None

    # --- Lesen ----------------------------------------------------------------------------
    def nuclide_names(self) -> list[str]:
        return [str(r.get("name")) for r in self._load("nuclides")]

    # --- Schreiben ------------------------------------------------------------------------
    @_writes
    def add_nuclide(self, name: str, *, half_life: float | str | None = None,
                    half_life_unc: float | str | None = None, stable: bool = False,
                    decays: Sequence[tuple] = (), note: str | None = None,
                    comment: str | None = None) -> str:
        """Eigenes Nuklid anlegen (oder ein eigenes ersetzen).

        :param half_life: T½ in Sekunden oder als Text mit Einheit, z. B. ``"65.94 h"``.
            Auch eine Zerfallskonstante ist erlaubt, z. B. ``"2.92e-6 1/s"``.
        :param decays: Zerfallswege als ``(Tochter, Anteil)`` oder ``(Tochter, Anteil, Art)``.
            Jede Tochter muss bereits in der Datenbank (zentral oder Overlay) stehen. Stabile
            Endprodukte also vorher anlegen bzw. ``stable=True`` setzen.
        :returns: kanonischer Name.
        """
        canon = names.normalize(name)
        nid = names.parse(canon)
        if self._db.has_nuclide(canon) and canon not in self.nuclide_names():
            raise ValueError(f"{canon} steht schon in der zentralen Datenbank. Für eigene Werte "
                             "add_value() verwenden.")
        if stable and decays:
            raise ValueError("Ein stabiles Nuklid hat keine Zerfallswege")
        dec_recs = []
        for d in decays:
            daughter, frac, *rest = d
            dcanon = names.normalize(daughter)
            if not self._db.has_nuclide(dcanon) and dcanon != canon:
                raise ValueError(f"Tochter {dcanon} ist unbekannt. Bitte zuerst anlegen "
                                 "(stabile Endprodukte mit stable=True).")
            rec = {"parent": canon, "daughter": dcanon, "branching": float(frac), "source": USER_SOURCE}
            if rest and rest[0]:
                rec["mode"] = str(rest[0])
            dec_recs.append(rec)

        rec: dict[str, Any] = {"name": canon, "z": nid.z, "a": nid.a, "isomer": nid.isomer,
                               "stable": bool(stable), "decay_source": USER_SOURCE, "values": {}}
        if note:
            rec["note"] = note
        if half_life is not None:
            v, u, text = self._parse_value("half_life_s", half_life, half_life_unc)
            rec["values"]["half_life_s"] = [{"value": v, "unc": u, "text": text, "source": USER_SOURCE,
                                             "preferred": True}]
        self._ensure_base()
        nucs = [r for r in self._load("nuclides") if names.sort_key(str(r.get("name"))) != names.sort_key(canon)]
        nucs.append(rec)
        modes = [r for r in self._load("decay_modes") if r.get("parent") != canon]
        modes.extend(dec_recs)
        self._save("nuclides", nucs)
        self._save("decay_modes", modes)
        self._log([{"changed_at": _now(), "file": "nuclides", "record": canon, "field": None,
                    "old": None, "new": "angelegt", "comment": comment}])
        return canon

    @_writes
    def add_value(self, name: str, quantity: str, value: Any, *, unc: Any = None, preferred: bool = True,
                  source: str = USER_SOURCE, comment: str | None = None) -> None:
        """Eigenen Wert einer Größe zu einem (zentralen oder eigenen) Nuklid hinzufügen.

        Mit ``preferred=True`` übersteuert er den zentralen Wert in allen Tools.
        """
        canon = names.normalize(name)
        if not self._db.has_nuclide(canon):
            raise ValueError(f"Unbekanntes Nuklid {canon}")
        if quantity not in self._db.quantities():
            raise ValueError(f"Unbekannte Größe {quantity!r}; bekannt: {', '.join(sorted(self._db.quantities()))}")
        v, u, text = self._parse_value(quantity, value, unc)
        self._ensure_base()
        nucs = self._load("nuclides")
        rec = next((r for r in nucs if r.get("name") == canon), None)
        if rec is None:
            nid = names.parse(canon)
            rec = {"name": canon, "z": nid.z, "a": nid.a, "isomer": nid.isomer, "values": {}}
            nucs.append(rec)
        vals = rec.setdefault("values", {}).setdefault(quantity, [])
        if preferred:
            for x in vals:
                x.pop("preferred", None)
        vals.append({"value": v, "unc": u, "text": text, "source": source, "preferred": preferred or None})
        self._save("nuclides", nucs)
        self._log([{"changed_at": _now(), "file": "nuclides", "record": canon, "field": quantity,
                    "old": None, "new": v, "comment": comment}])

    @_writes
    def remove_nuclide(self, name: str, *, comment: str | None = None) -> None:
        """Eigenen Eintrag eines Nuklids samt eigener Zerfallswege entfernen."""
        canon = names.normalize(name)
        nucs = self._load("nuclides")
        keep = [r for r in nucs if r.get("name") != canon]
        if len(keep) == len(nucs):
            raise ValueError(f"{canon} hat keinen eigenen Eintrag in der Ergänzungsdatenbank")
        users = [r for r in self._load("decay_modes") if r.get("daughter") == canon]
        if users:
            raise ValueError(f"{canon} ist Tochter von {', '.join(sorted({r['parent'] for r in users}))}; "
                             "diese Einträge zuerst ändern")
        self._save("nuclides", keep)
        self._save("decay_modes", [r for r in self._load("decay_modes") if r.get("parent") != canon])
        self._log([{"changed_at": _now(), "file": "nuclides", "record": canon, "field": None,
                    "old": "vorhanden", "new": None, "comment": comment}])

    # --- Eigene Linien ----------------------------------------------------------------------
    @staticmethod
    def _energy(value: Any, unc: Any) -> tuple[float, float | None, str | None]:
        if isinstance(value, str):
            q = units.parse_quantity(value, "energy", default_unit="keV")
            u = q.unc if unc is None else (units.parse_quantity(unc, "energy", default_unit="keV").value
                                           if isinstance(unc, str) else float(unc))
            return q.value, u, value
        return float(value), (None if unc is None else float(unc)), None

    @staticmethod
    def _fraction(value: Any, unc: Any) -> tuple[float | None, float | None]:
        if value is None:
            return None, None
        if isinstance(value, str):
            q = units.parse_quantity(value, "fraction")
            u = q.unc if unc is None else (units.parse_quantity(unc, "fraction").value
                                           if isinstance(unc, str) else float(unc))
            return q.value, u
        return float(value), (None if unc is None else float(unc))

    @_writes
    def add_emission(self, kind: str, nuclide: str, energy: float | str, *, intensity: float | str | None = None,
                     energy_unc: float | str | None = None, intensity_unc: float | str | None = None,
                     note: str | None = None, comment: str | None = None, **fields: Any) -> dict:
        """Eigene Linie (bzw. eigenen Zweig) zu einem Nuklid hinzufügen.

        :param kind: ``gamma``, ``alpha``, ``beta`` oder ``electron``.
        :param energy: Energie in keV oder als Text, z. B. ``"609.3(2) keV"`` oder ``"1,7645 MeV"``.
            Bei Beta-Zweigen die Endpunktenergie.
        :param intensity: pro Zerfall als Bruchteil (``0.455``) oder Text (``"45,5 %"``); ``None`` =
            unbekannt.
        :param fields: weitere Felder nach Spezifikation 4.7, z. B. ``radiation="G"``, ``type="B-"``,
            ``mean_energy_kev=...``.
        Gibt es schon eine eigene Linie dieser Art bei derselben Energie (±1 eV), wird sie ersetzt.
        Die Linie erscheint sofort in ``gammas()``, ``find_gammas()`` usw. aller Tools.
        :returns: den geschriebenen Datensatz.
        """
        if kind not in _EMISSION_FILES:
            raise ValueError(f"Unbekannte Strahlungsart {kind!r}; erlaubt: {', '.join(_EMISSION_FILES)}")
        canon = names.normalize(nuclide)
        if not self._db.has_nuclide(canon):
            raise ValueError(f"Unbekanntes Nuklid {canon}. Eigene Nuklide zuerst mit add_nuclide() anlegen.")
        e, eu, et = self._energy(energy, energy_unc)
        if not e > 0:
            raise ValueError(f"Energie muss positiv sein, nicht {e}")
        it, itu = self._fraction(intensity, intensity_unc)
        if it is not None and not 0 <= it <= 10:
            raise ValueError(f"Intensität {it} ist kein Bruchteil pro Zerfall (z. B. 0.455 oder '45,5 %')")
        if kind == "gamma":
            fields.setdefault("radiation", "G")
        if kind == "beta" and fields.get("type") not in ("B-", "B+"):
            raise ValueError("Beta-Zweige brauchen type='B-' oder type='B+'")
        rec = {"nuclide": canon, "energy_kev": e, "energy_kev_unc": eu, "energy_kev_text": et,
               "intensity": it, "intensity_unc": itu, "source": USER_SOURCE, "note": note, "added_at": _now(),
               **fields}
        fname = _EMISSION_FILES[kind]
        self._ensure_base()
        recs = [r for r in self._load(fname)
                if not (r.get("nuclide") == canon and abs(float(r.get("energy_kev", -1)) - e) <= 1e-3
                        and r.get("source") == USER_SOURCE)]
        recs.append(rec)
        self._save(fname, recs)
        self._log([{"changed_at": _now(), "file": fname, "record": f"{canon} {e:g} keV", "field": None,
                    "old": None, "new": "angelegt", "comment": comment}])
        return rec

    def add_gamma(self, nuclide: str, energy: float | str, *, intensity: float | str | None = None,
                  energy_unc: float | str | None = None, intensity_unc: float | str | None = None,
                  radiation: str = "G", note: str | None = None, comment: str | None = None, **fields: Any) -> dict:
        """Eigene Gamma- (oder Röntgen-)Linie hinzufügen, z. B. einen in plotSPE gefundenen Peak::

            db.user.add_gamma("Bi-214", "1764.49(3) keV", intensity="15,3 %", note="eigene Messung")
        """
        return self.add_emission("gamma", nuclide, energy, intensity=intensity, energy_unc=energy_unc,
                                 intensity_unc=intensity_unc, note=note, comment=comment, radiation=radiation,
                                 **fields)

    @_writes
    def remove_emission(self, kind: str, nuclide: str, energy_kev: float, *, tol_kev: float = 1e-3,
                        comment: str | None = None) -> int:
        """Eigene Linie(n) eines Nuklids bei ``energy_kev ± tol_kev`` entfernen. Liefert die Anzahl.

        Linien der zentralen Datenbank lassen sich nicht entfernen.
        """
        if kind not in _EMISSION_FILES:
            raise ValueError(f"Unbekannte Strahlungsart {kind!r}")
        canon = names.normalize(nuclide)
        fname = _EMISSION_FILES[kind]
        recs = self._load(fname)
        keep = [r for r in recs if not (r.get("nuclide") == canon and abs(float(r.get("energy_kev", -1e9))
                                                                            - energy_kev) <= tol_kev)]
        removed = len(recs) - len(keep)
        if not removed:
            raise ValueError(f"Keine eigene {kind}-Linie von {canon} bei {energy_kev} keV")
        self._save(fname, keep)
        self._log([{"changed_at": _now(), "file": fname, "record": f"{canon} {energy_kev:g} keV", "field": None,
                    "old": "vorhanden", "new": None, "comment": comment}])
        return removed

    def remove_gamma(self, nuclide: str, energy_kev: float, *, tol_kev: float = 1e-3,
                     comment: str | None = None) -> int:
        return self.remove_emission("gamma", nuclide, energy_kev, tol_kev=tol_kev, comment=comment)

    def emissions(self, kind: str, nuclide: str | None = None) -> list[dict]:
        """Eigene Linien (Rohdatensätze des Overlays), optional nur eines Nuklids."""
        canon = None if nuclide is None else names.normalize(nuclide)
        return [r for r in self._load(_EMISSION_FILES[kind]) if canon is None or r.get("nuclide") == canon]
