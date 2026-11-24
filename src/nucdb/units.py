"""Einheiten: umrechnen, Eingaben lesen, Werte anzeigen (Spezifikation Abschnitt 6a).

In der Datenbank steht jede Größe in genau einer Basiseinheit:

=================  =========
Größenart (kind)   Basis
=================  =========
time               s
decay_constant     1/s
energy             keV
mass               u
cross_section      b
fraction           Bruchteil (1)
=================  =========

Alle Tools rechnen ausschließlich über dieses Modul um. Es braucht nur die Standardbibliothek.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .physics import ATOMIC_MASS_UNIT_KEV, ATOMIC_MASS_UNIT_KG

# ---------------------------------------------------------------------------------------------
# Festgelegte Definitionen
# ---------------------------------------------------------------------------------------------

DAY_S = 86_400.0
#: Tropisches Jahr, gerundet, wie in NUBASE2020: 1 a = 365.2422 d (= 31 556 926.08 s).
YEAR_DAYS = 365.2422
YEAR_S = YEAR_DAYS * DAY_S
#: Julianisches Jahr (Astronomie). Nur für Importe aus Quellen, die so rechnen.
JULIAN_YEAR_S = 365.25 * DAY_S

LN2 = math.log(2.0)


class UnitError(ValueError):
    """Unbekannte oder unpassende Einheit bzw. nicht lesbare Eingabe."""


# ---------------------------------------------------------------------------------------------
# Einheitentabellen: Symbol -> Faktor zur Basiseinheit
# ---------------------------------------------------------------------------------------------

_TIME = {
    "fs": 1e-15, "ps": 1e-12, "ns": 1e-9, "µs": 1e-6, "ms": 1e-3, "s": 1.0,
    "min": 60.0, "h": 3600.0, "d": DAY_S, "a": YEAR_S,
}
_TIME_ALIASES = {
    "us": "µs", "μs": "µs",  # u und griechisches My statt Mikrozeichen
    "sec": "s", "Sekunde": "s", "Sekunden": "s", "second": "s", "seconds": "s",
    "Minute": "min", "Minuten": "min", "minute": "min", "minutes": "min", "mins": "min",
    "Std": "h", "Stunde": "h", "Stunden": "h", "hour": "h", "hours": "h", "hr": "h",
    "Tag": "d", "Tage": "d", "day": "d", "days": "d",
    "y": "a", "yr": "a", "yrs": "a", "Jahr": "a", "Jahre": "a", "year": "a", "years": "a",
}

_ENERGY = {"eV": 1e-3, "keV": 1.0, "MeV": 1e3, "GeV": 1e6}
_MASS = {
    "u": 1.0,
    "keV/c²": 1.0 / ATOMIC_MASS_UNIT_KEV,
    "MeV/c²": 1e3 / ATOMIC_MASS_UNIT_KEV,
    "kg": 1.0 / ATOMIC_MASS_UNIT_KG,
}
_MASS_ALIASES = {"Da": "u", "amu": "u", "keV/c2": "keV/c²", "keV/c^2": "keV/c²",
                 "MeV/c2": "MeV/c²", "MeV/c^2": "MeV/c²"}
_XS = {"µb": 1e-6, "mb": 1e-3, "b": 1.0, "fm²": 1e-2, "cm²": 1e24}
_XS_ALIASES = {"ub": "µb", "μb": "µb", "barn": "b", "fm2": "fm²", "fm^2": "fm²",
               "cm2": "cm²", "cm^2": "cm²"}
_FRACTION = {"1": 1.0, "%": 1e-2, "‰": 1e-3, "ppm": 1e-6}
_FRACTION_ALIASES = {"": "1", "Prozent": "%", "percent": "%"}


def _decay_constant_table() -> tuple[dict[str, float], dict[str, str]]:
    table: dict[str, float] = {}
    aliases: dict[str, str] = {}
    for sym, f in _TIME.items():
        canon = f"1/{sym}"
        table[canon] = 1.0 / f
        for alt in (f"{sym}^-1", f"{sym}⁻¹", f"/{sym}", f"{sym}-1"):
            aliases[alt] = canon
    for alias, target in _TIME_ALIASES.items():
        for alt in (f"1/{alias}", f"{alias}^-1", f"{alias}⁻¹", f"/{alias}"):
            aliases.setdefault(alt, f"1/{target}")
    return table, aliases


_DC, _DC_ALIASES = _decay_constant_table()

#: kind -> (Faktortabelle, Aliase, Basiseinheit)
KINDS: dict[str, tuple[dict[str, float], dict[str, str], str]] = {
    "time": (_TIME, _TIME_ALIASES, "s"),
    "decay_constant": (_DC, _DC_ALIASES, "1/s"),
    "energy": (_ENERGY, {}, "keV"),
    "mass": (_MASS, _MASS_ALIASES, "u"),
    "cross_section": (_XS, _XS_ALIASES, "b"),
    "fraction": (_FRACTION, _FRACTION_ALIASES, "1"),
}

#: Einheit in Feldnamen/quantities.json -> Größenart
UNIT_KIND = {"s": "time", "1/s": "decay_constant", "keV": "energy", "u": "mass", "b": "cross_section",
             "%": "fraction", "1": "fraction"}


def units_of(kind: str) -> list[str]:
    """Kanonische Einheitensymbole einer Größenart."""
    return list(_table(kind)[0])


def _table(kind: str):
    try:
        return KINDS[kind]
    except KeyError:
        raise UnitError(f"Unbekannte Größenart {kind!r}; bekannt: {', '.join(KINDS)}") from None


def _lookup_in(kind: str, unit: str) -> str | None:
    table, aliases, _base = _table(kind)
    u = unit.strip()
    if u in table:
        return u
    if u in aliases:
        return aliases[u]
    # Groß-/Kleinschreibung tolerieren, aber nur wenn eindeutig (MeV vs. meV, Mb vs. mb …)
    folded = u.casefold()
    hits = {c for c in table if c.casefold() == folded}
    hits |= {t for a, t in aliases.items() if a.casefold() == folded}
    if len(hits) == 1:
        return hits.pop()
    return None


def lookup(unit: str, kind: str | None = None) -> tuple[str, str]:
    """Einheit erkennen → (Größenart, kanonisches Symbol)."""
    kinds = [kind] if kind else list(KINDS)
    found = [(k, c) for k in kinds if (c := _lookup_in(k, unit)) is not None]
    if not found:
        where = f" für {kind}" if kind else ""
        raise UnitError(f"Unbekannte Einheit{where}: {unit!r}")
    if len(found) > 1:
        raise UnitError(f"Mehrdeutige Einheit {unit!r}: {found}")
    return found[0]


def factor(unit: str, kind: str | None = None) -> float:
    """Faktor, mit dem ein Wert in ``unit`` in die Basiseinheit umgerechnet wird."""
    k, canon = lookup(unit, kind)
    return _table(k)[0][canon]


def _clean(x: float) -> float:
    """Rundungsrauschen der Gleitkommarechnung entfernen (30.017999999999997 → 30.018).

    Gerundet wird auf 15 signifikante Stellen; das liegt weit unter jeder Messunsicherheit.
    """
    return float(f"{x:.15g}") if math.isfinite(x) else x


def convert(value: float, from_unit: str, to_unit: str, kind: str | None = None) -> float:
    """Umrechnen innerhalb einer Größenart, z. B. ``convert(3.8235, "d", "h")``."""
    k1, c1 = lookup(from_unit, kind)
    k2, c2 = lookup(to_unit, kind or k1)
    if k1 != k2:
        raise UnitError(f"{from_unit!r} ({k1}) lässt sich nicht in {to_unit!r} ({k2}) umrechnen")
    t = _table(k1)[0]
    return _clean(value * t[c1] / t[c2])


def to_base(value: float, unit: str, kind: str | None = None) -> float:
    return _clean(value * factor(unit, kind))


def from_base(value: float, unit: str, kind: str | None = None) -> float:
    return _clean(value / factor(unit, kind))


# ---------------------------------------------------------------------------------------------
# Zerfallskonstante <-> Halbwertszeit
# ---------------------------------------------------------------------------------------------

def half_life_to_lambda(t_s: float, unc_s: float | None = None) -> tuple[float, float | None]:
    """T½ (s) → (λ in 1/s, Unsicherheit). Relative Unsicherheit bleibt gleich."""
    if not t_s > 0:
        raise ValueError(f"Halbwertszeit muss positiv sein, nicht {t_s}")
    lam = LN2 / t_s
    return lam, (None if unc_s is None else lam * unc_s / t_s)


def lambda_to_half_life(lam: float, unc: float | None = None) -> tuple[float, float | None]:
    """λ (1/s) → (T½ in s, Unsicherheit)."""
    if not lam > 0:
        raise ValueError(f"Zerfallskonstante muss positiv sein, nicht {lam}")
    t = LN2 / lam
    return t, (None if unc is None else t * unc / lam)


# ---------------------------------------------------------------------------------------------
# Zahlen und Größen aus Text lesen
# ---------------------------------------------------------------------------------------------

# Tausendertrenner (Leerzeichen, schmales Leerzeichen, Apostroph) nur vor genau drei Ziffern,
# damit "5 1/s" nicht als 51 gelesen wird.
_NUM = (r"[+\-−]?(?:\d+(?:[   ']\d{3}(?!\d))*(?:[.,]\d+)*|[.,]\d+)"
        r"(?:[eE][+\-−]?\d+)?")
_QTY = re.compile(
    rf"^\s*(?P<num>{_NUM})\s*(?:\((?P<paren>\d+)\))?"
    rf"(?:\s*(?:±|\+/-|\+-)\s*(?P<pm>{_NUM}))?"
    rf"\s*(?P<unit>.*?)\s*$"
)


@dataclass(frozen=True, slots=True)
class Quantity:
    """Gelesener Messwert in der Basiseinheit seiner Größenart."""
    value: float
    unc: float | None
    unit: str        # Basiseinheit, z. B. "s"
    kind: str
    text: str        # Originaltext


def _clean_number(s: str) -> tuple[float, int]:
    """Zahl lesen; liefert (Wert, Anzahl Nachkommastellen der Mantisse).

    Dezimalkomma und -punkt werden beide akzeptiert. Kommen beide vor, ist das zuletzt
    stehende Zeichen das Dezimalzeichen, das andere ein Tausendertrenner.
    """
    s = s.strip().replace("−", "-")
    for sep in (" ", " ", " ", "'"):
        s = s.replace(sep, "")
    if not s or s in "+-":
        raise UnitError("Keine Zahl gefunden")
    mant, _, exp = s.partition("e") if "e" in s else s.partition("E")
    if "," in mant and "." in mant:
        if mant.rfind(",") > mant.rfind("."):
            mant = mant.replace(".", "").replace(",", ".")
        else:
            mant = mant.replace(",", "")
    else:
        if mant.count(",") > 1 or mant.count(".") > 1:
            raise UnitError(f"Zahl nicht eindeutig lesbar: {s!r}")
        mant = mant.replace(",", ".")
    decimals = len(mant.split(".", 1)[1]) if "." in mant else 0
    try:
        value = float(mant + (f"e{exp}" if exp else ""))
    except ValueError:
        raise UnitError(f"Keine gültige Zahl: {s!r}") from None
    return value, decimals


def parse_number(text: str) -> tuple[float, float | None]:
    """Zahl mit optionaler Unsicherheit lesen: ``"5,2714(5)"``, ``"2.60E-15(5)"``, ``"12.3 ± 0.4"``."""
    q = _parse_parts(text)
    if q[2]:
        raise UnitError(f"Unerwartete Einheit in Zahl: {text!r}")
    return q[0], q[1]


def _parse_parts(text: str) -> tuple[float, float | None, str]:
    m = _QTY.match(text.replace("−", "-"))
    if not m or not m.group("num") or not re.search(r"\d", m.group("num")):
        raise UnitError(f"Keine Zahl erkannt: {text!r}")
    num = m.group("num")
    # Ein Leerzeichen-Tausendertrenner darf die Einheit nicht verschlucken: "5 a" -> num="5 "
    value, decimals = _clean_number(num)
    exp_match = re.search(r"[eE]([+\-−]?\d+)", num)
    exponent = int(exp_match.group(1).replace("−", "-")) if exp_match else 0
    unc: float | None = None
    if m.group("paren"):
        unc = int(m.group("paren")) * 10.0 ** (exponent - decimals)
    elif m.group("pm"):
        unc, _ = _clean_number(m.group("pm"))
        unc = abs(unc)
    return value, unc, m.group("unit").strip()


def parse_quantity(text: str, kind: str, default_unit: str | None = None) -> Quantity:
    """Größe aus Text lesen und in die Basiseinheit umrechnen.

    ``kind`` ist eine Größenart aus :data:`KINDS` oder ``"half_life"``: Dann darf die Eingabe
    eine Zeit **oder** eine Zerfallskonstante sein, das Ergebnis ist immer T½ in Sekunden.
    Fehlt die Einheit, gilt ``default_unit`` (sonst Fehler, außer bei ``fraction``).
    """
    value, unc, unit = _parse_parts(text)
    if not unit:
        if default_unit is None and kind != "fraction":
            raise UnitError(f"Einheit fehlt: {text!r}")
        unit = default_unit or ""
    if kind == "half_life":
        k, canon = lookup(unit, None)
        if k == "time":
            f = _TIME[canon]
            return Quantity(value * f, None if unc is None else unc * f, "s", "time", text)
        if k == "decay_constant":
            lam = value * _DC[canon]
            ulam = None if unc is None else unc * _DC[canon]
            t, ut = lambda_to_half_life(lam, ulam)
            return Quantity(t, ut, "s", "time", text)
        raise UnitError(f"{unit!r} ist weder Zeit noch Zerfallskonstante")
    table, _aliases, base = _table(kind)
    _k, canon = lookup(unit, kind)
    f = table[canon]
    return Quantity(value * f, None if unc is None else unc * f, base, kind, text)


# ---------------------------------------------------------------------------------------------
# Anzeige
# ---------------------------------------------------------------------------------------------

_AUTO_TIME = ["fs", "ps", "ns", "µs", "ms", "s", "min", "h", "d", "a"]


def auto_time_unit(seconds: float) -> str:
    """Gut lesbare Zeiteinheit: die größte, in der der Wert noch ≥ 1 ist."""
    s = abs(seconds)
    best = "fs"
    for u in _AUTO_TIME:
        if s >= _TIME[u]:
            best = u
    return best


def _fmt_number(x: float, digits: int) -> str:
    if x == 0:
        return "0"
    mag = math.floor(math.log10(abs(x)))
    if -4 <= mag < 6:
        decimals = max(digits - 1 - mag, 0)
        return f"{x:.{decimals}f}"
    mant, exp = f"{x:.{digits - 1}e}".split("e")
    return f"{mant}e{int(exp)}"


def format_measurement(value: float, unc: float | None = None, digits: int = 4) -> str:
    """Wert mit Unsicherheit in Klammerschreibweise, z. B. ``5.2711(8)``.

    Die Unsicherheit wird auf zwei signifikante Stellen gerundet (bzw. eine, wenn sie mit
    3…9 beginnt), der Wert auf dieselbe Stelle. Ohne Unsicherheit: ``digits`` signifikante Stellen.
    """
    if unc is None or unc <= 0 or not math.isfinite(unc):
        return _fmt_number(value, digits)
    umag = math.floor(math.log10(unc))
    lead = unc / 10.0 ** umag
    sig = 2 if lead < 3 else 1
    place = umag - sig + 1                      # Zehnerpotenz der letzten Stelle
    vmag = math.floor(math.log10(abs(value))) if value else umag
    if vmag >= 6 or vmag < -4:                  # wissenschaftliche Schreibweise
        decimals = max(vmag - place, 0)
        mant = value / 10.0 ** vmag
        u_digits = round(unc / 10.0 ** place)
        return f"{mant:.{decimals}f}({u_digits})e{vmag}"
    decimals = max(-place, 0)
    u_digits = round(unc / 10.0 ** place)
    if place > 0:                               # Unsicherheit größer als 1 Einheit: ausschreiben
        step = 10 ** place
        rounded = math.copysign(math.floor(abs(value) / step + 0.5) * step, value)  # kaufmännisch
        return f"{rounded:.0f}({u_digits * step})"
    return f"{value:.{decimals}f}({u_digits})"


def format_quantity(value: float, unit: str, unc: float | None = None, *, kind: str | None = None,
                    digits: int = 4, decimal_comma: bool = False) -> str:
    """Wert aus der Basiseinheit in ``unit`` umrechnen und formatieren, z. B. ``"5.2711(8) a"``."""
    k, canon = lookup(unit, kind)
    f = _table(k)[0][canon]
    v = value / f
    u = None if unc is None else unc / f
    s = format_measurement(v, u, digits)
    if decimal_comma:
        s = s.replace(".", ",")
    return f"{s} {canon}".rstrip() if canon != "1" else s


def format_time(seconds: float, unit: str = "auto", unc: float | None = None, *, digits: int = 4,
                decimal_comma: bool = False) -> str:
    """Zeit (in s) anzeigen, z. B. ``format_time(166339713)`` → ``"5.271 a"``."""
    u = auto_time_unit(seconds) if unit == "auto" else unit
    return format_quantity(seconds, u, unc, kind="time", digits=digits, decimal_comma=decimal_comma)
