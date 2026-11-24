"""Importer für die PGAA-Excel-Dateien in ``db-source/`` (nur für **lokale** Datenbanken).

Die Herkunft der Dateien ist noch nicht geklärt (vermutlich IAEA „Database of Prompt Gamma Rays
from Slow Neutron Capture for Elemental Analysis“, 2007). Die Quelle ist deshalb
``redistributable: false``: Sie darf nur in eine lokale Datenbank (z. B. ``db-local/``), nie in die
verteilte Momentaufnahme ``src/nucdb/data``. ``nucdb validate --distributable`` prüft das.

Dateien und Ziel:

* ``Liste-promptgammas.xls``  → ``prompt_gamma.json`` (Target, Produkt, E, σγ, k0)
* ``Liste-Gammas-Zerfall.xls`` → ``activation_gamma.json`` (NAA: Target, Produkt, E, σγ, k0)
* ``Liste-isotope-häufigkeiten.xls`` → Werte ``abundance_percent``, ``sigma_capture_b``,
  ``g_factor_westcott`` der Nuklide
* ``Liste-Daten-Elemente.xls`` → Atomgewicht und Einfangquerschnitt der Elemente

σγ ist der elementare partielle Querschnitt (Häufigkeit × Einfangquerschnitt × Emissionswahr-
scheinlichkeit) in barn. Benötigt ``xlrd`` (``pip install nucdb[import]``).
"""

from __future__ import annotations

from pathlib import Path

from .. import elements, names, units
from ..fileformat import read_file, write_file
from . import common

SOURCE = "PGAA-XLS"
FILES = {
    "prompt": "Liste-promptgammas.xls",
    "activation": "Liste-Gammas-Zerfall.xls",
    "isotopes": "Liste-isotope-häufigkeiten.xls",
    "elements": "Liste-Daten-Elemente.xls",
}

SOURCE_RECORD = {
    "key": SOURCE,
    "title": "Prompt- und Aktivierungsgammas, Isotopen- und Elementdaten (Excel-Listen)",
    "publisher": "Herkunft noch ungeklärt – vermutlich IAEA, Database of Prompt Gamma Rays from Slow "
                 "Neutron Capture for Elemental Analysis (STI/PUB/1263, 2007)",
    "license": "ungeklärt",
    "redistributable": False,
    "citation": "PGAA-Excel-Listen (Herkunft wird geklärt)",
    "notes": "Nur in lokalen Datenbanken verwenden, nicht weitergeben.",
}


def _xlrd():
    try:
        import xlrd  # noqa: PLC0415
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("Für den PGAA-Import wird 'xlrd' benötigt: pip install 'nucdb[import]'") from e
    return xlrd


def _rows(path: Path):
    sh = _xlrd().open_workbook(str(path)).sheet_by_index(0)
    for r in range(2, sh.nrows):                     # zwei Kopfzeilen
        yield [sh.cell_value(r, c) for c in range(sh.ncols)]


def _num(x) -> float | None:
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _measured(text, value, unc=None) -> tuple[float | None, float | None, str | None]:
    """Wert mit Unsicherheit: zuerst aus dem Originaltext (``787.2(6)``), sonst aus den Zahlenspalten."""
    t = str(text).strip() if text not in (None, "") else ""
    if t:
        try:
            v, u = units.parse_number(t)
            if u is None and unc is not None:
                u = _num(unc)
            return v, u, t
        except units.UnitError:
            pass
    return _num(value), _num(unc), (t or None)


def _isotope(text: str) -> str | None:
    try:
        return names.normalize(str(text).strip())
    except names.NuclideNameError:
        return None


def parse_lines(path: Path, *, kind: str) -> list[dict]:
    """Prompt- oder Aktivierungsliste → Datensätze (ohne Quelle)."""
    out = []
    for row in _rows(path):
        a, iso, z = _num(row[0]), row[1], _num(row[2])
        if a is None or z is None:
            continue
        product = _isotope(iso)
        try:
            target = names.canonical_name(int(z), int(a), 0)
        except ValueError:
            continue
        e, eu, et = _measured(row[4], row[5])
        if e is None:
            continue
        sg, sgu, sgt = _measured(row[6], row[7], row[8])
        if kind == "prompt":
            k0, k0u, _ = _measured(row[9], row[10], row[11])
        else:
            k0, k0u, _ = _measured(row[11], row[12], row[13])
        rec = {"target": target, "product": product, "element": elements.symbol(int(z)),
               "energy_kev": e, "energy_kev_unc": eu, "sigma_partial_b": sg, "sigma_partial_b_unc": sgu,
               "k0": k0, "k0_unc": k0u}
        if kind == "activation":
            rec["half_life_s"] = _num(row[10])
            rec["half_life_text"] = str(row[9]).strip() or None
        out.append(rec)
    return out


