"""Importer für DDEP (Decay Data Evaluation Project, LNHB) aus dem Lara-Archiv.

Quelle: ``All-nuclides_lara.zip`` von https://www.lnhb.fr/nuclides/ (eine Datei je Nuklid).
Übernommen werden Halbwertszeit, Zerfallsarten mit Anteilen, Gamma-, Röntgen- und Alpha-Linien.
Beta- und Elektronendaten enthalten die Lara-Dateien nicht; sie kommen aus ENSDF (LiveChart).

Konventionen:

* Gammalinien werden vom angeregten Tochterkern ausgesandt (Spalte ``Origin``) und gehören zum
  zerfallenden Nuklid. Manche Lara-Dateien enthalten zusätzlich die Linien der ganzen Folgekette;
  die Spalte ``Parent`` nennt dann den Zerfall, der die Linie auslöst (Sr-90-Datei: 2186 keV mit
  Parent Y-90). Diese Linien werden dem Parent zugeordnet, nicht der Datei. Hat der Parent eine
  eigene DDEP-Datei, gilt diese; sonst (z. B. Th-227, I-132, U-233) werden die Linien aus der
  Mutterdatei übernommen. Die Intensitäten gelten pro Zerfall des Parent.
* Jahre werden mit 365.2422 d umgerechnet. DDEP gibt T½ zusätzlich in Sekunden an; bei allen
  eindeutig entscheidbaren Fällen bis auf einen passt das nur zum tropischen Jahr.
* ``a*``-Linien (β-verzögerte „long-range“ Alphas, z. B. aus angeregtem Po-212 beim Bi-212-Zerfall)
  gehören zum zerfallenden Nuklid und bekommen ``beta_delayed: true``.
* Intensitäten in % werden zu Bruchteilen. Röntgengruppen mit Energiebereich (``20.07 - 23.17``)
  bekommen die Mitte als ``energy_kev`` und den Bereich in ``energy_range_kev``.
* Der α-Anteil steht in Lara gekürzt (Po-210: "1" statt 100 %) und wird daher als 100 % minus der
  übrigen Zweige berechnet; ebenso ein einzelner auf 0 gerundeter Zweig (Bi-214: α = 0.021 %).
* Alle Nuklide aus DDEP bekommen ``decay_source: "DDEP"`` (Spezifikation 4.5).
"""

from __future__ import annotations

import re
import zipfile
from decimal import Decimal
from pathlib import Path

from .. import names, units
from . import common

SOURCE = "DDEP"
ARCHIVE = "All-nuclides_lara.zip"
URL = "https://www.lnhb.fr/nuclides/All-nuclides_lara.zip"

SOURCE_RECORD = {
    "key": SOURCE,
    "title": "Decay Data Evaluation Project (DDEP) – Recommended Data",
    "publisher": "Laboratoire National Henri Becquerel (LNHB), CEA; veröffentlicht unter der Ägide des BIPM",
    "url": "https://www.lnhb.fr/nuclear-data/nuclear-data-table/",
    "license": "Frei zugänglich, Zitat erforderlich",
    "redistributable": True,
    "citation": "Decay Data Evaluation Project (DDEP), recommended data, LNHB/CEA, "
                "https://www.lnhb.fr/nuclear-data/nuclear-data-table/ (Lara-Dateien)",
    "notes": "Jahr = 365.2422 d (aus den Sekundenangaben bestätigt). Evaluationsjahr je Nuklid im "
             "Feld 'ddep_reference' der Nuklide.",
}

_HL_UNITS = {"s": 1.0, "min": 60.0, "h": 3600.0, "d": 86400.0, "a": units.YEAR_S}
_MODES = {"(B-)": "B-", "(alpha)": "A", "(EC)": "EC", "(B+, EC)": "EC+B+", "(B+)": "B+", "(I.T.)": "IT",
          "(SF)": "SF"}
_MODE_DELTA = {"B-": (1, 0), "A": (-2, -4), "EC": (-1, 0), "EC+B+": (-1, 0), "B+": (-1, 0), "IT": (0, 0)}


def _f(s: str) -> float | None:
    s = s.strip()
    if not s:
        return None
    try:
        return float(s.replace("E", "e"))
    except ValueError:
        return None


def _pct(s: str) -> float | None:
    v = _f(s)
    return None if v is None else float(Decimal(s.strip().replace("E", "e")) / 100)


