"""Importer für AME2020 (Atommassen) und NUBASE2020 (Halbwertszeiten, Isomere, Zerfallsarten).

Quelldateien (Atomic Mass Data Center, Spiegel bei der IAEA):

* ``mass_1.mas20.txt`` – Massenexzess, Bindungsenergie/A, β⁻-Zerfallsenergie, Atommasse
* ``rct1.mas20.txt``   – u. a. Q(α)
* ``nubase_4.mas20.txt`` – Halbwertszeiten, Isomere, Spin/Parität, Häufigkeiten, Zerfallsarten

Konventionen beim Import:

* ``#`` statt Dezimalpunkt = Wert aus Systematik → ``flag: "sys"``; ``*`` = nicht berechenbar → weggelassen.
* NUBASE-Halbwertszeiten werden mit 1 y = 365.2422 d umgerechnet (Definition von NUBASE).
  Grenzwerte (``>``, ``<``, ``~``) erhalten das entsprechende ``flag``.
* Isomere: Als eigene Nuklide gelten angeregte Zustände mit T½ ≥ 1 ms (``ISOMER_MIN_HALF_LIFE_S``).
  Sie werden in NUBASE-Reihenfolge (nach Energie) durchgezählt: ``m``, ``m2``, ``m3`` …
  So entstehen die üblichen Namen (Ag-110m = 250 d, Lu-177m = 160 d, Kr-83m = 1,8 h); NUBASE zählt
  dagegen auch Zustände im ns-Bereich mit. Der NUBASE-Buchstabe steht im Feld ``nubase_state``.
  Kürzerlebige Zustände, Zustände ohne Halbwertszeit, IAS und Resonanzen entfallen.
* Zerfallsarten in NUBASE-Schreibweise. Verzweigungen in % werden als Bruchteil gespeichert.
  Teilzweige wie ``B-n`` (β⁻ mit anschließender Neutronenemission) bekommen ``parent_mode``;
  sie sind im Hauptzweig enthalten (Spezifikation 4.6).
* Als widerlegt markierte Zustände (``non-exist``) werden nicht übernommen.
* IT führt zum Grundzustand desselben Nuklids (NUBASE nennt den Zielzustand nicht).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .. import elements, units
from . import common

SOURCE_AME = "AME2020"
SOURCE_NUBASE = "NUBASE2020"
BASE_URL = "https://www-nds.iaea.org/amdc/ame2020/"
FILES = {"mass": "mass_1.mas20.txt", "rct1": "rct1.mas20.txt", "nubase": "nubase_4.mas20.txt"}

SOURCE_RECORDS = {
    SOURCE_AME: {
        "key": SOURCE_AME,
        "title": "The Ame2020 atomic mass evaluation (I) and (II)",
        "authors": "W. J. Huang, M. Wang, F. G. Kondev, G. Audi, S. Naimi",
        "publisher": "Chinese Physics C 45, 030002 und 030003 (2021)", "year": 2021,
        "doi": "10.1088/1674-1137/abddb0", "url": "https://www-nds.iaea.org/amdc/",
        "license": "Artikel Open Access (CC BY 3.0); Datendateien frei verfügbar, Zitat erforderlich",
        "redistributable": True,
        "citation": "W. J. Huang et al., Chin. Phys. C 45, 030002 (2021); M. Wang et al., "
                    "Chin. Phys. C 45, 030003 (2021)",
    },
    SOURCE_NUBASE: {
        "key": SOURCE_NUBASE,
        "title": "The NUBASE2020 evaluation of nuclear physics properties",
        "authors": "F. G. Kondev, M. Wang, W. J. Huang, S. Naimi, G. Audi",
        "publisher": "Chinese Physics C 45, 030001 (2021)", "year": 2021,
        "doi": "10.1088/1674-1137/abddae", "url": "https://www-nds.iaea.org/amdc/",
        "license": "Artikel Open Access (CC BY 3.0); Datendateien frei verfügbar, Zitat erforderlich",
        "redistributable": True,
        "citation": "F. G. Kondev et al., Chin. Phys. C 45, 030001 (2021)",
        "notes": "Jahr = 365.2422 d. Isomere: Zustände mit T½ ≥ 1 ms, nach Energie gezählt (m, m2 …).",
    },
}

YEAR_S = units.YEAR_S
_T_UNITS = {
    "ys": 1e-24, "zs": 1e-21, "as": 1e-18, "fs": 1e-15, "ps": 1e-12, "ns": 1e-9, "us": 1e-6,
    "ms": 1e-3, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0, "y": YEAR_S, "ky": 1e3 * YEAR_S,
    "My": 1e6 * YEAR_S, "Gy": 1e9 * YEAR_S, "Ty": 1e12 * YEAR_S, "Py": 1e15 * YEAR_S,
    "Ey": 1e18 * YEAR_S, "Zy": 1e21 * YEAR_S, "Yy": 1e24 * YEAR_S,
}

# Zerfallsart -> (ΔZ, ΔA) zur Tochter; None = keine eindeutige Tochter
_DELTA: dict[str, tuple[int, int] | None] = {
    "B-": (1, 0), "2B-": (2, 0), "B+": (-1, 0), "EC": (-1, 0), "e+": (-1, 0), "EC+B+": (-1, 0),
    "2B+": (-2, 0), "A": (-2, -4), "IT": (0, 0), "p": (-1, -1), "2p": (-2, -2), "3p": (-3, -3),
    "n": (0, -1), "2n": (0, -2), "3n": (0, -3), "d": (-1, -2), "3H": (-1, -3), "3He": (-2, -3),
    "B-n": (1, -1), "B-2n": (1, -2), "B-3n": (1, -3), "B-4n": (1, -4), "B-p": (0, -1), "B-A": (-1, -4),
    "B-d": (0, -2), "B-t": (0, -3), "B+p": (-2, -1), "B+2p": (-3, -2), "B+3p": (-4, -3), "B+A": (-3, -4),
    "B+pA": (-4, -5), "SF": None, "B-SF": None, "B+SF": None,
}
_CLUSTER = re.compile(r"^(\d+)([A-Z][a-z]?)$")


@dataclass
class Num:
    value: float
    unc: float | None
    flag: str | None
    text: str


def _num(s: str, unc: str = "") -> Num | None:
    """AME/NUBASE-Zahl: ``#`` statt Punkt = Systematik, ``*`` oder leer = kein Wert."""
    t = s.strip()
    if not t or t == "*":
        return None
    flag = "sys" if "#" in t else None
    try:
        v = float(t.replace("#", "."))
    except ValueError:                              # z. B. "non-exist"
        return None
    u = unc.strip()
    uv = None
    if u and u != "*":
        try:
            uv = float(u.replace("#", "."))
        except ValueError:
            uv = None
    return Num(v, uv, flag, (t + (" " + u if u else "")).strip())


