"""Physikalische Konstanten und einfache Formeln für Spektren.

Konstanten nach CODATA 2018. Das ist derselbe Satz, den AME2020 für die Umrechnung zwischen
Masseneinheiten und Energie verwendet. Nuklidmassen (Neutron, ¹H …) stehen **nicht** hier,
sondern in der Datenbank (Quelle AME2020).
"""

from __future__ import annotations

#: Ruheenergie des Elektrons m_e c² in keV (CODATA 2018: 0.510 998 950 00(15) MeV)
ELECTRON_MASS_KEV = 510.99895000
#: 1 u in keV/c² (CODATA 2018: 931.494 102 42(28) MeV, wie in AME2020)
ATOMIC_MASS_UNIT_KEV = 931_494.10242
#: 1 u in kg (CODATA 2018: 1.660 539 066 60(50) × 10⁻²⁷ kg)
ATOMIC_MASS_UNIT_KG = 1.66053906660e-27

ANNIHILATION_KEV = ELECTRON_MASS_KEV
PAIR_THRESHOLD_KEV = 2.0 * ELECTRON_MASS_KEV


def single_escape(energy_kev: float) -> float | None:
    """Lage des Single-Escape-Peaks, ``None`` unterhalb der Paarbildungsschwelle."""
    return energy_kev - ELECTRON_MASS_KEV if energy_kev > PAIR_THRESHOLD_KEV else None


def double_escape(energy_kev: float) -> float | None:
    """Lage des Double-Escape-Peaks, ``None`` unterhalb der Paarbildungsschwelle."""
    return energy_kev - PAIR_THRESHOLD_KEV if energy_kev > PAIR_THRESHOLD_KEV else None


def compton_edge(energy_kev: float) -> float:
    """Compton-Kante: maximale Energie, die ein Photon an ein Elektron abgibt (Streuung um 180°)."""
    return energy_kev * 2.0 * energy_kev / (ELECTRON_MASS_KEV + 2.0 * energy_kev)


def backscatter(energy_kev: float) -> float:
    """Rückstreupeak: Energie des um 180° gestreuten Photons."""
    return energy_kev / (1.0 + 2.0 * energy_kev / ELECTRON_MASS_KEV)
