"""Lese-API der NucDB (Spezifikation Abschnitt 9).

>>> from nucdb import NucDB
>>> db = NucDB()                       # Fundort nach Spezifikation 2
>>> db.nuclide("60Co").half_life("a")
>>> db.find_gammas(609.3, tol_kev=1.5)

Dateien werden erst beim ersten Zugriff gelesen. Prompt-Gammas werden nur geladen, wenn
ausdrücklich nach ihnen gefragt wird.
"""

from __future__ import annotations

import bisect
import os
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from . import elements as _elements
from . import names, schema
from .fileformat import FormatError, read_file, read_json
from .locate import MANIFEST, default_overlay_dir, find_database
from .models import (ActivationGamma, Chain, DecayMode, Element, Emission, LineMatch, Nuclide, PromptGamma,
                     Source, SpecialLine, Value)
from .physics import ELECTRON_MASS_KEV, PAIR_THRESHOLD_KEV


class IncompatibleSchemaError(RuntimeError):
    """Die Datenbank hat eine andere MAJOR-Version als diese Bibliothek."""


class UnknownNuclideError(KeyError):
    """Nuklid ist nicht in der Datenbank."""

    def __str__(self) -> str:  # KeyError setzt sonst Anführungszeichen
        return str(self.args[0]) if self.args else "Unbekanntes Nuklid"


_EMISSION_CORE = ("nuclide", "energy_kev", "energy_kev_unc", "intensity", "intensity_unc", "source")
_NUCLIDE_CORE = ("name", "z", "a", "isomer", "stable", "decay_source", "values")


def _f(x: Any) -> float | None:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _canon(name: Any) -> str:
    """Nuklidname normalisieren; Unlesbares bleibt unverändert (der Validator meldet es)."""
    try:
        return names.normalize(str(name))
    except names.NuclideNameError:
        return str(name)


