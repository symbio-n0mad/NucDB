"""Feste Elementtabelle (Ordnungszahl, Symbol, englischer und deutscher Name).

Die Tabelle ist Teil des Codes, weil die Namensauflösung (``"60Co"`` → Co-60) auch ohne
geladene Datenbank funktionieren muss. Atomgewichte und andere Messwerte stehen dagegen in
``elements.json`` der Datenbank.

Z = 0 ist das Neutron (Symbol ``n``), damit Zerfallsarten mit Neutronenemission und die
Neutronenmasse wie normale Nuklide behandelt werden können.
"""

from __future__ import annotations

# (Symbol, englischer Name, deutscher Name), Index = Ordnungszahl Z
_TABLE: tuple[tuple[str, str, str], ...] = (
    ("n", "Neutron", "Neutron"),
    ("H", "Hydrogen", "Wasserstoff"),
    ("He", "Helium", "Helium"),
    ("Li", "Lithium", "Lithium"),
    ("Be", "Beryllium", "Beryllium"),
    ("B", "Boron", "Bor"),
    ("C", "Carbon", "Kohlenstoff"),
    ("N", "Nitrogen", "Stickstoff"),
    ("O", "Oxygen", "Sauerstoff"),
    ("F", "Fluorine", "Fluor"),
    ("Ne", "Neon", "Neon"),
    ("Na", "Sodium", "Natrium"),
    ("Mg", "Magnesium", "Magnesium"),
    ("Al", "Aluminium", "Aluminium"),
    ("Si", "Silicon", "Silicium"),
    ("P", "Phosphorus", "Phosphor"),
    ("S", "Sulfur", "Schwefel"),
    ("Cl", "Chlorine", "Chlor"),
    ("Ar", "Argon", "Argon"),
    ("K", "Potassium", "Kalium"),
    ("Ca", "Calcium", "Calcium"),
    ("Sc", "Scandium", "Scandium"),
    ("Ti", "Titanium", "Titan"),
    ("V", "Vanadium", "Vanadium"),
    ("Cr", "Chromium", "Chrom"),
    ("Mn", "Manganese", "Mangan"),
    ("Fe", "Iron", "Eisen"),
    ("Co", "Cobalt", "Cobalt"),
    ("Ni", "Nickel", "Nickel"),
    ("Cu", "Copper", "Kupfer"),
    ("Zn", "Zinc", "Zink"),
    ("Ga", "Gallium", "Gallium"),
    ("Ge", "Germanium", "Germanium"),
    ("As", "Arsenic", "Arsen"),
    ("Se", "Selenium", "Selen"),
    ("Br", "Bromine", "Brom"),
    ("Kr", "Krypton", "Krypton"),
    ("Rb", "Rubidium", "Rubidium"),
    ("Sr", "Strontium", "Strontium"),
    ("Y", "Yttrium", "Yttrium"),
    ("Zr", "Zirconium", "Zirconium"),
    ("Nb", "Niobium", "Niob"),
    ("Mo", "Molybdenum", "Molybdän"),
    ("Tc", "Technetium", "Technetium"),
    ("Ru", "Ruthenium", "Ruthenium"),
    ("Rh", "Rhodium", "Rhodium"),
    ("Pd", "Palladium", "Palladium"),
    ("Ag", "Silver", "Silber"),
    ("Cd", "Cadmium", "Cadmium"),
    ("In", "Indium", "Indium"),
    ("Sn", "Tin", "Zinn"),
    ("Sb", "Antimony", "Antimon"),
    ("Te", "Tellurium", "Tellur"),
    ("I", "Iodine", "Iod"),
    ("Xe", "Xenon", "Xenon"),
    ("Cs", "Caesium", "Caesium"),
    ("Ba", "Barium", "Barium"),
    ("La", "Lanthanum", "Lanthan"),
    ("Ce", "Cerium", "Cer"),
    ("Pr", "Praseodymium", "Praseodym"),
    ("Nd", "Neodymium", "Neodym"),
    ("Pm", "Promethium", "Promethium"),
    ("Sm", "Samarium", "Samarium"),
    ("Eu", "Europium", "Europium"),
    ("Gd", "Gadolinium", "Gadolinium"),
    ("Tb", "Terbium", "Terbium"),
    ("Dy", "Dysprosium", "Dysprosium"),
    ("Ho", "Holmium", "Holmium"),
    ("Er", "Erbium", "Erbium"),
    ("Tm", "Thulium", "Thulium"),
    ("Yb", "Ytterbium", "Ytterbium"),
    ("Lu", "Lutetium", "Lutetium"),
    ("Hf", "Hafnium", "Hafnium"),
    ("Ta", "Tantalum", "Tantal"),
    ("W", "Tungsten", "Wolfram"),
    ("Re", "Rhenium", "Rhenium"),
    ("Os", "Osmium", "Osmium"),
    ("Ir", "Iridium", "Iridium"),
    ("Pt", "Platinum", "Platin"),
    ("Au", "Gold", "Gold"),
    ("Hg", "Mercury", "Quecksilber"),
    ("Tl", "Thallium", "Thallium"),
    ("Pb", "Lead", "Blei"),
    ("Bi", "Bismuth", "Bismut"),
    ("Po", "Polonium", "Polonium"),
    ("At", "Astatine", "Astat"),
    ("Rn", "Radon", "Radon"),
    ("Fr", "Francium", "Francium"),
    ("Ra", "Radium", "Radium"),
    ("Ac", "Actinium", "Actinium"),
    ("Th", "Thorium", "Thorium"),
    ("Pa", "Protactinium", "Protactinium"),
    ("U", "Uranium", "Uran"),
    ("Np", "Neptunium", "Neptunium"),
    ("Pu", "Plutonium", "Plutonium"),
    ("Am", "Americium", "Americium"),
    ("Cm", "Curium", "Curium"),
    ("Bk", "Berkelium", "Berkelium"),
    ("Cf", "Californium", "Californium"),
    ("Es", "Einsteinium", "Einsteinium"),
    ("Fm", "Fermium", "Fermium"),
    ("Md", "Mendelevium", "Mendelevium"),
    ("No", "Nobelium", "Nobelium"),
    ("Lr", "Lawrencium", "Lawrencium"),
    ("Rf", "Rutherfordium", "Rutherfordium"),
    ("Db", "Dubnium", "Dubnium"),
    ("Sg", "Seaborgium", "Seaborgium"),
    ("Bh", "Bohrium", "Bohrium"),
    ("Hs", "Hassium", "Hassium"),
    ("Mt", "Meitnerium", "Meitnerium"),
    ("Ds", "Darmstadtium", "Darmstadtium"),
    ("Rg", "Roentgenium", "Roentgenium"),
    ("Cn", "Copernicium", "Copernicium"),
    ("Nh", "Nihonium", "Nihonium"),
    ("Fl", "Flerovium", "Flerovium"),
    ("Mc", "Moscovium", "Moscovium"),
    ("Lv", "Livermorium", "Livermorium"),
    ("Ts", "Tennessine", "Tenness"),
    ("Og", "Oganesson", "Oganesson"),
)

