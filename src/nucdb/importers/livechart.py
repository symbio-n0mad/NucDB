"""Importer für ENSDF-Zerfallsstrahlung über die IAEA LiveChart-API.

Die CSV-Antworten lädt :mod:`nucdb.importers.livechart_fetch` in einen Zwischenspeicher; dieser
Importer liest nur diesen Ordner. Übernommen werden Gamma-, Röntgen-, Alpha-, Beta⁻-, Beta⁺- und
Elektronenlinien. Halbwertszeiten und Zerfallsarten kommen weiterhin aus NUBASE bzw. DDEP.

Konventionen:

* Intensitäten in LiveChart gelten pro 100 Zerfälle der Mutter → Bruchteil.
* Der Mutterzustand (Spalte ``p_energy``) wird über die Anregungsenergie dem Grundzustand oder
  einem Isomer der Datenbank zugeordnet; nicht zuordenbare Zeilen entfallen (gezählt).
* Linien mit bekannter Intensität unter ``MIN_INTENSITY`` (0,1 %) entfallen, Linien ohne
  Intensitätsangabe bleiben erhalten. Bei Beta-Zweigen gilt die Schwelle nicht.
* β⁺: LiveChart gibt die EC-Energie an; die Endpunktenergie ist E_EC − 2 m_e c².
* Offensichtliche Quellfehler werden verworfen: mittlere β-Energie > Endpunkt (vermerkt),
  negative Endpunktenergien (Rh-114).
* Die 511-keV-Linie ohne Niveauzuordnung ist Vernichtungsstrahlung: ``radiation: "ANN"``
  (Intensität bis 2, zwei Quanten pro Positron).
* Linien ohne Intensitätsangabe bleiben erhalten (meist kurzlebige, exotische Nuklide).
"""

from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from .. import elements, names
from ..physics import PAIR_THRESHOLD_KEV
from . import common
from .livechart_fetch import code

SOURCE = "ENSDF-LiveChart"
MIN_INTENSITY = 0.001

SOURCE_RECORD = {
    "key": SOURCE,
    "title": "Evaluated Nuclear Structure Data File (ENSDF), abgerufen über die IAEA LiveChart of Nuclides API",
    "publisher": "IAEA Nuclear Data Section; ENSDF: International Network of Nuclear Structure and Decay "
                 "Data Evaluators, NNDC/BNL",
    "url": "https://www-nds.iaea.org/relnsd/vcharthtml/api_v0_guide.html",
    "license": "Frei zugänglich, Zitat erforderlich",
    "redistributable": True,
    "citation": "ENSDF via IAEA LiveChart of Nuclides, https://www-nds.iaea.org/livechart/ "
                "(Evaluatoren und Stand je Nuklid im Feld 'ensdf_reference')",
}


def _pct(x: str) -> float | None:
    x = (x or "").strip()
    if not x:
        return None
    try:
        return float(Decimal(x) / 100)
    except Exception:  # noqa: BLE001
        return None


def _f(x: str) -> float | None:
    x = (x or "").strip()
    if not x:
        return None
    try:
        return float(x)
    except ValueError:
        return None