class NucDB:
    """Zugriff auf eine NucDB-Datenbank samt Ergänzungsdatenbank (Overlay).

    :param path: Datenbankordner. ``None`` = automatisch suchen (Spezifikation 2).
    :param overlay: ``True`` = gemeinsame Ergänzungsdatenbank im Benutzerordner verwenden,
        ``False`` = keine, oder ein eigener Pfad.
    """

    def __init__(self, path: str | os.PathLike | None = None, *, overlay: bool | str | os.PathLike = True):
        self.location: Path = find_database(path)
        self.manifest: dict = read_json(self.location / MANIFEST)
        self.schema_version: str = str(self.manifest.get("schema_version", "0.0.0"))
        if not schema.is_compatible(self.schema_version):
            raise IncompatibleSchemaError(
                f"Datenbank {self.location} hat Schema {self.schema_version}, diese Bibliothek "
                f"unterstützt {schema.SCHEMA_VERSION} (gleiche Hauptversion nötig). "
                "Bitte NucDB bzw. die Datenbank aktualisieren.")
        self.data_version: str | None = self.manifest.get("data_version")

        if overlay is True:
            self.overlay_location: Path | None = default_overlay_dir()
        elif overlay in (False, None):
            self.overlay_location = None
        else:
            self.overlay_location = Path(overlay).expanduser()
        if self.overlay_location is not None:
            om = self.overlay_location / MANIFEST
            if om.is_file():
                ov = str(read_json(om).get("schema_version", schema.SCHEMA_VERSION))
                if not schema.is_compatible(ov):
                    warnings.warn(f"Ergänzungsdatenbank {self.overlay_location} hat inkompatibles "
                                  f"Schema {ov} und wird ignoriert", RuntimeWarning, stacklevel=2)
                    self.overlay_location = None
        self._cache: dict[Any, Any] = {}
        self._overlay_sig = self._overlay_signature()

        from .overlay import UserDB  # zyklischen Import vermeiden
        self.user: UserDB | None = UserDB(self, self.overlay_location) if self.overlay_location else None

    def __repr__(self) -> str:
        return f"NucDB({str(self.location)!r}, data_version={self.data_version!r})"

    # ------------------------------------------------------------------------------------
    # Rohdaten
    # ------------------------------------------------------------------------------------
    def reload(self) -> None:
        """Alle zwischengespeicherten Daten verwerfen (z. B. nach Änderungen am Overlay)."""
        self._cache.clear()
        self._overlay_sig = self._overlay_signature()

    def _overlay_signature(self) -> tuple:
        base = self.overlay_location
        if base is None or not base.is_dir():
            return ()
        return tuple(sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in base.glob("*.json")))

    def overlay_changed(self) -> bool:
        """``True``, wenn ein anderes Programm die Ergänzungsdatenbank seit dem Laden geändert hat."""
        return self._overlay_signature() != getattr(self, "_overlay_sig", ())

    def reload_if_changed(self) -> bool:
        """Neu laden, falls die Ergänzungsdatenbank von außen geändert wurde. Liefert, ob neu geladen wurde.

        Gedacht für langlebige Programme (GUIs): z. B. beim Fokuswechsel aufrufen, damit ein in
        ActivityPartitioner angelegtes Nuklid auch in plotSPE erscheint.
        """
        if self.overlay_changed():
            self.reload()
            return True
        return False

    def _raw(self, name: str) -> list[tuple[dict, bool]]:
        """Datensätze einer Datei: zentrale, dann Overlay. Liefert (Datensatz, aus_overlay)."""
        key = ("raw", name)
        if key not in self._cache:
            out: list[tuple[dict, bool]] = []
            for base, is_user in ((self.location, False), (self.overlay_location, True)):
                if base is None:
                    continue
                p = base / f"{name}.json"
                if p.is_file():
                    try:
                        _head, recs = read_file(p)
                    except FormatError:
                        if is_user:
                            warnings.warn(f"Ergänzungsdatei {p} ist beschädigt und wird ignoriert",
                                          RuntimeWarning, stacklevel=3)
                            continue
                        raise
                    out.extend((r, is_user) for r in recs)
            self._cache[key] = out
        return self._cache[key]

    def _source_priority(self) -> list[str]:
        prio = self.manifest.get("source_priority")
        return list(prio) if isinstance(prio, list) else []

    def _select_sources(self, items: list, decay_source: str | None) -> list:
        """Datensätze eines Nuklids auf die bevorzugte Quelle beschränken (Spezifikation 4.5).

        Overlay-Einträge sind immer dabei. Fehlt die bevorzugte Quelle für diese Datenart, wird die
        erste vorhandene Quelle nach ``manifest.source_priority`` (sonst alphabetisch) genommen.
        """
        user = [i for i in items if i.user]
        central = [i for i in items if not i.user]
        if not central:
            return user
        srcs = {i.source for i in central}
        if decay_source in srcs:
            chosen = decay_source
        else:
            prio = self._source_priority()
            ranked = sorted(srcs, key=lambda s: (prio.index(s) if s in prio else len(prio), s))
            chosen = ranked[0]
        return [i for i in central if i.source == chosen] + user

    # ------------------------------------------------------------------------------------
    # Quellen, Größen, Elemente
    # ------------------------------------------------------------------------------------
    def sources(self) -> dict[str, Source]:
        if "sources" not in self._cache:
            out: dict[str, Source] = {}
            for rec, user in self._raw("sources"):
                key = str(rec.get("key", ""))
                if not key or (key in out and user):  # Overlay darf zentrale Quellen nicht umdefinieren
                    continue
                out[key] = Source(key=key, fields=dict(rec), user=user)
            self._cache["sources"] = out
        return self._cache["sources"]

    def source(self, key: str) -> Source:
        try:
            return self.sources()[key]
        except KeyError:
            raise KeyError(f"Unbekannte Quelle: {key!r}") from None

    def quantities(self) -> dict[str, dict]:
        """Registry der skalaren Größen: Name → Datensatz (unit, dtype, description)."""
        if "quantities" not in self._cache:
            out: dict[str, dict] = {}
            for rec, user in self._raw("quantities"):
                q = rec.get("quantity")
                if q and not (q in out and user):
                    out[q] = dict(rec)
            self._cache["quantities"] = out
        return self._cache["quantities"]

    def elements(self) -> dict[int, Element]:
        if "elements" not in self._cache:
            recs = {int(r["z"]): r for r, _u in self._raw("elements") if isinstance(r.get("z"), (int, float))}
            out = {}
            for z, sym, en, de in _elements.all_elements():
                rec = recs.get(z, {})
                extra = {k: v for k, v in rec.items() if k not in ("z", "symbol", "name_en", "name_de")}
                out[z] = Element(z, sym, rec.get("name_en", en), rec.get("name_de", de), extra)
            self._cache["elements"] = out
        return self._cache["elements"]

    def element(self, key: int | str) -> Element:
        z = key if isinstance(key, int) else _elements.z_of(str(key))
        try:
            return self.elements()[z]
        except KeyError:
            raise KeyError(f"Unbekanntes Element: {key!r}") from None

    # ------------------------------------------------------------------------------------
    # Nuklide
    # ------------------------------------------------------------------------------------
    def _nuclide_map(self) -> dict[str, Nuclide]:
        if "nuclides" in self._cache:
            return self._cache["nuclides"]
        acc: dict[str, dict] = {}
        for rec, user in self._raw("nuclides"):
            name = _canon(rec.get("name", ""))
            entry = acc.get(name)
            if entry is None:
                try:
                    nid = names.parse(name)
                    z, a, iso = nid
                except names.NuclideNameError:
                    z, a, iso = int(rec.get("z", -1)), int(rec.get("a", -1)), int(rec.get("isomer", 0))
                entry = acc[name] = {"z": z, "a": a, "isomer": iso, "stable": bool(rec.get("stable", False)),
                                     "decay_source": rec.get("decay_source"), "fields": {},
                                     "values": defaultdict(list), "user": user}
            else:
                # Overlay ergänzt bzw. übersteuert ausdrücklich angegebene Felder
                if "stable" in rec:
                    entry["stable"] = bool(rec["stable"])
                if "decay_source" in rec:
                    entry["decay_source"] = rec["decay_source"]
            entry["fields"].update({k: v for k, v in rec.items() if k not in _NUCLIDE_CORE})
            for q, vals in (rec.get("values") or {}).items():
                if isinstance(vals, dict):
                    vals = [vals]
                for v in vals or []:
                    if not isinstance(v, dict):
                        continue
                    entry["values"][q].append(Value(
                        value=v.get("value"), source=str(v.get("source", "")), unc=_f(v.get("unc")),
                        preferred=bool(v.get("preferred", False)), text=v.get("text"), flag=v.get("flag"),
                        user=user))
        out: dict[str, Nuclide] = {}
        for name, e in acc.items():
            vbq: dict[str, tuple[Value, ...]] = {}
            for q, vals in e["values"].items():
                pref_idx = next((i for i, v in enumerate(vals) if v.user and v.preferred), None)
                if pref_idx is None:
                    pref_idx = next((i for i, v in enumerate(vals) if v.preferred), 0)
                ordered = [vals[pref_idx]] + [v for i, v in enumerate(vals) if i != pref_idx]
                vbq[q] = tuple(Value(v.value, v.source, v.unc, i == 0, v.text, v.flag, v.user)
                               for i, v in enumerate(ordered))
            out[name] = Nuclide(name=name, z=e["z"], a=e["a"], isomer=e["isomer"], stable=e["stable"],
                                decay_source=e["decay_source"], values_by_quantity=vbq,
                                fields=e["fields"], user=e["user"])
        self._cache["nuclides"] = out
        return out

    def nuclide(self, name: str) -> Nuclide:
        """Nuklid nach Namen (beliebige gängige Schreibweise, z. B. ``"60Co"``)."""
        canon = names.normalize(name)
        try:
            return self._nuclide_map()[canon]
        except KeyError:
            raise UnknownNuclideError(f"Nuklid nicht in der Datenbank: {canon}") from None

    def has_nuclide(self, name: str) -> bool:
        try:
            return names.normalize(name) in self._nuclide_map()
        except names.NuclideNameError:
            return False

    def nuclides(self, *, z: int | None = None, a: int | None = None, stable: bool | None = None,
                 user: bool | None = None) -> list[Nuclide]:
        """Alle Nuklide (sortiert nach Z, A, Isomer), optional gefiltert."""
        res = [n for n in self._nuclide_map().values()
               if (z is None or n.z == z) and (a is None or n.a == a)
               and (stable is None or n.stable == stable) and (user is None or n.user == user)]
        res.sort(key=lambda n: (n.z, n.a, n.isomer))
        return res

    def _decay_source_of(self, name: str) -> str | None:
        n = self._nuclide_map().get(name)
        return n.decay_source if n else None

    # ------------------------------------------------------------------------------------
    # Zerfallsarten und Ketten
    # ------------------------------------------------------------------------------------
    def _modes_by_parent(self) -> dict[str, list[DecayMode]]:
        if "modes" not in self._cache:
            by: dict[str, list[DecayMode]] = defaultdict(list)
            for rec, user in self._raw("decay_modes"):
                parent = _canon(rec.get("parent"))
                daughter = rec.get("daughter")
                extra = {k: v for k, v in rec.items() if k not in
                         ("parent", "mode", "daughter", "branching", "branching_unc", "q_value_kev", "source")}
                by[parent].append(DecayMode(
                    parent=parent, mode=rec.get("mode"), daughter=None if daughter is None else _canon(daughter),
                    branching=_f(rec.get("branching")), source=str(rec.get("source", "")),
                    branching_unc=_f(rec.get("branching_unc")), q_value_kev=_f(rec.get("q_value_kev")),
                    fields=extra, user=user))
            self._cache["modes"] = dict(by)
        return self._cache["modes"]

    def decay_modes(self, name: str, *, all_sources: bool = False) -> list[DecayMode]:
        """Zerfallsarten eines Nuklids (aus seiner bevorzugten Quelle, Overlay immer dabei).

        Jede Zerfallsart trägt ``effective_branching``: den Anteil, der wirklich zu ihrer Tochter
        führt (Hauptzweig minus Teilzweige mit anderer Tochter, Spezifikation 4.6).
        """
        canon = names.normalize(name)
        items = self._modes_by_parent().get(canon, [])
        sel = list(items) if all_sources else self._select_sources(items, self._decay_source_of(canon))
        return self._apply_isomer_feeding(canon, _with_effective_branching(sel))

    def isomer_feedings(self, name: str) -> list[dict]:
        """Bevölkerung von Tochter-Isomeren je Mutter (Datei ``isomer_feeding.json``)."""
        if "feeding" not in self._cache:
            by: dict[str, list[dict]] = defaultdict(list)
            for rec, _u in self._raw("isomer_feeding"):
                by[_canon(rec.get("parent"))].append(dict(rec, isomer=_canon(rec.get("isomer"))))
            self._cache["feeding"] = dict(by)
        return list(self._cache["feeding"].get(names.normalize(name), []))

    def _apply_isomer_feeding(self, parent: str, modes: list[DecayMode]) -> list[DecayMode]:
        """Zweige zum Grundzustand der Tochter auf Isomer und Grundzustand aufteilen.

        NUBASE und DDEP nennen als Tochter nur den Grundzustand (Mo-99 → Tc-99). Ist bekannt, welcher
        Anteil der Zerfälle im Isomer landet (Mo-99 → Tc-99m 87,8 %), wird ein zusätzlicher Zweig zum
        Isomer erzeugt und der Zweig zum Grundzustand entsprechend verkleinert.
        """
        from dataclasses import replace
        feeds = self.isomer_feedings(parent)
        if not feeds or any(m.user for m in modes):
            return modes
        out = list(modes)
        for fd in feeds:
            iso = fd["isomer"]
            try:
                gs = names.canonical_name(*names.parse(iso)[:2], 0)
            except names.NuclideNameError:
                continue
            if any(m.daughter == iso for m in out):
                continue                                  # Quelle nennt das Isomer schon selbst
            idx = next((i for i, m in enumerate(out) if m.daughter == gs and not m.informational
                        and m.effective_branching is not None), None)
            if idx is None:
                continue
            main = out[idx]
            frac = min(float(fd["fraction"]), main.effective_branching)
            out[idx] = replace(main, effective_branching=round(max(main.effective_branching - frac, 0.0), 12))
            out.append(DecayMode(parent=parent, mode=main.mode, daughter=iso, branching=None,
                                 source=str(fd.get("source", "")), effective_branching=round(frac, 12),
                                 fields={"isomer_feeding": True, "method": fd.get("method")}))
        return out

    def chain(self, name: str, *, min_branching: float | None = None, include_unknown: bool = True,
              max_nuclides: int = 1000) -> Chain:
        """Zerfallskette ab ``name`` bis zu den stabilen Endprodukten.

        ``Chain.nuclides`` ist so sortiert, dass jede Mutter vor ihren Töchtern steht.
        Töchter, die nicht in der Datenbank stehen, landen in ``Chain.unknown`` (Datenfehler, sie
        gelten nicht als stabil). Instabile Nuklide ohne Zerfallsdaten landen in ``Chain.open_ends``.

        :param min_branching: Zweige mit kleinerem effektivem Anteil weglassen, z. B. ``1e-4`` für
            eine übersichtliche Kette ohne extrem seltene Zweige (Clusterzerfälle, 2β …).
        :param include_unknown: Zweige mit unbekanntem Anteil (``?``) mitnehmen.
        """
        root = names.normalize(name)
        nucs = self._nuclide_map()
        if root not in nucs:
            raise UnknownNuclideError(f"Nuklid nicht in der Datenbank: {root}")
        seen: list[str] = []
        edges: list[DecayMode] = []
        unknown: list[str] = []
        stack = [root]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.append(cur)
            if len(seen) > max_nuclides:
                raise RuntimeError(f"Kette ab {root} hat mehr als {max_nuclides} Nuklide")
            if nucs[cur].stable:                    # "stabil" mit nur vermuteten Zerfällen
                continue
            for m in self.decay_modes(cur):
                if m.informational:
                    continue
                eb = m.effective_branching
                if eb is None and not include_unknown:
                    continue
                if eb is not None and min_branching is not None and eb < min_branching:
                    continue
                edges.append(m)
                d = m.daughter
                if d is None:
                    continue
                if d not in nucs:
                    if d not in unknown:
                        unknown.append(d)
                    continue
                if d not in seen:
                    stack.append(d)
        # Topologisch sortieren (Kahn), bei Gleichstand in Entdeckungsreihenfolge
        indeg = {n: 0 for n in seen}
        for e in edges:
            if e.daughter in indeg and e.parent in indeg and e.daughter != e.parent:
                indeg[e.daughter] += 1
        order: list[str] = []
        ready = [n for n in seen if indeg[n] == 0]
        while ready:
            n = ready.pop(0)
            order.append(n)
            for e in edges:
                if e.parent == n and e.daughter in indeg and e.daughter != n:
                    indeg[e.daughter] -= 1
                    if indeg[e.daughter] == 0:
                        ready.append(e.daughter)
        if len(order) < len(seen):  # Zyklus (sollte es physikalisch nicht geben)
            order += [n for n in seen if n not in order]
        open_ends = [n for n in order if not nucs[n].stable and not any(e.parent == n for e in edges)]
        return Chain(root=root, nuclides=tuple(order), edges=tuple(edges), unknown=tuple(unknown),
                     open_ends=tuple(open_ends))

    # ------------------------------------------------------------------------------------
    # Zerfallsstrahlung
    # ------------------------------------------------------------------------------------
    def _emissions(self, kind: str) -> tuple[dict[str, list[Emission]], dict[str, list[Emission]],
                                             list[float], list[Emission]]:
        """(alle je Nuklid, bevorzugte je Nuklid, sortierte Energien, zugehörige Linien)."""
        key = ("emissions", kind)
        if key not in self._cache:
            fname = schema.EMISSION_FILES[kind]
            allby: dict[str, list[Emission]] = defaultdict(list)
            for rec, user in self._raw(fname):
                e_kev = _f(rec.get("energy_kev"))
                if e_kev is None:
                    continue
                allby[_canon(rec.get("nuclide"))].append(Emission(
                    kind=kind, nuclide=_canon(rec.get("nuclide")), energy_kev=e_kev,
                    source=str(rec.get("source", "")), energy_kev_unc=_f(rec.get("energy_kev_unc")),
                    intensity=_f(rec.get("intensity")), intensity_unc=_f(rec.get("intensity_unc")),
                    fields={k: v for k, v in rec.items() if k not in _EMISSION_CORE}, user=user))
            prefby: dict[str, list[Emission]] = {}
            flat: list[Emission] = []
            for nuc, items in allby.items():
                items.sort(key=lambda x: x.energy_kev)
                sel = self._select_sources(items, self._decay_source_of(nuc))
                sel.sort(key=lambda x: x.energy_kev)
                prefby[nuc] = sel
                flat.extend(sel)
            flat.sort(key=lambda x: x.energy_kev)
            self._cache[key] = (dict(allby), prefby, [x.energy_kev for x in flat], flat)
        return self._cache[key]

    def emissions(self, kind: str, name: str, *, min_intensity: float | None = None,
                  all_sources: bool = False, **filters: Any) -> list[Emission]:
        """Strahlung eines Nuklids. ``kind``: gamma, alpha, beta, electron.

        Weitere Schlüsselwörter filtern nach Feldern, z. B. ``radiation="G"`` oder ``type="B-"``.
        """
        if kind not in schema.EMISSION_FILES:
            raise ValueError(f"Unbekannte Strahlungsart {kind!r}")
        canon = names.normalize(name)
        allby, prefby, _e, _l = self._emissions(kind)
        items = allby.get(canon, []) if all_sources else prefby.get(canon, [])
        res = []
        for x in items:
            if min_intensity is not None and x.intensity is not None and x.intensity < min_intensity:
                continue
            if any(x.fields.get(k) != v for k, v in filters.items()):
                continue
            res.append(x)
        return res

    def gammas(self, name: str, *, min_intensity: float | None = None, all_sources: bool = False,
               radiation: str | None = None) -> list[Emission]:
        """Gamma-/Röntgenlinien eines Nuklids. ``radiation``: G, XK, XL, ANN (oder ``None`` = alle)."""
        f = {"radiation": radiation} if radiation else {}
        return self.emissions("gamma", name, min_intensity=min_intensity, all_sources=all_sources, **f)

    def alphas(self, name: str, *, min_intensity: float | None = None, all_sources: bool = False) -> list[Emission]:
        return self.emissions("alpha", name, min_intensity=min_intensity, all_sources=all_sources)

    def betas(self, name: str, *, type: str | None = None, min_intensity: float | None = None,
              all_sources: bool = False) -> list[Emission]:
        """Beta-Zweige (``energy_kev`` = Endpunktenergie, ``mean_energy_kev`` im Feld)."""
        f = {"type": type} if type else {}
        return self.emissions("beta", name, min_intensity=min_intensity, all_sources=all_sources, **f)

    def electrons(self, name: str, *, type: str | None = None, min_intensity: float | None = None,
                  all_sources: bool = False) -> list[Emission]:
        f = {"type": type} if type else {}
        return self.emissions("electron", name, min_intensity=min_intensity, all_sources=all_sources, **f)

    def special_lines(self, kind: str | None = None) -> list[SpecialLine]:
        if "special" not in self._cache:
            out = []
            for rec, _user in self._raw("special_lines"):
                out.append(SpecialLine(
                    kind=str(rec.get("kind", "")), source=str(rec.get("source", "")),
                    energy_kev=_f(rec.get("energy_kev")), offset_kev=_f(rec.get("offset_kev")),
                    origin=rec.get("origin"), description=rec.get("description"),
                    fields={k: v for k, v in rec.items() if k not in
                            ("kind", "source", "energy_kev", "offset_kev", "origin", "description")}))
            self._cache["special"] = out
        return [s for s in self._cache["special"] if kind is None or s.kind == kind]

    #: Gewichte für die Bewertung von Escape-Peaks und Sonderlinien (grobe, detektorunabhängige Annahme)
    ESCAPE_WEIGHT = {"single_escape": 0.05, "double_escape": 0.02}
    SPECIAL_WEIGHT = 0.5
    UNKNOWN_INTENSITY = 1e-4

    def find_gammas(self, energy_kev: float, tol_kev: float = 1.0, *, min_intensity: float | None = None,
                    min_half_life_s: float | None = None, nuclides: Iterable[str] | None = None,
                    include_special: bool = True, include_escapes: bool = True,
                    include_annihilation: bool = False, sort: str = "score") -> list[LineMatch]:
        """Peak-Identifikation in **Zerfalls**spektren: Kandidaten bei ``energy_kev ± tol_kev``.

        Durchsucht Gamma-/Röntgenlinien (bevorzugte Quelle je Nuklid), feste Sonderlinien
        (511 keV, 1022 keV, Pb-Röntgen …) und – wenn ``include_escapes`` – Single-/Double-Escape-Peaks.
        Prompt-Gammas werden **nie** einbezogen.

        :param min_intensity: Linien mit kleinerer (bekannter) Intensität weglassen.
        :param min_half_life_s: Nuklide mit kürzerer Halbwertszeit weglassen, z. B. ``3600`` für
            Proben, die erst nach einer Stunde gemessen werden. Achtung: kurzlebige Folgeprodukte
            (Bi-214, Pb-214 …) fallen dann auch weg; dafür besser ``nuclides`` verwenden.
        :param nuclides: nur diese Nuklide berücksichtigen (z. B. die Bibliothek eines Tools).
        :param include_annihilation: auch die 511-keV-Linien (``ANN``) einzelner β⁺-Strahler liefern.
            Standard: nein, die Sonderlinie ``annihilation`` steht für alle.
        :param sort: ``"score"`` (Standard): nach Bewertung = Intensität × Gauß-Gewicht des Abstands
            (Breite ``tol_kev/2``); Escape-Peaks zählen schwächer, Linien ohne Intensität fast gar nicht.
            ``"delta"``: nur nach Abstand.
        Die Bewertung steht in ``LineMatch.score``.
        """
        import math
        _a, _p, energies, lines = self._emissions("gamma")
        nucs = self._nuclide_map()
        out: list[LineMatch] = []
        width = max(tol_kev / 2.0, 1e-9)
        allowed = None if nuclides is None else {names.normalize(n) for n in nuclides}

        def window(center: float):
            lo = bisect.bisect_left(energies, center - tol_kev)
            hi = bisect.bisect_right(energies, center + tol_kev)
            for x in lines[lo:hi]:
                if min_intensity is not None and x.intensity is not None and x.intensity < min_intensity:
                    continue
                if allowed is not None and x.nuclide not in allowed:
                    continue
                if not include_annihilation and x.fields.get("radiation") == "ANN":
                    continue
                if min_half_life_s is not None:
                    n = nucs.get(x.nuclide)
                    t = None if n is None else n.half_life_s
                    if t is None or t < min_half_life_s:
                        continue
                yield x

        def score(kind: str, delta: float, line) -> float:
            it = getattr(line, "intensity", None)
            base = self.SPECIAL_WEIGHT if kind == "special" else (it if it is not None else self.UNKNOWN_INTENSITY)
            return base * self.ESCAPE_WEIGHT.get(kind, 1.0) * math.exp(-0.5 * (delta / width) ** 2)

        def add(kind: str, peak: float, line) -> None:
            d = energy_kev - peak
            out.append(LineMatch(kind, peak, d, line, score(kind, d, line)))

        for x in window(energy_kev):
            add("decay", x.energy_kev, x)
        if include_escapes:
            for kind, off in (("single_escape", ELECTRON_MASS_KEV), ("double_escape", PAIR_THRESHOLD_KEV)):
                for x in window(energy_kev + off):
                    if x.energy_kev > PAIR_THRESHOLD_KEV and x.fields.get("radiation") in (None, "G"):
                        add(kind, x.energy_kev - off, x)
        if include_special:
            for s in self.special_lines():
                if s.energy_kev is not None and abs(s.energy_kev - energy_kev) <= tol_kev:
                    add("special", s.energy_kev, s)
        if sort == "delta":
            out.sort(key=lambda m: (abs(m.delta_kev), -(getattr(m.line, "intensity", None) or 0.0)))
        else:
            out.sort(key=lambda m: (-m.score, abs(m.delta_kev)))
        return out

    # ------------------------------------------------------------------------------------
    # Aktivierungslinien (NAA)
    # ------------------------------------------------------------------------------------
    def activation_gammas(self, *, element: str | None = None, target: str | None = None,
                          product: str | None = None) -> list[ActivationGamma]:
        """Zerfallslinien von Aktivierungsprodukten mit partiellem Querschnitt σγ und k0 (für NAA).

        Anders als ``gammas()`` beziehen sich die Werte auf das **Target** (Neutroneneinfang), nicht
        auf einen Zerfall. Nur in Datenbanken mit entsprechender Quelle vorhanden.
        """
        if "activation" not in self._cache:
            lines = [_activation_from(r, u) for r, u in self._raw("activation_gamma") if _f(r.get("energy_kev")) is not None]
            lines.sort(key=lambda x: x.energy_kev)
            self._cache["activation"] = lines
        sym = None if element is None else _elements.symbol(_elements.z_of(element))
        tgt = None if target is None else names.normalize(target)
        prd = None if product is None else names.normalize(product)
        return [x for x in self._cache["activation"] if (sym is None or x.element == sym)
                and (tgt is None or x.target == tgt) and (prd is None or x.product == prd)]


    # ------------------------------------------------------------------------------------
    # Prompt-Gammas (getrennt!)
    # ------------------------------------------------------------------------------------
    def _prompt(self) -> tuple[list[float], list[PromptGamma]]:
        if "prompt" not in self._cache:
            lines = []
            for rec, user in self._raw("prompt_gamma"):
                e = _f(rec.get("energy_kev"))
                if e is None:
                    continue
                lines.append(PromptGamma(
                    target=_canon(rec.get("target")), energy_kev=e, source=str(rec.get("source", "")),
                    product=None if rec.get("product") is None else _canon(rec.get("product")),
                    element=rec.get("element"), energy_kev_unc=_f(rec.get("energy_kev_unc")),
                    sigma_partial_b=_f(rec.get("sigma_partial_b")),
                    sigma_partial_b_unc=_f(rec.get("sigma_partial_b_unc")),
                    k0=_f(rec.get("k0")), k0_unc=_f(rec.get("k0_unc")),
                    fields={k: v for k, v in rec.items() if k not in PromptGamma.__dataclass_fields__},
                    user=user))
            lines.sort(key=lambda x: x.energy_kev)
            self._cache["prompt"] = ([x.energy_kev for x in lines], lines)
        return self._cache["prompt"]

    def prompt_gammas(self, *, element: str | None = None, target: str | None = None) -> list[PromptGamma]:
        """Prompt-Gammas (n,γ), optional nach Element oder Target-Nuklid gefiltert."""
        _e, lines = self._prompt()
        sym = None if element is None else _elements.symbol(_elements.z_of(element))
        tgt = None if target is None else names.normalize(target)
        return [x for x in lines if (sym is None or x.element == sym) and (tgt is None or x.target == tgt)]

    def find_prompt_gammas(self, energy_kev: float, tol_kev: float = 1.0) -> list[LineMatch]:
        energies, lines = self._prompt()
        lo = bisect.bisect_left(energies, energy_kev - tol_kev)
        hi = bisect.bisect_right(energies, energy_kev + tol_kev)
        out = [LineMatch("prompt", x.energy_kev, energy_kev - x.energy_kev, x) for x in lines[lo:hi]]
        out.sort(key=lambda m: (abs(m.delta_kev), -(m.line.sigma_partial_b or 0.0)))
        return out


