"""Test-Datenbank. Die Zahlenwerte sind Testdaten, keine Referenzdaten."""

from __future__ import annotations

from pathlib import Path

import pytest

from nucdb.fileformat import write_file
from nucdb.maintenance import create_base, update_manifest

YEAR = 365.2422 * 86400


def _hl(value, src="TEST-A", **kw):
    return {"value": value, "source": src, **kw}


NUCLIDES = [
    {"name": "Co-60", "z": 27, "a": 60, "isomer": 0, "decay_source": "TEST-A",
     "values": {"half_life_s": [_hl(5.2711 * YEAR, unc=0.0008 * YEAR, preferred=True),
                                _hl(5.2714 * YEAR, "TEST-B", unc=0.0005 * YEAR)],
                "mass_u": [_hl(59.9338, "TEST-B")]}},
    {"name": "Ni-60", "z": 28, "a": 60, "isomer": 0, "stable": True},
    {"name": "Na-22", "z": 11, "a": 22, "values": {"half_life_s": [_hl(2.6029 * YEAR)]}},
    {"name": "Ne-22", "z": 10, "a": 22, "stable": True},
    {"name": "Rn-222", "z": 86, "a": 222, "values": {"half_life_s": [_hl(3.8235 * 86400)]}},
    {"name": "Po-218", "z": 84, "a": 218, "values": {"half_life_s": [_hl(3.098 * 60)]}},
    {"name": "Pb-214", "z": 82, "a": 214, "values": {"half_life_s": [_hl(27.06 * 60)]}},
    {"name": "At-218", "z": 85, "a": 218, "values": {"half_life_s": [_hl(1.5)]}},
    {"name": "Bi-214", "z": 83, "a": 214, "values": {"half_life_s": [_hl(19.9 * 60)]}},
    {"name": "Tc-99m", "z": 43, "a": 99, "isomer": 1, "values": {"half_life_s": [_hl(6.0067 * 3600)]}},
    {"name": "Tc-99", "z": 43, "a": 99, "values": {"half_life_s": [_hl(2.111e5 * YEAR)]}},
    {"name": "H-1", "z": 1, "a": 1, "stable": True},
    {"name": "H-2", "z": 1, "a": 2, "stable": True},
]

MODES = [
    {"parent": "Co-60", "mode": "B-", "daughter": "Ni-60", "branching": 1.0, "source": "TEST-A"},
    {"parent": "Na-22", "mode": "EC+B+", "daughter": "Ne-22", "branching": 1.0, "source": "TEST-A"},
    {"parent": "Rn-222", "mode": "A", "daughter": "Po-218", "branching": 1.0, "source": "TEST-A"},
    {"parent": "Po-218", "mode": "A", "daughter": "Pb-214", "branching": 0.9998, "source": "TEST-A"},
    {"parent": "Po-218", "mode": "B-", "daughter": "At-218", "branching": 0.0002, "source": "TEST-A"},
    {"parent": "At-218", "mode": "A", "daughter": "Bi-214", "branching": 1.0, "source": "TEST-A"},
    {"parent": "Pb-214", "mode": "B-", "daughter": "Bi-214", "branching": 1.0, "source": "TEST-A"},
    {"parent": "Bi-214", "mode": "B-", "daughter": "Po-214", "branching": 1.0, "source": "TEST-A"},
    {"parent": "Tc-99m", "mode": "IT", "daughter": "Tc-99", "branching": 1.0, "source": "TEST-A"},
]

GAMMAS = [
    {"nuclide": "Co-60", "radiation": "G", "energy_kev": 1173.228, "intensity": 0.9985, "source": "TEST-A"},
    {"nuclide": "Co-60", "radiation": "G", "energy_kev": 1332.492, "intensity": 0.999826, "source": "TEST-A"},
    {"nuclide": "Co-60", "radiation": "G", "energy_kev": 1332.50, "intensity": 0.9998, "source": "TEST-B"},
    {"nuclide": "Na-22", "radiation": "G", "energy_kev": 1274.537, "intensity": 0.9994, "source": "TEST-A"},
    {"nuclide": "Na-22", "radiation": "ANN", "energy_kev": 510.99895, "intensity": 1.798, "source": "TEST-A"},
    {"nuclide": "Bi-214", "radiation": "G", "energy_kev": 609.312, "intensity": 0.4549, "source": "TEST-A"},
    {"nuclide": "Bi-214", "radiation": "G", "energy_kev": 1764.494, "intensity": 0.1531, "source": "TEST-A"},
]

BETAS = [
    {"nuclide": "Co-60", "type": "B-", "energy_kev": 317.32, "mean_energy_kev": 95.77, "intensity": 0.9988,
     "source": "TEST-A"},
]

PROMPT = [
    {"target": "H-1", "product": "H-2", "element": "H", "energy_kev": 2223.248, "sigma_partial_b": 0.3326,
     "source": "TEST-A"},
]

SOURCES = [{"key": "TEST-A", "title": "Testquelle A", "redistributable": True},
           {"key": "TEST-B", "title": "Testquelle B", "redistributable": True}]


@pytest.fixture()
def dbdir(tmp_path: Path) -> Path:
    root = create_base(tmp_path / "db", data_version="2026.11.0")
    from nucdb.fileformat import read_file
    write_file(root / "sources.json", "sources", read_file(root / "sources.json")[1] + SOURCES)
    write_file(root / "nuclides.json", "nuclides", NUCLIDES)
    write_file(root / "decay_modes.json", "decay_modes", MODES)
    write_file(root / "decay_gamma.json", "decay_gamma", GAMMAS)
    write_file(root / "decay_beta.json", "decay_beta", BETAS)
    write_file(root / "prompt_gamma.json", "prompt_gamma", PROMPT)
    update_manifest(root)
    return root


@pytest.fixture()
def db(dbdir: Path, tmp_path: Path):
    from nucdb import NucDB
    return NucDB(dbdir, overlay=tmp_path / "overlay")