MAX_Z = len(_TABLE) - 1

_BY_SYMBOL = {sym: z for z, (sym, _en, _de) in enumerate(_TABLE)}
# Ohne Groß-/Kleinschreibung sind die Elementsymbole eindeutig (z. B. "CO" -> Co). Das Neutron
# "n" bleibt außen vor, sonst kollidiert es mit Stickstoff "N"; es wird nur exakt erkannt.
_BY_SYMBOL_FOLDED = {sym.casefold(): z for sym, z in _BY_SYMBOL.items() if z > 0}
assert len(_BY_SYMBOL_FOLDED) == len(_BY_SYMBOL) - 1


def symbol(z: int) -> str:
    """Elementsymbol zur Ordnungszahl ``z``."""
    if not 0 <= z <= MAX_Z:
        raise ValueError(f"Ordnungszahl außerhalb 0…{MAX_Z}: {z}")
    return _TABLE[z][0]


def name_en(z: int) -> str:
    symbol(z)
    return _TABLE[z][1]


def name_de(z: int) -> str:
    symbol(z)
    return _TABLE[z][2]


def z_of(sym: str, *, strict_case: bool = False) -> int:
    """Ordnungszahl zu einem Elementsymbol. Ohne ``strict_case`` ist die Schreibweise egal."""
    sym = sym.strip()
    if sym in _BY_SYMBOL:
        return _BY_SYMBOL[sym]
    if not strict_case and sym.casefold() in _BY_SYMBOL_FOLDED:
        return _BY_SYMBOL_FOLDED[sym.casefold()]
    raise KeyError(f"Unbekanntes Elementsymbol: {sym!r}")


def z_candidates(sym: str) -> list[int]:
    """Alle Ordnungszahlen, die zu ``sym`` passen können (exakte Schreibweise zuerst)."""
    sym = sym.strip()
    out = []
    if sym in _BY_SYMBOL:
        out.append(_BY_SYMBOL[sym])
    z = _BY_SYMBOL_FOLDED.get(sym.casefold())
    if z is not None and z not in out:
        out.append(z)
    return out


def all_elements() -> list[tuple[int, str, str, str]]:
    """Liste aller Elemente als (Z, Symbol, englischer Name, deutscher Name), ohne Neutron."""
    return [(z, s, en, de) for z, (s, en, de) in enumerate(_TABLE) if z > 0]