def _activation_from(rec: dict, user: bool) -> "ActivationGamma":
    core = ("target", "product", "element", "energy_kev", "energy_kev_unc", "sigma_partial_b",
            "sigma_partial_b_unc", "k0", "k0_unc", "half_life_s", "source")
    return ActivationGamma(
        target=_canon(rec.get("target")), energy_kev=float(rec["energy_kev"]), source=str(rec.get("source", "")),
        product=None if rec.get("product") is None else _canon(rec.get("product")), element=rec.get("element"),
        energy_kev_unc=_f(rec.get("energy_kev_unc")), sigma_partial_b=_f(rec.get("sigma_partial_b")),
        sigma_partial_b_unc=_f(rec.get("sigma_partial_b_unc")), k0=_f(rec.get("k0")), k0_unc=_f(rec.get("k0_unc")),
        half_life_s=_f(rec.get("half_life_s")),
        fields={k: v for k, v in rec.items() if k not in core}, user=user)


def _with_effective_branching(modes: list[DecayMode]) -> list[DecayMode]:
    from dataclasses import replace
    out = []
    for m in modes:
        pm = m.parent_mode
        if pm:
            main = next((x for x in modes if x.mode == pm and x.source == m.source and not x.parent_mode), None)
            same = main is not None and main.daughter == m.daughter
            out.append(replace(m, effective_branching=None if same else m.branching, informational=same))
            continue
        subs = [x for x in modes if x.parent_mode == m.mode and x.source == m.source and x.daughter != m.daughter]
        eff = m.branching
        if eff is not None and subs:
            eff = round(max(eff - sum(x.branching or 0.0 for x in subs), 0.0), 12)
        out.append(replace(m, effective_branching=eff))
    return out


def open_database(path: str | os.PathLike | None = None, **kw: Any) -> NucDB:
    """Kurzform für :class:`NucDB`."""
    return NucDB(path, **kw)


__all__: Iterable[str] = ("NucDB", "IncompatibleSchemaError", "UnknownNuclideError", "open_database")