def _emission(row: list[str]) -> tuple[str, dict] | None:
    """Lara-Zeile → (Strahlungsart, Datensatz) oder None."""
    e_txt, eu, it, iu, typ = row[0], row[1], row[2], row[3], row[4]
    rec: dict = {}
    if " - " in e_txt:
        lo, hi = (float(x) for x in e_txt.split(" - "))
        rec["energy_kev"] = round((lo + hi) / 2, 6)
        rec["energy_range_kev"] = [lo, hi]
    else:
        e = _f(e_txt)
        if e is None:
            return None
        rec["energy_kev"] = e
    rec["energy_kev_unc"] = _f(eu)
    rec["intensity"] = _pct(it)
    rec["intensity_unc"] = _pct(iu)
    if typ == "g":
        kind, rec["radiation"] = "gamma", "G"
    elif typ == "g511":
        kind, rec["radiation"] = "gamma", "ANN"
    elif typ.startswith("XK"):
        kind, rec["radiation"], rec["xray_line"] = "gamma", "XK", typ[1:]
    elif typ.startswith("XL"):
        kind, rec["radiation"] = "gamma", "XL"
        if len(typ) > 2:
            rec["xray_line"] = typ[1:]
    elif typ == "a":
        kind = "alpha"
    elif typ == "a*":                                 # β-verzögertes α aus angeregtem Tochterzustand
        kind = "alpha"
        rec["beta_delayed"] = True
    else:
        return None
    if len(row) > 5 and row[5]:
        rec["origin"] = row[5]
    return kind, rec


def parse_lara(text: str) -> dict:
    """Eine Lara-Datei lesen → dict mit name, half_life, modes, emissions, reference."""
    out: dict = {"modes": [], "emissions": [], "half_life": None, "reference": None, "progeny": {}}
    in_table = False
    for line in text.splitlines():
        p = [x.strip() for x in line.split(";")]
        key = p[0]
        if key == "Nuclide":
            out["name"] = p[1]
        elif key == "Daughter(s)":
            i = 1
            while i < len(p):
                if p[i].startswith("("):
                    out["modes"].append({"mode": _MODES.get(p[i], p[i]), "daughter": p[i + 1] if i + 1 < len(p) else None,
                                         "pct": p[i + 2] if i + 2 < len(p) else "", "text": p[i]})
                    i += 3
                else:
                    i += 1
        elif key.startswith("Half-life (") and out["half_life"] is None:
            unit = key[len("Half-life ("):-1]
            if unit in _HL_UNITS and _f(p[1]) is not None:
                f = _HL_UNITS[unit]
                v, u = _f(p[1]), _f(p[2]) if len(p) > 2 else None
                out["half_life"] = {"value": float(Decimal(p[1]) * Decimal(repr(f))),
                                    "unc": None if u is None else float(Decimal(p[2]) * Decimal(repr(f))),
                                    "text": f"{p[1]}({p[2] if len(p) > 2 else ''}) {unit}"}
        elif key == "Reference":
            out["reference"] = p[1]
        elif key.startswith("Energy (keV)"):
            in_table = True
        elif in_table and len(p) >= 5 and p[0] and (p[0][0].isdigit()):
            parent = p[8] if len(p) > 8 else ""
            em = _emission(p)
            if not em:
                continue
            if parent and parent != out.get("name"):
                # Linie aus dem Zerfall eines Folgenuklids (Intensität pro Zerfall dieses Folgenuklids)
                out["progeny"].setdefault(parent, []).append(em)
            else:
                out["emissions"].append(em)
    return out


def _fix_modes(modes: list[dict]) -> list[dict]:
    """Zerfallsanteile aus der Lara-Kopfzeile aufbereiten.

    In den Lara-Dateien ist der α-Anteil fehlerhaft gekürzt (Po-210: "1" statt 100, Bi-212: "3" statt
    35.93). Der α-Anteil wird deshalb immer als Rest berechnet: 100 % minus aller übrigen Zweige.
    Gleiches gilt für einen einzelnen auf 0 gerundeten Zweig. Solche Werte bekommen ``flag: "~"``.
    """
    vals = [_f(m["pct"]) for m in modes]
    derive = [i for i, m in enumerate(modes) if m["mode"] == "A" or vals[i] == 0]
    others = [Decimal(m["pct"]) for i, m in enumerate(modes) if i not in derive and vals[i] is not None]
    rest = Decimal("100") - sum(others, Decimal(0))
    res = []
    for i, m in enumerate(modes):
        rec = {"mode": m["mode"], "daughter": m["daughter"], "text": f"{m['text']} {m['pct']}"}
        if i in derive:
            if len(derive) == 1 and len(others) == len(modes) - 1 and rest >= 0:
                rec["branching"] = float(rest / 100)
                rec["branching_flag"] = "~"
                rec["note"] = "aus 100 % minus übrige Zweige berechnet (Lara-Angabe gekürzt/gerundet)"
            else:
                rec["branching_flag"] = "?"
        elif vals[i] is None:
            rec["branching_flag"] = "?"
        else:
            rec["branching"] = float(Decimal(m["pct"]) / 100)
        res.append(rec)
    return res