def _scale(x: float, scale: float | str) -> float:
    """Dezimal skalieren, damit kein Rundungsrauschen entsteht (222.017576017, nicht …6999998)."""
    return float(Decimal(repr(x)) * Decimal(str(scale)))


def _val(n: Num, scale: float = 1.0) -> dict:
    d = {"value": _scale(n.value, scale), "unc": None if n.unc is None else _scale(n.unc, scale)}
    if n.flag:
        d["flag"] = n.flag
    return d


# ---------------------------------------------------------------------------------------------
# AME2020
# ---------------------------------------------------------------------------------------------

def parse_ame_mass(path: Path) -> dict[tuple[int, int], dict]:
    """``mass_1.mas20`` → {(Z, A): {mass_excess, binding, qbeta, mass_u}}."""
    out: dict[tuple[int, int], dict] = {}
    started = False
    for line in Path(path).read_text(encoding="latin-1").splitlines():
        if line.startswith("1N-Z"):
            started = True
            continue
        if not started or len(line) < 110:
            continue
        try:
            z, a = int(line[9:14]), int(line[14:19])
        except ValueError:
            continue
        rec = {"me": _num(line[28:42], line[42:54]), "ba": _num(line[54:67], line[68:78]),
               "qb": _num(line[81:94], line[94:105])}
        mi, mf = line[106:109].strip(), line[110:123].strip()
        if mi and mf and mf != "*":
            mu = _num(mi + mf, line[123:135])          # Mikro-u: "59" + "933815.536"
            if mu:
                rec["mass"] = Num(_scale(mu.value, "1e-6"), None if mu.unc is None else _scale(mu.unc, "1e-6"),
                                  mu.flag, f"{mi} {mf} µu")
        out[(z, a)] = rec
    return out


def parse_ame_rct1(path: Path) -> dict[tuple[int, int], dict]:
    """``rct1.mas20`` → {(Z, A): {qa: Num}} (weitere Spalten bei Bedarf ergänzen)."""
    out: dict[tuple[int, int], dict] = {}
    for line in Path(path).read_text(encoding="latin-1").splitlines():
        if len(line) < 80 or line[0] not in " 0":
            continue
        try:
            a, z = int(line[1:4]), int(line[8:11])
        except ValueError:
            continue
        out[(z, a)] = {"qa": _num(line[56:68], line[68:78])}
    return out


