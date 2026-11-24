"""Pflege der zentralen Datenbank: Grundgerüst erzeugen, Manifest aktualisieren.

Wird vom Editor, von den Importern und von ``nucdb manifest`` verwendet, nicht von Konsumenten.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from . import elements, schema
from .fileformat import atomic_write_text, read_file, read_json, sha256_of, write_file
from .locate import MANIFEST
from .physics import ELECTRON_MASS_KEV, PAIR_THRESHOLD_KEV

BUILTIN_SOURCE = "NucDB"

#: Quellen, die schon das Grundgerüst braucht
BASE_SOURCES = [
    {
        "key": BUILTIN_SOURCE,
        "title": "NucDB – feste Definitionen (Elementnamen, abgeleitete Sonderlinien)",
        "publisher": "NucDB-Projekt", "url": "https://github.com/symbio-n0mad/NucDB",
        "license": "CC-BY-4.0", "redistributable": True,
        "citation": "NucDB, https://github.com/symbio-n0mad/NucDB",
    },
    {
        "key": "CODATA2018",
        "title": "CODATA Recommended Values of the Fundamental Physical Constants: 2018",
        "authors": "E. Tiesinga, P. J. Mohr, D. B. Newell, B. N. Taylor",
        "publisher": "Rev. Mod. Phys. 93, 025010 (2021)", "year": 2021,
        "doi": "10.1103/RevModPhys.93.025010", "url": "https://physics.nist.gov/cuu/Constants/",
        "license": "Fakten, frei zitierbar", "redistributable": True,
        "citation": "E. Tiesinga et al., CODATA Recommended Values of the Fundamental Physical "
                    "Constants: 2018, Rev. Mod. Phys. 93, 025010 (2021)",
    },
    {
        "key": "XDB2009",
        "title": "X-Ray Data Booklet, 3rd edition, Table 1-2 (Photon energies of principal K-, L- and "
                 "M-shell emission lines)",
        "authors": "A. C. Thompson et al.", "publisher": "Lawrence Berkeley National Laboratory",
        "year": 2009, "url": "https://xdb.lbl.gov/", "license": "Fakten, frei zitierbar",
        "redistributable": True,
        "citation": "A. C. Thompson et al., X-Ray Data Booklet, 3rd ed., LBNL (2009)",
    },
]

#: Anfangsbestand der skalaren Größen (Spezifikation 4.3)
BASE_QUANTITIES = [
    ("mass_u", "u", "real", "Atommasse (inkl. Elektronen)"),
    ("mass_excess_kev", "keV", "real", "Massenexzess (M − A·u)·c²"),
    ("binding_energy_per_nucleon_kev", "keV", "real", "Bindungsenergie pro Nukleon"),
    ("half_life_s", "s", "real", "Halbwertszeit"),
    ("level_energy_kev", "keV", "real", "Anregungsenergie (Isomere)"),
    ("spin_parity", "", "text", "Spin und Parität, z. B. '5+'"),
    ("abundance_percent", "%", "real", "Natürliche Isotopenhäufigkeit (Atomprozent)"),
    ("sigma_capture_b", "b", "real", "Thermischer Neutroneneinfangquerschnitt (2200 m/s)"),
    ("resonance_integral_b", "b", "real", "Resonanzintegral für Neutroneneinfang"),
    ("q_beta_minus_kev", "keV", "real", "Q-Wert des β⁻-Zerfalls"),
    ("q_alpha_kev", "keV", "real", "Q-Wert des α-Zerfalls"),
    ("q_ec_kev", "keV", "real", "Q-Wert des Elektroneneinfangs"),
]

#: Sonderlinien (Spezifikation 4.8). Pb-Röntgenenergien aus dem X-Ray Data Booklet.
BASE_SPECIAL_LINES = [
    {"kind": "annihilation", "energy_kev": ELECTRON_MASS_KEV, "source": "CODATA2018",
     "description": "Vernichtungsstrahlung (m_e c²); im Spektrum durch Doppler-Effekt verbreitert"},
    {"kind": "sum", "energy_kev": PAIR_THRESHOLD_KEV, "source": "CODATA2018",
     "description": "Summenpeak 2 × 511 keV (beide Vernichtungsquanten im Detektor)"},
    {"kind": "single_escape", "offset_kev": -ELECTRON_MASS_KEV, "source": "CODATA2018",
     "description": "Single-Escape-Peak E − 511 keV (nur für E > 1022 keV)"},
    {"kind": "double_escape", "offset_kev": -PAIR_THRESHOLD_KEV, "source": "CODATA2018",
     "description": "Double-Escape-Peak E − 1022 keV (nur für E > 1022 keV)"},
    {"kind": "xray_fluorescence", "energy_kev": 72.8042, "origin": "Pb", "xray_line": "Ka2",
     "source": "XDB2009", "description": "Pb Kα2 – Röntgenfluoreszenz der Bleiabschirmung"},
    {"kind": "xray_fluorescence", "energy_kev": 74.9694, "origin": "Pb", "xray_line": "Ka1",
     "source": "XDB2009", "description": "Pb Kα1 – Röntgenfluoreszenz der Bleiabschirmung"},
    {"kind": "xray_fluorescence", "energy_kev": 84.936, "origin": "Pb", "xray_line": "Kb1",
     "source": "XDB2009", "description": "Pb Kβ1 – Röntgenfluoreszenz der Bleiabschirmung"},
    {"kind": "backscatter", "source": BUILTIN_SOURCE,
     "description": "Rückstreupeak E / (1 + 2E/m_e c²), berechnet mit nucdb.physics.backscatter"},
    {"kind": "compton_edge", "source": BUILTIN_SOURCE,
     "description": "Compton-Kante 2E² / (m_e c² + 2E), berechnet mit nucdb.physics.compton_edge"},
]


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def create_base(root: str | Path, *, data_version: str | None = None) -> Path:
    """Grundgerüst einer Datenbank erzeugen bzw. die festen Teile darin auffrischen.

    Schreibt Quellen, Größen, Elemente (Namen) und Sonderlinien. Vorhandene Datensätze anderer
    Quellen (z. B. aus Importern) bleiben erhalten.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    def merge(name: str, new: list[dict], key) -> None:
        p = root / f"{name}.json"
        old = read_file(p)[1] if p.is_file() else []
        new_keys = {key(r) for r in new}
        write_file(p, name, [r for r in old if key(r) not in new_keys] + new)

    merge("sources", BASE_SOURCES, lambda r: r.get("key"))
    merge("quantities", [{"quantity": q, "unit": u, "dtype": t, "description": d}
                         for q, u, t, d in BASE_QUANTITIES], lambda r: r.get("quantity"))
    # Elemente: Namen aus der festen Tabelle, vorhandene Messwerte (Atomgewichte …) bleiben
    p = root / "elements.json"
    old = {r.get("z"): r for r in (read_file(p)[1] if p.is_file() else [])}
    els = []
    for z, sym, en, de in elements.all_elements():
        rec = dict(old.get(z, {}))
        rec.update({"z": z, "symbol": sym, "name_en": en, "name_de": de})
        rec.setdefault("source", BUILTIN_SOURCE)
        els.append(rec)
    write_file(p, "elements", els)
    # Sonderlinien gehören komplett dem Grundgerüst
    write_file(root / "special_lines.json", "special_lines", BASE_SPECIAL_LINES)
    for name in ("nuclides", "decay_modes", "decay_gamma", "decay_alpha", "decay_beta", "decay_electron",
                 "prompt_gamma", "activation_gamma", "isomer_feeding", "changelog"):
        if not (root / f"{name}.json").is_file():
            write_file(root / f"{name}.json", name, [])
    update_manifest(root, data_version=data_version)
    return root