def _rows(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith(("energy,", "mean_energy,")):
        return []                                   # leere Antwort oder Fehlercode
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    seen: Counter = Counter()
    cols = []
    for h in header:                                 # doppelte Spaltennamen (unc_me) unterscheiden
        seen[h] += 1
        cols.append(h if seen[h] == 1 else f"{h}_{seen[h]}")
    return [dict(zip(cols, r)) for r in reader if r]


class _StateMap:
    """(Z, A, p_energy) → Nuklidname über die Anregungsenergien der Datenbank."""

    def __init__(self, db):
        import math
        self._log = math.log
        self.by_za: dict[tuple[int, int], list[tuple[float, str, float | None]]] = defaultdict(list)
        for n in db.nuclides():
            e = 0.0 if n.isomer == 0 else n.value("level_energy_kev")
            t = n.half_life_s
            self.by_za[(n.z, n.a)].append((None if e is None else float(e), n.name,
                                           t if t and t != float("inf") else None))

    def lookup(self, z: int, a: int, p_energy: str, shift: str, half_life_s: str = "") -> str | None:
        """Mutterzustand über die Anregungsenergie, ersatzweise über die Halbwertszeit zuordnen.

        ENSDF und NUBASE nennen für manche Isomere leicht verschiedene Energien (Rh-106m: 137 bzw.
        136 keV, Lu-168m). Passt die Energie nicht, aber die Halbwertszeit auf 25 %, gilt der Zustand
        mit der passendsten Halbwertszeit.
        """
        e = _f(p_energy) or 0.0
        cands = self.by_za.get((z, a), [])
        if not cands:
            return None
        if e == 0.0 and not shift:
            return next((nm for en, nm, _t in cands if en == 0.0), None)
        with_e = [c for c in cands if c[0] is not None and c[0] > 0]
        if with_e:
            best = min(with_e, key=lambda c: abs(c[0] - e))
            if abs(best[0] - e) <= max(2.0, 0.02 * e):
                return best[1]
        t = _f(half_life_s)
        if t and t > 0:
            iso = [c for c in cands if c[2] and (c[0] is None or c[0] > 0)]
            if iso:
                best = min(iso, key=lambda c: abs(self._log(c[2] / t)))
                if abs(self._log(best[2] / t)) <= self._log(1.25):
                    return best[1]
        return None


def _common(row: dict, rec: dict, *, threshold: bool = True) -> dict | None:
    if threshold and rec.get("intensity") is not None and rec["intensity"] < MIN_INTENSITY:
        return None
    return rec


def parse_file(path: Path, rt: str) -> list[tuple[str, dict, dict]]:
    """CSV einer Strahlungsart → [(Strahlungsdatei, Datensatz ohne Nuklid, Rohzeile)]."""
    out = []
    for r in _rows(path):
        if rt == "g":
            e = _f(r.get("energy"))
            if e is None:
                continue
            rec = {"energy_kev": e, "energy_kev_unc": _f(r.get("unc_en")), "intensity": _pct(r.get("intensity")),
                   "intensity_unc": _pct(r.get("unc_i")), "radiation": "G"}
            if abs(e - 511.0) < 0.5 and not r.get("end_level_energy") and not r.get("multipolarity"):
                rec["radiation"] = "ANN"                 # Vernichtungsstrahlung (bis 200 %: 2 Quanten)
            if r.get("multipolarity"):
                rec["multipolarity"] = r["multipolarity"]
            if r.get("conversion_coeff"):
                rec["conversion_coeff"] = _f(r["conversion_coeff"])
            kind = "decay_gamma"
        elif rt == "x":
            e = _f(r.get("energy"))
            if e is None:
                continue
            shell = (r.get("shell") or "").strip()
            rec = {"energy_kev": e, "energy_kev_unc": _f(r.get("unc_en")), "intensity": _pct(r.get("intensity")),
                   "intensity_unc": _pct(r.get("unc_i")), "radiation": "XK" if shell.startswith("K") else "XL"}
            if shell:
                rec["xray_line"] = shell
            kind = "decay_gamma"
        elif rt == "e":
            e = _f(r.get("energy"))
            if e is None:
                continue
            rec = {"energy_kev": e, "energy_kev_unc": _f(r.get("unc_en")), "intensity": _pct(r.get("intensity")),
                   "intensity_unc": _pct(r.get("unc_i")), "type": (r.get("type") or "").strip() or "?"}
            if r.get("shell"):
                rec["shell"] = r["shell"].strip()
            kind = "decay_electron"
        elif rt == "a":
            e = _f(r.get("energy"))
            if e is None:
                continue
            rec = {"energy_kev": e, "energy_kev_unc": _f(r.get("unc_en")), "intensity": _pct(r.get("intensity")),
                   "intensity_unc": _pct(r.get("unc_i"))}
            if r.get("daughter_level_energy"):
                rec["daughter_level_kev"] = _f(r["daughter_level_energy"])
            kind = "decay_alpha"
        elif rt in ("bm", "bp"):
            if rt == "bm":
                emax, umax = _f(r.get("max_energy")), _f(r.get("unc_me_2"))
            else:
                eec = _f(r.get("energy_ec"))
                emax = None if eec is None or eec <= PAIR_THRESHOLD_KEV else round(eec - PAIR_THRESHOLD_KEV, 4)
                umax = _f(r.get("unc_eec"))
            ib = _pct(r.get("intensity_beta"))
            rec = {"type": "B-" if rt == "bm" else "B+", "energy_kev": emax, "energy_kev_unc": umax,
                   "mean_energy_kev": _f(r.get("mean_energy")), "mean_energy_kev_unc": _f(r.get("unc_me")),
                   "intensity": ib, "intensity_unc": _pct(r.get("unc_ib"))}
            me = rec.get("mean_energy_kev")
            if me is not None and emax is not None and me > emax:
                rec["note"] = f"mittlere Energie {me} keV > Endpunkt in der Quelle, verworfen"
                rec["mean_energy_kev"] = rec["mean_energy_kev_unc"] = None
            if r.get("transition_type"):
                rec["transition"] = r["transition_type"].strip()
            if r.get("log_ft"):
                rec["log_ft"] = _f(r["log_ft"])
            if r.get("daughter_level_energy"):
                rec["daughter_level_kev"] = _f(r["daughter_level_energy"])
            if rt == "bp":
                iec = _pct(r.get("intensity_ec"))
                if iec is not None:
                    rec["ec_intensity"] = iec
                if ib in (None, 0.0) or emax is None:
                    continue                          # reiner EC-Zweig: kein Positron
            elif emax is None or emax <= 0 or not ib:
                continue                              # kein Endpunkt oder Quellfehler (negativ)
            kind = "decay_beta"
        else:
            continue
        if r.get("decay"):
            rec["decay_mode"] = r["decay"].strip()
        if kind != "decay_beta":
            rec = _common(r, rec)
            if rec is None:
                continue
        out.append((kind, rec, r))
    return out


def isomer_feedings(db, states: "_StateMap", src_dir: Path, z: int, a: int) -> list[dict]:
    """Bevölkerung der Tochter-Isomere aus der ENSDF-Niveaubilanz einer Massenkette (Z, A).

    Anteil pro Zerfall der Mutter = direkte β⁻/β⁺/EC/α-Fütterung des Isomerniveaus + Summe aller
    Übergänge, die dort enden (Gammaintensität × (1 + Konversionskoeffizient)). Das Isomerniveau
    wird über die Energie erkannt, ersatzweise über seine Halbwertszeit (NUBASE und ENSDF nennen
    teils verschiedene Energien, z. B. Pa-234m 79 bzw. 73,9 keV).
    """
    import math
    stem = code(z, a)
    rows: list[tuple[str, dict]] = []
    for rt in ("bm", "bp", "a", "g"):
        f = src_dir / f"{stem}_{rt}.csv"
        if f.is_file():
            rows.extend((rt, r) for r in _rows(f))
    # Isomere der möglichen Töchter
    iso_by_za: dict[tuple[int, int], list] = defaultdict(list)
    for n in db.nuclides():
        if n.isomer > 0 and n.value("level_energy_kev") is not None:
            iso_by_za[(n.z, n.a)].append(n)

    def level_is(iso, energy, hl) -> bool:
        e_iso = float(iso.value("level_energy_kev"))
        if energy is None:
            return False
        if abs(energy - e_iso) <= max(0.5, 0.001 * e_iso):
            return True
        t = iso.half_life_s
        return bool(hl and t and t != float("inf") and abs(math.log(hl / t)) <= math.log(1.25)
                    and abs(energy - e_iso) <= max(10.0, 0.1 * e_iso))

    acc: dict[tuple[str, str, str], float] = defaultdict(float)
    for rt, r in rows:
        parent = states.lookup(z, a, r.get("p_energy", ""), r.get("p_energy_shift", ""), r.get("half_life_sec", ""))
        dz, dn = _f(r.get("d_z")), _f(r.get("d_n"))
        if parent is None or dz is None or dn is None:
            continue
        mode = (r.get("decay") or "").strip()
        for iso in iso_by_za.get((int(dz), int(dz + dn)), []):
            if rt == "g":
                if not level_is(iso, _f(r.get("end_level_energy")), _f(r.get("end_level_hl"))):
                    continue
                it = _f(r.get("intensity"))
                if not it:
                    continue
                v = it * (1.0 + (_f(r.get("conversion_coeff")) or 0.0))
            else:
                if not level_is(iso, _f(r.get("daughter_level_energy")), _f(r.get("daughter_level_hl"))):
                    continue
                keys = ("intensity_beta", "intensity_ec") if rt == "bp" else \
                       ("intensity_beta",) if rt == "bm" else ("intensity",)
                v = sum(_f(r.get(k)) or 0.0 for k in keys)
            if v > 0:
                acc[(parent, mode, iso.name)] += v
    return [{"parent": p, "mode": m, "isomer": i, "fraction": round(min(v, 100.0) / 100.0, 8),
             "method": "ENSDF-Niveaubilanz"} for (p, m, i), v in sorted(acc.items())]


def run(root: Path, src_dir: Path) -> dict:
    root, src_dir = Path(root), Path(src_dir)
    if not src_dir.is_dir():
        raise FileNotFoundError(f"Zwischenspeicher fehlt: {src_dir} (python -m nucdb.importers.livechart_fetch)")
    from ..db import NucDB
    db = NucDB(root, overlay=False)
    states = _StateMap(db)
    by_code = {code(n.z, n.a): (n.z, n.a) for n in db.nuclides() if n.z > 0}

    out: dict[str, list[dict]] = defaultdict(list)
    refs: dict[str, str] = {}
    unmatched: Counter = Counter()
    files = sorted(src_dir.glob("*.csv"))
    for p in files:
        stem, _, rt = p.stem.rpartition("_")
        za = by_code.get(stem)
        if za is None:
            continue
        z, a = za
        for kind, rec, raw in parse_file(p, rt):
            name = states.lookup(z, a, raw.get("p_energy", ""), raw.get("p_energy_shift", ""),
                                 raw.get("half_life_sec", ""))
            if name is None:
                unmatched[f"{stem}@{raw.get('p_energy')}"] += 1
                continue
            out[kind].append({"nuclide": name, **rec})
            if name not in refs and raw.get("ensdf_authors"):
                refs[name] = f"{raw['ensdf_authors'].strip()} (ENSDF, Stand {raw.get('ensdf_publication_cut-off', '').strip()})"

    feed: list[dict] = []
    for stem_za in sorted({by_code[p.stem.rpartition("_")[0]] for p in files if p.stem.rpartition("_")[0] in by_code}):
        feed.extend(isomer_feedings(db, states, src_dir, *stem_za))
    n_feed = common.replace_records(root, "isomer_feeding", SOURCE, feed)

    common.upsert_source(root, {**SOURCE_RECORD, "file_name": f"{len(files)} CSV-Dateien (LiveChart-API)",
                                "retrieved_at": common.now()[:10]})
    counts = {k: common.replace_records(root, k, SOURCE, v) for k, v in out.items()}
    for k in ("decay_gamma", "decay_alpha", "decay_beta", "decay_electron"):
        if k not in out:
            counts[k] = common.replace_records(root, k, SOURCE, [])
    # ENSDF-Bearbeiter je Nuklid vermerken
    from ..fileformat import read_file, write_file
    head, recs = read_file(root / "nuclides.json")
    for r in recs:
        if r["name"] in refs:
            r["ensdf_reference"] = refs[r["name"]]
    write_file(root / "nuclides.json", "nuclides", recs)
    summary = (f"ENSDF/LiveChart: {len(files)} Dateien, Gamma/Röntgen {counts['decay_gamma']}, Alpha "
               f"{counts['decay_alpha']}, Beta {counts['decay_beta']}, Elektronen {counts['decay_electron']}; "
               f"{sum(unmatched.values())} Zeilen ohne passenden Mutterzustand; {n_feed} Isomer-Fütterungen")
    common.log_import(root, SOURCE, summary)
    return {"counts": counts, "unmatched": unmatched, "summary": summary}