def fetch(src_dir: Path) -> None:
    p = Path(src_dir) / ARCHIVE
    if not p.is_file():
        common.download(URL, p)


def run(root: Path, src_dir: Path) -> dict:
    root, src_dir = Path(root), Path(src_dir)
    archive = src_dir / ARCHIVE
    if not archive.is_file():
        raise FileNotFoundError(f"Quelldatei fehlt: {archive} (mit --download holen)")
    from ..db import NucDB
    known = {n.name for n in NucDB(root, overlay=False).nuclides()}

    meta: dict[str, dict] = {}
    vals: dict[str, dict[str, list[dict]]] = {}
    modes_out: list[dict] = []
    em_out: dict[str, list[dict]] = {"gamma": [], "alpha": []}
    skipped: list[str] = []
    progeny: dict[str, tuple[str, list]] = {}         # Folgenuklid -> (Datei, Linien), erste Fundstelle
    with zipfile.ZipFile(archive) as z:
        for fname in sorted(z.namelist()):
            if not fname.endswith(".lara.txt"):
                continue
            d = parse_lara(z.read(fname).decode("utf-8", "replace"))
            try:
                name = names.normalize(d.get("name") or fname.replace(".lara.txt", ""))
            except names.NuclideNameError:
                skipped.append(fname)
                continue
            if name not in known:
                skipped.append(name)
                continue
            nid = names.parse(name)
            meta[name] = {"z": nid.z, "a": nid.a, "isomer": nid.isomer}
            if d["reference"]:
                meta[name]["ddep_reference"] = d["reference"]
            if d["half_life"]:
                vals[name] = {"half_life_s": [d["half_life"]]}
            for m in _fix_modes(d["modes"]):
                try:
                    m["daughter"] = names.normalize(m["daughter"]) if m["daughter"] else None
                except names.NuclideNameError:
                    m["daughter"] = None
                modes_out.append({"parent": name, **m})
            for kind, rec in d["emissions"]:
                em_out[kind].append({"nuclide": name, **rec})
            for pname, lines in d["progeny"].items():
                progeny.setdefault(pname, (name, lines))

    # Folgenuklide ohne eigene DDEP-Datei: ihre DDEP-Linien stehen nur in der Datei der Mutter
    from_progeny: list[str] = []
    for pname, (holder, lines) in sorted(progeny.items()):
        try:
            canon = names.normalize(pname)
        except names.NuclideNameError:
            continue
        if canon in meta or canon not in known:
            continue
        nid = names.parse(canon)
        meta[canon] = {"z": nid.z, "a": nid.a, "isomer": nid.isomer,
                       "ddep_reference": f"Linien aus der DDEP-Datei von {holder} (keine eigene Datei)"}
        for kind, rec in lines:
            em_out[kind].append({"nuclide": canon, **rec})
        from_progeny.append(canon)

    common.upsert_source(root, {**SOURCE_RECORD, **common.file_info(archive), "retrieved_at": common.now()[:10]})
    created, n_vals = common.replace_nuclide_data(root, SOURCE, meta, vals)
    # decay_source für alle DDEP-Nuklide setzen
    from ..fileformat import read_file, write_file
    head, recs = read_file(root / "nuclides.json")
    for r in recs:
        if r["name"] in meta:
            r["decay_source"] = SOURCE
            r["ddep_reference"] = meta[r["name"]].get("ddep_reference")
    write_file(root / "nuclides.json", "nuclides", recs)
    n_modes = common.replace_records(root, "decay_modes", SOURCE, modes_out)
    n_g = common.replace_records(root, "decay_gamma", SOURCE, em_out["gamma"])
    n_a = common.replace_records(root, "decay_alpha", SOURCE, em_out["alpha"])
    summary = (f"DDEP: {len(meta)} Nuklide, {n_modes} Zerfallsarten, {n_g} Gamma-/Röntgenlinien, "
               f"{n_a} Alphalinien; nur aus Mutter-Dateien: {', '.join(from_progeny) or '—'}; "
               f"übersprungen: {', '.join(skipped) or '—'}")
    common.log_import(root, SOURCE, summary)
    return {"nuclides": len(meta), "skipped": skipped, "summary": summary}
