"""Nuklidnamen erkennen und in die kanonische Form bringen (Spezifikation 3.3).

Kanonisch: ``<Symbol>-<A>[m[n]]``, z. B. ``Co-60``, ``Tc-99m``, ``Hf-178m2``, ``n-1``.
Akzeptiert werden außerdem u. a. ``60Co``, ``Co60``, ``60-Co``, ``CO-60``, ``co 60``,
``99mTc``, ``Tc99m``, ``Am-242g`` (Grundzustand) sowie ``D`` (H-2) und ``T`` (H-3).
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import NamedTuple

from . import elements


class NuclideNameError(ValueError):
    """Der Text lässt sich keinem Nuklid zuordnen."""


class NuclideId(NamedTuple):
    z: int
    a: int
    isomer: int = 0

    @property
    def n(self) -> int:
        return self.a - self.z

    @property
    def symbol(self) -> str:
        return elements.symbol(self.z)

    @property
    def name(self) -> str:
        return canonical_name(self.z, self.a, self.isomer)

    def __str__(self) -> str:  # pragma: no cover - Komfort
        return self.name


def canonical_name(z: int, a: int, isomer: int = 0) -> str:
    suffix = "" if isomer == 0 else "m" if isomer == 1 else f"m{isomer}"
    return f"{elements.symbol(z)}-{a}{suffix}"


_ALIASES = {"d": NuclideId(1, 2), "t": NuclideId(1, 3), "n": NuclideId(0, 1)}

# Isomer-Zusatz: m, m1, m2 … oder g (Grundzustand)
_ISO = r"(?:(?P<m>[mM])(?P<mn>\d)?|(?P<g>[gG]))?"
_SEP = r"\s*[-_ ]?\s*"
_SYM_FIRST = re.compile(rf"^(?P<sym>[A-Za-z]{{1,3}}){_SEP}(?P<a>\d{{1,3}})\s*{_ISO}$")
_A_FIRST = re.compile(rf"^(?P<a>\d{{1,3}})\s*{_ISO}{_SEP}(?P<sym>[A-Za-z]{{1,3}})$")


def _isomer(m: re.Match) -> int:
    if m.group("m"):
        return int(m.group("mn")) if m.group("mn") else 1
    return 0


def _plausible(z: int, a: int) -> bool:
    if z == 0:
        return a == 1
    return a >= z and a >= 1


def _candidates(text: str) -> list[NuclideId]:
    found: list[NuclideId] = []
    for rx in (_SYM_FIRST, _A_FIRST):
        m = rx.match(text)
        if m:
            a = int(m.group("a"))
            for z in elements.z_candidates(m.group("sym")):
                if _plausible(z, a):
                    found.append(NuclideId(z, a, _isomer(m)))
                    break
    # "60Mn" passt formal auch als "60m" + "n". Daher zusätzlich die Lesart ohne Isomer-Buchstaben
    # prüfen, bei der das "m"/"M" zum Elementsymbol gehört.
    m2 = re.match(r"^(?P<a>\d{1,3})\s*[-_ ]?\s*(?P<sym>[A-Za-z]{1,3})$", text)
    if m2:
        a = int(m2.group("a"))
        for z in elements.z_candidates(m2.group("sym")):
            if _plausible(z, a):
                found.append(NuclideId(z, a, 0))
                break
    # Doppelte entfernen, Reihenfolge erhalten
    return list(dict.fromkeys(found))


@lru_cache(maxsize=4096)
def parse(text: str) -> NuclideId:
    """Text → :class:`NuclideId`. Wirft :class:`NuclideNameError` bei unklaren Angaben."""
    if not isinstance(text, str):
        raise NuclideNameError(f"Nuklidname muss Text sein, nicht {type(text).__name__}")
    t = text.strip()
    if t.casefold() in _ALIASES and t not in ("N",):  # "N" allein wäre Stickstoff ohne A
        return _ALIASES[t.casefold()]
    cands = _candidates(t)
    if not cands:
        raise NuclideNameError(f"Kein gültiger Nuklidname: {text!r}")
    if len(cands) > 1:
        # Mehrdeutig, z. B. "60Mn": Mn-60 (Grundzustand) vor "n-60m" (unplausibel, schon gefiltert).
        # Gibt es weiterhin mehrere, gewinnt die Lesart mit der längsten Symbolübereinstimmung,
        # also die ohne abgespaltenen Isomer-Buchstaben.
        ground = [c for c in cands if c.isomer == 0]
        if len(ground) == 1:
            return ground[0]
        raise NuclideNameError(f"Mehrdeutiger Nuklidname {text!r}: {', '.join(c.name for c in cands)}")
    return cands[0]


def normalize(text: str) -> str:
    """Text → kanonischer Name, z. B. ``"60co"`` → ``"Co-60"``."""
    return parse(text).name


def is_canonical(text: str) -> bool:
    try:
        return parse(text).name == text
    except NuclideNameError:
        return False


def sort_key(name: str) -> tuple[int, int, int, str]:
    """Sortierschlüssel (Z, A, Isomer). Ungültige Namen landen am Ende."""
    try:
        nid = parse(name)
        return (nid.z, nid.a, nid.isomer, "")
    except NuclideNameError:
        return (10_000, 0, 0, str(name))