def update_manifest(root: str | Path, *, data_version: str | None = None, **extra) -> dict:
    """Prüfsummen und Datensatzzahlen aller Dateien ins Manifest schreiben."""
    root = Path(root)
    mp = root / MANIFEST
    manifest = read_json(mp) if mp.is_file() else {}
    manifest.update({"format": "nucdb/manifest", "schema_version": schema.SCHEMA_VERSION})
    manifest.setdefault("license", "CC-BY-4.0")
    manifest["import"] = {"min_intensity": 0.001, "min_intensity_sources": ["ENSDF-LiveChart"],
                          "min_half_life_s": 1}
    manifest.setdefault("source_priority", ["DDEP", "ENSDF-LiveChart", "NUBASE2020", "AME2020"])
    if data_version:
        manifest["data_version"] = data_version
    manifest.setdefault("data_version", _dt.date.today().strftime("%Y.%m.0"))
    manifest.update(extra)
    files = {}
    for p in sorted(root.glob("*.json")):
        if p.name == MANIFEST:
            continue
        try:
            n = len(read_file(p)[1])
        except Exception:  # noqa: BLE001 - Manifest soll trotzdem entstehen; validate meldet den Fehler
            n = None
        files[p.name] = {"sha256": sha256_of(p), "records": n}
    manifest["files"] = files
    manifest["created_at"] = _now()
    atomic_write_text(mp, json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
    return manifest


#: Reihenfolge der Importer beim vollständigen Aufbau: (Name, Modul, Unterordner der Rohdaten)
BUILD_STEPS = [
    ("amdc2020", "nucdb.importers.amdc2020", "amdc2020"),
    ("ddep", "nucdb.importers.ddep", "ddep"),
    ("livechart", "nucdb.importers.livechart", "livechart"),
]


#: Zusätzliche Schritte nur für lokale Datenbanken (Quellen mit redistributable: false)
LOCAL_STEPS = [
    ("pgaa", "nucdb.importers.pgaa_xls", "."),
]


def build_all(root: str | Path, src_root: str | Path, *, data_version: str | None = None,
              download: bool = False, local: bool = False, curation: str | Path | None = None,
              log=print) -> None:
    """Datenbank vollständig neu aus den Rohdaten aufbauen (Grundgerüst + alle Importer).

    Der Zielordner wird zuerst geleert (nur ``*.json``), damit keine Reste alter Importe bleiben.
    Mit ``local=True`` kommen die nicht weitergebbaren Quellen dazu (PGAA-Excel). Eine solche
    Datenbank darf nicht nach ``src/nucdb/data`` und nicht ins Repository.
    Zum Schluss wird der Kurationsordner ``curation`` (Korrekturen aus dem Editor) angewandt; in
    eine weitergebbare Datenbank nur Einträge aus weitergebbaren Quellen.
    """
    root = Path(root)
    if local and root.resolve() == (Path(__file__).parent / "data").resolve():
        raise ValueError("Eine lokale Datenbank (mit nicht weitergebbaren Quellen) darf nicht in "
                         "die mitgelieferte Momentaufnahme src/nucdb/data gebaut werden")
    import importlib
    root, src_root = Path(root), Path(src_root)
    root.mkdir(parents=True, exist_ok=True)
    for p in root.glob("*.json"):
        p.unlink()
    create_base(root, data_version=data_version)
    for name, module, sub in BUILD_STEPS + (LOCAL_STEPS if local else []):
        mod = importlib.import_module(module)
        src = src_root / sub
        if download and name != "pgaa":
            if name == "livechart":
                from .importers import livechart_fetch
                livechart_fetch.main(["--db", str(root), "--out", str(src)])
            else:
                mod.fetch(src)
        res = mod.run(root, src)
        log(res["summary"])
    if curation is not None and Path(curation).is_dir():
        from .curation import apply
        counts = apply(curation, root, distributable=not local)
        log(f"Kuration {curation}: " + (", ".join(f"{k} {v}" for k, v in counts.items()) or "nichts zu tun"))
    update_manifest(root, data_version=data_version)