# ---------------------------------------------------------------------------------------------
# NUBASE2020
# ---------------------------------------------------------------------------------------------

@dataclass
class NubaseEntry:
    z: int
    a: int
    state: int
    s: str
    mass_excess: Num | None
    excitation: Num | None
    half_life: dict | None          # Wert-Objekt in s (mit flag/text) oder None
    stable: bool
    jpi: dict | None
    discovery: int | None
    modes: list[dict]
    abundance: dict | None
    order_uncertain: bool
    nonexistent: bool = False       # in NUBASE als widerlegt markiert ("non-exist")


_MODE_TOKEN = re.compile(
    r"^(?P<mode>.+?)\s*(?P<rel>[=~<>?])\s*(?P<val>[\d.]+(?:[eE][+-]?\d+)?#?)?\s*(?P<unc>\S+)?$")


def _last_digit_unc(value_text: str, unc_text: str | None) -> float | None:
    """NUBASE-Unsicherheit in Einheiten der letzten Stellen: ``16 1`` → 1, ``0.000278 18`` → 1.8e-5."""
    if not unc_text or not unc_text.rstrip("#").isdigit():
        return None
    mant, _, exp = value_text.rstrip("#").lower().partition("e")
    dec = len(mant.split(".", 1)[1]) if "." in mant else 0
    return float(Decimal(int(unc_text.rstrip("#"))).scaleb((int(exp) if exp else 0) - dec))


def _parse_half_life(t: str, unit: str, dt: str) -> tuple[dict | None, bool]:
    t, unit, dt = t.strip(), unit.strip(), dt.strip()
    if t == "stbl":
        return None, True
    if t in ("", "p-unst"):
        # Grenzwert steht manchmal im Unsicherheitsfeld, z. B. ">300ns"
        m = re.fullmatch(r"([<>~])\s*([\d.]+#?)\s*([a-zA-Z]+)", dt)
        if m and m.group(3) in _T_UNITS:
            v = float(m.group(2).replace("#", "")) * _T_UNITS[m.group(3)]
            return {"value": v, "flag": m.group(1), "text": dt}, False
        return None, False
    flag = None
    if t[0] in "<>~":
        flag, t = t[0], t[1:].strip()
    if "#" in t:
        flag = flag or "sys"
    if unit not in _T_UNITS:
        return None, False
    f = _T_UNITS[unit]
    v = float(t.replace("#", "")) * f
    unc = None
    if dt and re.fullmatch(r"[\d.]+#?", dt):
        unc = float(dt.replace("#", "")) * f
    text = f"{'' if flag in (None, 'sys') else flag}{t} {unit}" + (f" {dt}" if dt else "")
    d = {"value": v, "unc": unc, "text": text}
    if flag:
        d["flag"] = flag
    return d, False


def _parse_jpi(s: str) -> dict | None:
    tok = s.split("T=")[0].strip().split()
    tok = [x for x in tok if x != "frg"]
    if not tok:
        return None
    raw = tok[0]
    clean = raw.replace("*", "").replace("#", "")
    if not clean:
        return None
    d = {"value": clean, "text": raw}
    if "#" in raw:
        d["flag"] = "sys"
    return d


def _parse_modes(br: str) -> tuple[list[dict], dict | None]:
    modes: list[dict] = []
    abundance = None
    for tok in br.split(";"):
        tok = tok.strip()
        if not tok:
            continue
        m = _MODE_TOKEN.match(tok)
        if not m:
            continue
        mode, rel, val, unc = m.group("mode").strip(), m.group("rel"), m.group("val"), m.group("unc")
        if mode == "B":                             # Schreibfehler in NUBASE2020 (Pd-126m3)
            mode = "B-"
        if mode == "IS":
            if val:
                abundance = {"value": float(val.rstrip("#")), "unc": _last_digit_unc(val, unc), "text": tok}
            continue
        rec: dict = {"mode": mode, "text": tok}
        if rel == "?" or val is None:
            rec["branching_flag"] = "?"
        else:
            rec["branching"] = _scale(float(val.rstrip("#")), "0.01")
            u = _last_digit_unc(val, unc)
            rec["branching_unc"] = None if u is None else _scale(u, "0.01")
            if rel != "=":
                rec["branching_flag"] = rel
            elif val.endswith("#"):
                rec["branching_flag"] = "sys"
        modes.append(rec)
    return modes, abundance


