"""Dateien, Formatkennungen, Pflichtfelder und Sortierung (Spezifikation Abschnitt 4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import names

#: Version des Datenformats (= Version der Spezifikation `docs/NUCDB-SPEC.md`).
SCHEMA_VERSION = "1.2.0"


def parse_version(v: str) -> tuple[int, int, int]:
    parts = (str(v).split(".") + ["0", "0"])[:3]
    try:
        return tuple(int(p) for p in parts)  # type: ignore[return-value]
    except ValueError:
        raise ValueError(f"Ungültige Versionsangabe: {v!r}") from None


def is_compatible(data_version: str, lib_version: str = SCHEMA_VERSION) -> bool:
    """Gleiche MAJOR-Version = kompatibel (Spezifikation 5.2)."""
    return parse_version(data_version)[0] == parse_version(lib_version)[0]


def _num(x) -> float:
    return x if isinstance(x, (int, float)) else float("inf")


def _nuc(r: dict, key: str = "nuclide"):
    return names.sort_key(str(r.get(key, "")))


@dataclass(frozen=True)
class FileSpec:
    name: str                       # ohne .json
    required: tuple[str, ...]       # Pflichtfelder je Datensatz
    sort_key: Callable[[dict], tuple]
    nuclide_fields: tuple[str, ...] = ()   # Felder, die auf Nuklide verweisen
    lazy: bool = True               # erst bei Bedarf laden


FILES: dict[str, FileSpec] = {f.name: f for f in (
    FileSpec("sources", ("key",), lambda r: (str(r.get("key", "")),), lazy=False),
    FileSpec("quantities", ("quantity", "unit", "dtype"), lambda r: (str(r.get("quantity", "")),),
             lazy=False),
    FileSpec("elements", ("z", "symbol"), lambda r: (_num(r.get("z")),)),
    FileSpec("nuclides", ("name", "z", "a"),
             lambda r: (_num(r.get("z")), _num(r.get("a")), _num(r.get("isomer", 0)), str(r.get("name")))),
    FileSpec("decay_modes", ("parent", "source"),
             lambda r: (_nuc(r, "parent"), str(r.get("source", "")), str(r.get("mode", "")),
                        str(r.get("daughter", ""))),
             nuclide_fields=("parent", "daughter")),
    FileSpec("decay_gamma", ("nuclide", "energy_kev", "source"),
             lambda r: (_nuc(r), str(r.get("source", "")), _num(r.get("energy_kev"))),
             nuclide_fields=("nuclide", "target")),
    FileSpec("decay_alpha", ("nuclide", "energy_kev", "source"),
             lambda r: (_nuc(r), str(r.get("source", "")), _num(r.get("energy_kev"))),
             nuclide_fields=("nuclide",)),
    FileSpec("decay_beta", ("nuclide", "type", "energy_kev", "source"),
             lambda r: (_nuc(r), str(r.get("source", "")), str(r.get("type", "")), _num(r.get("energy_kev"))),
             nuclide_fields=("nuclide",)),
    FileSpec("decay_electron", ("nuclide", "type", "energy_kev", "source"),
             lambda r: (_nuc(r), str(r.get("source", "")), _num(r.get("energy_kev"))),
             nuclide_fields=("nuclide",)),
    FileSpec("special_lines", ("kind", "source"),
             lambda r: (str(r.get("kind", "")), _num(r.get("energy_kev", r.get("offset_kev"))),
                        str(r.get("origin", "")))),
    FileSpec("prompt_gamma", ("target", "energy_kev", "source"),
             lambda r: (_nuc(r, "target"), str(r.get("source", "")), _num(r.get("energy_kev"))),
             nuclide_fields=("target", "product")),
    FileSpec("activation_gamma", ("target", "energy_kev", "source"),
             lambda r: (_nuc(r, "target"), _nuc(r, "product"), str(r.get("source", "")), _num(r.get("energy_kev"))),
             nuclide_fields=("target", "product")),
    FileSpec("isomer_feeding", ("parent", "isomer", "fraction", "source"),
             lambda r: (_nuc(r, "parent"), _nuc(r, "isomer"), str(r.get("source", ""))),
             nuclide_fields=("parent", "isomer")),
    FileSpec("changelog", ("changed_at", "file"), lambda r: (str(r.get("changed_at", "")),)),
)}

#: Strahlungsdateien: Kurzname der API -> Datei
EMISSION_FILES = {"gamma": "decay_gamma", "alpha": "decay_alpha", "beta": "decay_beta",
                  "electron": "decay_electron"}

SPECIAL_KINDS = ("annihilation", "sum", "single_escape", "double_escape", "xray_fluorescence",
                 "backscatter", "compton_edge")



def format_id(name: str) -> str:
    return f"nucdb/{name}"


def sort_key_for(name: str) -> Callable[[dict], tuple]:
    spec = FILES.get(name)
    return spec.sort_key if spec else (lambda r: ())
