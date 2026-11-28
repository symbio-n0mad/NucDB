"""Datenobjekte der Lese-API. Unbekannte Felder bleiben über Attribute bzw. ``fields`` erreichbar."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import units
from .names import NuclideId

#: Empfohlene Grenze für „praktisch stabil“ (10¹⁵ a in s), z. B. für ``db.chain(stable_above_s=…)``
PRACTICALLY_STABLE_S = 1e15 * units.YEAR_S


class _Extra:
    """Unbekannte/optionale Felder als Attribute zugänglich machen (``line.radiation``)."""

    fields: dict

    def __getattr__(self, item: str) -> Any:
        # Wird nur aufgerufen, wenn es kein echtes Attribut dieses Namens gibt.
        if item.startswith("__"):
            raise AttributeError(item)
        try:
            return self.__dict__["fields"][item]
        except KeyError:
            raise AttributeError(item) from None

    def get(self, key: str, default: Any = None) -> Any:
        return self.fields.get(key, default)


@dataclass(frozen=True)
class Value:
    """Ein Messwert einer skalaren Größe aus einer Quelle (Spezifikation 3.2/4.5)."""
    value: Any
    source: str
    unc: float | None = None
    preferred: bool = False
    text: str | None = None
    flag: str | None = None
    user: bool = False          # stammt aus der Ergänzungsdatenbank (Overlay)


@dataclass(frozen=True)
class Source(_Extra):
    key: str
    fields: dict = field(default_factory=dict, repr=False)
    user: bool = False

    @property
    def citation(self) -> str:
        return self.fields.get("citation") or self.fields.get("title") or self.key

    @property
    def redistributable(self) -> bool:
        return bool(self.fields.get("redistributable", True))


@dataclass(frozen=True)
class Element(_Extra):
    z: int
    symbol: str
    name_en: str
    name_de: str
    fields: dict = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class Nuclide:
    name: str
    z: int
    a: int
    isomer: int
    stable: bool
    decay_source: str | None
    values_by_quantity: dict[str, tuple[Value, ...]] = field(repr=False, default_factory=dict)
    fields: dict = field(repr=False, default_factory=dict)
    user: bool = False          # Nuklid wurde im Overlay neu angelegt

    # --- Identität ----------------------------------------------------------------------
    @property
    def n(self) -> int:
        return self.a - self.z

    @property
    def id(self) -> NuclideId:
        return NuclideId(self.z, self.a, self.isomer)

    @property
    def symbol(self) -> str:
        return self.id.symbol

    # --- Werte --------------------------------------------------------------------------
    def values(self, quantity: str) -> tuple[Value, ...]:
        """Alle Werte einer Größe (alle Quellen), bevorzugter Wert zuerst."""
        return self.values_by_quantity.get(quantity, ())

    def preferred(self, quantity: str) -> Value | None:
        vals = self.values(quantity)
        return vals[0] if vals else None

    def value(self, quantity: str, default: Any = None) -> Any:
        """Bevorzugter Zahlenwert einer Größe in der Basiseinheit (oder ``default``)."""
        v = self.preferred(quantity)
        return default if v is None else v.value

    def unc(self, quantity: str) -> float | None:
        v = self.preferred(quantity)
        return None if v is None else v.unc

    @property
    def quantities(self) -> list[str]:
        return sorted(self.values_by_quantity)

    # --- Halbwertszeit und Zerfallskonstante ---------------------------------------------
    @property
    def half_life_s(self) -> float | None:
        """T½ in s; ``None`` wenn unbekannt; ``math.inf`` bei stabilen Nukliden ohne Wert."""
        t = self.value("half_life_s")
        if t is None and self.stable:
            return float("inf")
        return t

    @property
    def half_life_unc_s(self) -> float | None:
        return self.unc("half_life_s")

    def practically_stable(self, limit_s: float | None = None) -> bool:
        """Stabil oder T½ ≥ ``limit_s`` (Standard :data:`PRACTICALLY_STABLE_S`, 10¹⁵ a).

        Die Daten bleiben unverändert (Bi-209 bleibt radioaktiv); das ist nur eine gemeinsame
        Grenze, damit alle Tools Ketten an derselben Stelle enden lassen.
        """
        t = self.half_life_s
        if t is None:
            return False
        return t >= (PRACTICALLY_STABLE_S if limit_s is None else limit_s)

    def half_life(self, unit: str = "s") -> float | None:
        t = self.half_life_s
        return None if t is None else units.from_base(t, unit, "time")

    def decay_constant(self, unit: str = "1/s") -> float | None:
        """λ in der gewünschten Einheit; 0 bei stabilen Nukliden, ``None`` wenn unbekannt."""
        t = self.half_life_s
        if t is None:
            return None
        if t == float("inf"):
            return 0.0
        lam, _ = units.half_life_to_lambda(t)
        return units.from_base(lam, unit, "decay_constant")

    def format_half_life(self, unit: str = "auto", digits: int = 4, decimal_comma: bool = False) -> str:
        t = self.half_life_s
        if t is None:
            return "?"
        if t == float("inf"):
            return "stabil"
        return units.format_time(t, unit, self.half_life_unc_s, digits=digits, decimal_comma=decimal_comma)


@dataclass(frozen=True)
class DecayMode(_Extra):
    parent: str
    mode: str | None
    daughter: str | None
    branching: float | None
    source: str
    branching_unc: float | None = None
    q_value_kev: float | None = None
    fields: dict = field(default_factory=dict, repr=False)
    user: bool = False
    #: Anteil, der tatsächlich zu ``daughter`` führt. Beim Hauptzweig (z. B. B-) sind die
    #: Teilzweige mit anderer Tochter (B-n …) schon abgezogen. ``None`` = unbekannt.
    effective_branching: float | None = None
    #: Teilzweig mit derselben Tochter wie sein Hauptzweig (z. B. EC innerhalb von B+): nur Information,
    #: zählt in Ketten nicht zusätzlich.
    informational: bool = False

    @property
    def parent_mode(self) -> str | None:
        return self.fields.get("parent_mode")


@dataclass(frozen=True)
class Emission(_Extra):
    """Eine Linie bzw. ein Zweig der Zerfallsstrahlung (Gamma, Röntgen, Alpha, Beta, Elektron).

    Bei Beta-Zweigen ist ``energy_kev`` die Endpunktenergie (E_max).
    """
    kind: str                     # gamma | alpha | beta | electron
    nuclide: str
    energy_kev: float
    source: str
    energy_kev_unc: float | None = None
    intensity: float | None = None
    intensity_unc: float | None = None
    fields: dict = field(default_factory=dict, repr=False)
    user: bool = False


@dataclass(frozen=True)
class SpecialLine(_Extra):
    kind: str
    source: str
    energy_kev: float | None = None
    offset_kev: float | None = None
    origin: str | None = None
    description: str | None = None
    fields: dict = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class PromptGamma(_Extra):
    target: str
    energy_kev: float
    source: str
    product: str | None = None
    element: str | None = None
    energy_kev_unc: float | None = None
    sigma_partial_b: float | None = None
    sigma_partial_b_unc: float | None = None
    k0: float | None = None
    k0_unc: float | None = None
    fields: dict = field(default_factory=dict, repr=False)
    user: bool = False


@dataclass(frozen=True)
class ActivationGamma(_Extra):
    """Linie eines Aktivierungsprodukts mit partiellem Querschnitt bezogen auf das Target (NAA)."""
    target: str
    energy_kev: float
    source: str
    product: str | None = None
    element: str | None = None
    energy_kev_unc: float | None = None
    sigma_partial_b: float | None = None
    sigma_partial_b_unc: float | None = None
    k0: float | None = None
    k0_unc: float | None = None
    half_life_s: float | None = None     # T½ des Produkts laut Quelle
    fields: dict = field(default_factory=dict, repr=False)
    user: bool = False


@dataclass(frozen=True)
class LineMatch:
    """Treffer bei der Peak-Identifikation.

    ``kind``: ``"decay"`` (Linie selbst), ``"single_escape"``/``"double_escape"`` (Escape-Peak der
    Linie ``line``) oder ``"special"`` (feste Sonderlinie wie 511 keV).
    ``energy_kev`` ist die erwartete Peaklage, ``delta_kev`` = gesuchte Energie − erwartete Lage.
    """
    kind: str
    energy_kev: float
    delta_kev: float
    line: Emission | SpecialLine | PromptGamma
    score: float = 0.0          # Bewertung für die Sortierung (siehe NucDB.find_gammas)


@dataclass(frozen=True)
class Chain:
    """Zerfallskette ab ``root``: alle erreichbaren Nuklide (Mutter vor Töchtern) und Zweige."""
    root: str
    nuclides: tuple[str, ...]
    edges: tuple[DecayMode, ...]
    unknown: tuple[str, ...] = ()       # Töchter, die nicht in der Datenbank stehen (Datenfehler)
    open_ends: tuple[str, ...] = ()     # instabile Nuklide ohne bekannte Zerfallsart
    practically_stable: tuple[str, ...] = ()   # Endpunkte wegen ``stable_above_s`` (seit 1.2)

    def daughters(self, name: str) -> list[DecayMode]:
        return [e for e in self.edges if e.parent == name]