def parse_nubase(path: Path) -> list[NubaseEntry]:
    out: list[NubaseEntry] = []
    for line in Path(path).read_text(encoding="latin-1").splitlines():
        if line.startswith("#") or len(line) < 20:
            continue
        line = line.ljust(209)
        try:
            a, z, state = int(line[0:3]), int(line[4:7]), int(line[7])
        except ValueError:
            continue
        hl, stable = _parse_half_life(line[69:78], line[78:80], line[81:88])
        modes, abundance = _parse_modes(line[119:])
        disc = line[114:118].strip()
        out.append(NubaseEntry(
            z=z, a=a, state=state, s=line[16].strip(),
            mass_excess=_num(line[18:31], line[31:42]), excitation=_num(line[42:54], line[54:65]),
            half_life=hl, stable=stable, jpi=_parse_jpi(line[88:102]),
            discovery=int(disc) if disc.isdigit() else None, modes=modes, abundance=abundance,
            order_uncertain=line[67] == "*", nonexistent="non-exist" in line[18:65]))
    return out


#: Mindest-Halbwertszeit, ab der ein angeregter Zustand als eigenes Nuklid (Isomer) geführt wird
ISOMER_MIN_HALF_LIFE_S = 1e-3


def _include(e: NubaseEntry) -> bool:
    if e.nonexistent:
        return False
    if e.state == 0:
        return True
    if 1 <= e.state <= 6 and e.stable:
        return True                                 # z. B. Ta-180m (bisher kein Zerfall beobachtet)
    if not 1 <= e.state <= 6 or e.half_life is None:
        return False                                # IAS, Resonanzen, Niveaus ohne T½
    if e.half_life.get("flag") == "<":
        return e.half_life["value"] >= ISOMER_MIN_HALF_LIFE_S * 10  # "< 85 ms" o. ä. nur wenn deutlich lang
    return e.half_life["value"] >= ISOMER_MIN_HALF_LIFE_S


def _number_isomers(entries: list[NubaseEntry]) -> dict[int, int]:
    """id(entry) → Isomernummer (0 = Grundzustand, dann 1, 2 … in NUBASE-Reihenfolge)."""
    out: dict[int, int] = {}
    count: dict[tuple[int, int], int] = {}
    for e in entries:
        if e.state == 0:
            out[id(e)] = 0
        else:
            k = (e.z, e.a)
            count[k] = count.get(k, 0) + 1
            out[id(e)] = count[k]
    return out


def _daughter(z: int, a: int, mode: str) -> str | None:
    if mode in _DELTA:
        d = _DELTA[mode]
        if d is None:
            return None
        dz, da = d
    else:
        m = _CLUSTER.match(mode)
        if not m:
            return None                            # z. B. kombinierte Clusterzerfälle "24Ne+26Ne"
        try:
            dz, da = -elements.z_of(m.group(2), strict_case=True), -int(m.group(1))
        except KeyError:
            return None
    zz, aa = z + dz, a + da
    if zz < 0 or aa < 1 or aa < zz:
        return None
    return common.nuclide_name(zz, aa, 0)


def _parent_mode(mode: str, present: dict[str, float | None]) -> str | None:
    """Hauptzweig eines Teilzweigs. ``present``: Zerfallsart → Verzweigung dieses Nuklids.

    EC bzw. e+ sind nur dann Teil von B+, wenn B+ schon (fast) alles umfasst, z. B.
    ``B+=100;EC=60``. Bei ``EC=61;B+=39`` sind es getrennte Zweige.
    """
    if mode.startswith("B-") and mode != "B-":
        return "B-"
    if mode.startswith("B+") and mode != "B+":
        return "B+"
    if mode in ("EC", "e+") and "B+" in present:
        bp, own = present.get("B+"), present.get(mode)
        if bp is not None and own is not None and bp + own > 1.011:
            return "B+"
    return None


# ---------------------------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------------------------

def fetch(src_dir: Path) -> None:
    """Fehlende Quelldateien herunterladen."""
    for fname in FILES.values():
        p = Path(src_dir) / fname
        if not p.is_file():
            common.download(BASE_URL + fname, p)