def parse_isotopes(path: Path) -> dict[str, dict[str, list[dict]]]:
    vals: dict[str, dict[str, list[dict]]] = {}
    for row in _rows(path):
        name = _isotope(row[1])
        if name is None:
            continue
        v: dict[str, list[dict]] = {}
        ab, abu, abt = _measured(row[4], row[5], row[6])
        if ab is not None:
            v["abundance_percent"] = [{"value": ab, "unc": abu, "text": abt}]
        sg, sgu, sgt = _measured(row[7], row[8], row[9])
        if sg is not None and str(row[8]).strip():   # He-4: Wertspalte leer = kein Wert
            v["sigma_capture_b"] = [{"value": sg, "unc": sgu, "text": sgt}]
        g = _num(row[10])
        if g is not None:
            v["g_factor_westcott"] = [{"value": g}]
        if v:
            vals[name] = v
    return vals


def parse_elements(path: Path) -> dict[int, dict]:
    out: dict[int, dict] = {}
    for row in _rows(path):
        z = _num(row[0])
        if z is None:
            continue
        aw, awu, awt = _measured(row[3], row[4], row[5])
        xs, xsu, xst = _measured(row[6], row[7], row[8])
        out[int(z)] = {"atomic_weight_u": aw, "atomic_weight_u_unc": awu, "atomic_weight_text": awt,
                       "sigma_capture_b": xs, "sigma_capture_b_unc": xsu, "sigma_capture_text": xst}
    return out


def run(root: Path, src_dir: Path) -> dict:
    root, src_dir = Path(root), Path(src_dir)
    paths = {k: src_dir / v for k, v in FILES.items()}
    for p in paths.values():
        if not p.is_file():
            raise FileNotFoundError(f"Quelldatei fehlt: {p}")
    info = [common.file_info(p) for p in paths.values()]
    common.upsert_source(root, {**SOURCE_RECORD, "file_name": ", ".join(i["file_name"] for i in info),
                                "file_sha256": ", ".join(i["file_sha256"] for i in info),
                                "retrieved_at": common.now()[:10]})
    # Größe g-Faktor ggf. ergänzen
    qp = root / "quantities.json"
    qs = read_file(qp)[1]
    if not any(q.get("quantity") == "g_factor_westcott" for q in qs):
        qs.append({"quantity": "g_factor_westcott", "unit": "1", "dtype": "real",
                   "description": "Westcott-g-Faktor (Abweichung vom 1/v-Verhalten, thermische Neutronen)"})
        write_file(qp, "quantities", qs)

    prompt = parse_lines(paths["prompt"], kind="prompt")
    activation = parse_lines(paths["activation"], kind="activation")
    iso_vals = parse_isotopes(paths["isotopes"])
    known = {r["name"] for r in read_file(root / "nuclides.json")[1]}
    iso_vals = {k: v for k, v in iso_vals.items() if k in known}

    n_p = common.replace_records(root, "prompt_gamma", SOURCE, prompt)
    n_a = common.replace_records(root, "activation_gamma", SOURCE, activation)
    _c, n_v = common.replace_nuclide_data(root, SOURCE, {}, iso_vals)

    # Elemente: Werte mit Quellenangabe je Feld
    ep = root / "elements.json"
    els = read_file(ep)[1]
    data = parse_elements(paths["elements"])
    for r in els:
        d = data.get(r.get("z"))
        # Werte eines früheren PGAA-Imports entfernen, andere Quellen bleiben unangetastet
        if r.get("atomic_weight_source") == SOURCE:
            for k in ("atomic_weight_u", "atomic_weight_u_unc", "atomic_weight_text", "atomic_weight_source"):
                r.pop(k, None)
        if r.get("sigma_capture_source") == SOURCE:
            for k in ("sigma_capture_b", "sigma_capture_b_unc", "sigma_capture_text", "sigma_capture_source"):
                r.pop(k, None)
        if d and d["atomic_weight_u"] is not None and "atomic_weight_u" not in r:
            r.update({k: d[k] for k in ("atomic_weight_u", "atomic_weight_u_unc", "atomic_weight_text")})
            r["atomic_weight_source"] = SOURCE
        if d and d["sigma_capture_b"] is not None and "sigma_capture_b" not in r:
            r.update({k: d[k] for k in ("sigma_capture_b", "sigma_capture_b_unc", "sigma_capture_text")})
            r["sigma_capture_source"] = SOURCE
    write_file(ep, "elements", els)

    summary = (f"PGAA-Excel (lokal): {n_p} Prompt-Gammas, {n_a} Aktivierungslinien, {n_v} Isotopenwerte, "
               f"{len(data)} Elemente")
    common.log_import(root, SOURCE, summary)
    return {"summary": summary}