def run(root: Path, src_dir: Path) -> dict:
    """AME2020 und NUBASE2020 aus ``src_dir`` in die Datenbank ``root`` importieren."""
    root, src_dir = Path(root), Path(src_dir)
    paths = {k: src_dir / v for k, v in FILES.items()}
    for k, p in paths.items():
        if not p.is_file():
            raise FileNotFoundError(f"Quelldatei fehlt: {p} (mit --download holen)")
    ame = parse_ame_mass(paths["mass"])
    rct1 = parse_ame_rct1(paths["rct1"])
    nub = [e for e in parse_nubase(paths["nubase"]) if _include(e)]
    iso_no = _number_isomers(nub)

    # --- Nuklide und NUBASE-Werte ------------------------------------------------------------
    meta: dict[str, dict] = {}
    nvals: dict[str, dict[str, list[dict]]] = {}
    modes_out: list[dict] = []
    for e in nub:
        if e.z > elements.MAX_Z:
            continue
        iso = iso_no[id(e)]
        name = common.nuclide_name(e.z, e.a, iso)
        m = {"z": e.z, "a": e.a, "isomer": iso, "stable": e.stable}
        if e.state:
            m["nubase_state"] = e.s
        if e.discovery:
            m["discovery_year"] = e.discovery
        if e.order_uncertain:
            m["isomer_order_uncertain"] = True
        meta[name] = m
        v: dict[str, list[dict]] = {}
        if e.half_life:
            v["half_life_s"] = [e.half_life]
        if e.jpi:
            v["spin_parity"] = [e.jpi]
        if e.abundance:
            v["abundance_percent"] = [e.abundance]
        if e.state > 0:
            if e.excitation:
                v["level_energy_kev"] = [_val(e.excitation)]
            if e.mass_excess:
                v["mass_excess_kev"] = [_val(e.mass_excess)]
        elif e.mass_excess and (e.z, e.a) not in ame:
            v["mass_excess_kev"] = [_val(e.mass_excess)]
        if v:
            nvals[name] = v
        present = {md["mode"]: md.get("branching") for md in e.modes}
        for md in e.modes:
            rec = {"parent": name, "mode": md["mode"], "daughter": _daughter(e.z, e.a, md["mode"]),
                   "branching": md.get("branching"), "branching_unc": md.get("branching_unc"),
                   "branching_flag": md.get("branching_flag"), "text": md["text"],
                   "parent_mode": _parent_mode(md["mode"], present)}
            if md["mode"] == "IT" and e.state == 0:
                rec["daughter"] = None                 # IT aus dem Grundzustand: Ziel unbekannt
            modes_out.append(rec)

    # --- AME2020-Werte (Grundzustände) -------------------------------------------------------
    avals: dict[str, dict[str, list[dict]]] = {}
    for (z, a), r in ame.items():
        if z > elements.MAX_Z:
            continue
        name = common.nuclide_name(z, a, 0)
        if name not in meta:
            meta[name] = {"z": z, "a": a, "isomer": 0}
        v = {}
        if r.get("me"):
            v["mass_excess_kev"] = [_val(r["me"])]
        if r.get("mass"):
            v["mass_u"] = [_val(r["mass"])]
        if r.get("ba") and a > 1:
            v["binding_energy_per_nucleon_kev"] = [_val(r["ba"])]
        if r.get("qb"):
            v["q_beta_minus_kev"] = [_val(r["qb"])]
        # Q(EC) von (Z, A) = −Q(β⁻) von (Z−1, A)
        prev = ame.get((z - 1, a), {}).get("qb")
        if prev:
            v["q_ec_kev"] = [{"value": -prev.value, "unc": prev.unc, **({"flag": prev.flag} if prev.flag else {})}]
        qa = rct1.get((z, a), {}).get("qa")
        if qa:
            v["q_alpha_kev"] = [_val(qa)]
        if v:
            avals[name] = v

    # --- Schreiben ---------------------------------------------------------------------------
    for key, rec in SOURCE_RECORDS.items():
        info = {}
        for k, fname in FILES.items():
            if (key == SOURCE_AME) == (k != "nubase"):
                info.setdefault("file_name", [])
                info.setdefault("file_sha256", [])
                fi = common.file_info(paths[k])
                info["file_name"].append(fi["file_name"])
                info["file_sha256"].append(fi["file_sha256"])
        common.upsert_source(root, {**rec, "file_name": ", ".join(info["file_name"]),
                                    "file_sha256": ", ".join(info["file_sha256"]),
                                    "retrieved_at": common.now()[:10]})
    created, n_nub = common.replace_nuclide_data(root, SOURCE_NUBASE, meta, nvals)
    _c2, n_ame = common.replace_nuclide_data(root, SOURCE_AME, {}, avals)
    n_modes = common.replace_records(root, "decay_modes", SOURCE_NUBASE, modes_out)
    summary = (f"{len(meta)} Nuklide ({created} neu), {n_nub} NUBASE-Werte, {n_ame} AME-Werte, "
               f"{n_modes} Zerfallsarten")
    common.log_import(root, "AME2020+NUBASE2020", summary)
    return {"nuclides": len(meta), "created": created, "nubase_values": n_nub, "ame_values": n_ame,
            "decay_modes": n_modes, "summary": summary}
