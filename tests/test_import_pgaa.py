"""PGAA-Excel-Importer (nur lokale Datenbanken).

Die Excel-Dateien selbst liegen nicht im Repository (Weitergabe ungeklärt). Die Logik wird mit
einigen Zeilen getestet, die hier direkt stehen; der Integrationstest läuft nur, wenn
``db-source/`` lokal vorhanden ist.
"""

from pathlib import Path

import pytest

from nucdb import NucDB
from nucdb.fileformat import write_file
from nucdb.importers import pgaa_xls
from nucdb.maintenance import build_all, create_base, update_manifest
from nucdb.validate import validate

ROWS = {
    "prompt": [
        [1.0, "  2-H ", 1.0, "p", "2223.24835(9)", 2223.248, "           0.3326(7)", 0.3326, 0.0007,
         "          1.0000(21)", 1.0, 0.0021],
        [3.0, "  4-He", 2.0, "p", 20520.46, 20520.46, "         4.2E-11(12)", 4.2e-11, 1.2e-11,
         "          3.2E-11(9)", 3.18e-11, 9.09e-12],
    ],
    "activation": [
        [15.0, " 16-N ", 7.0, "d", "    6128.63(4)", 6128.63, "        5.90E-08(12)", 5.9e-08, 1.19e-09,
         "     7.13 S", 7.13, "         1.28E-08(3)", 1.28e-08, 2.57e-10],
    ],
    "isotopes": [
        ["H ", "  1-H ", 1.0, 1.0, "   99.9885(70)      ", 99.9885, 0.007, "    0.3326(7)       ", 0.3326,
         0.0007, 0.999, 1.0],
        ["He", "  4-He", 2.0, 4.0, "   99.999863(3)     ", 99.999863, 3e-06, 0.0, "           ", "      ", 1.0, 0.0],
    ],
    "elements": [
        [1.0, "H", "Hydrogen", "1.00794(7)", 1.00794, 7e-05, "    0.3326(7)       ", 0.3326, 0.00069989],
    ],
}

NUCLIDES = [
    {"name": "H-1", "z": 1, "a": 1, "stable": True,
     "values": {"abundance_percent": [{"value": 99.9855, "source": "NUBASE2020"}]}},
    {"name": "H-2", "z": 1, "a": 2, "stable": True},
    {"name": "He-4", "z": 2, "a": 4, "stable": True},
    {"name": "N-15", "z": 7, "a": 15, "stable": True},
    {"name": "N-16", "z": 7, "a": 16},
]


@pytest.fixture()
def root(tmp_path, monkeypatch):
    r = create_base(tmp_path / "db")
    from nucdb.importers.common import upsert_source
    upsert_source(r, {"key": "NUBASE2020", "redistributable": True})
    write_file(r / "nuclides.json", "nuclides", NUCLIDES)
    src = tmp_path / "src"
    src.mkdir()
    for f in pgaa_xls.FILES.values():
        (src / f).write_bytes(b"")                    # nur vorhanden, Inhalt kommt aus ROWS
    by_file = {v: ROWS[k] for k, v in pgaa_xls.FILES.items()}
    monkeypatch.setattr(pgaa_xls, "_rows", lambda p: iter(by_file[Path(p).name]))
    pgaa_xls.run(r, src)
    update_manifest(r)
    return r


def test_prompt_gammas(root):
    db = NucDB(root, overlay=False)
    (h,) = db.prompt_gammas(target="H-1")
    assert h.product == "H-2" and h.element == "H"
    assert h.energy_kev == pytest.approx(2223.24835) and h.energy_kev_unc == pytest.approx(9e-5)
    assert h.sigma_partial_b == pytest.approx(0.3326) and h.k0 == pytest.approx(1.0)
    he = db.prompt_gammas(element="He")[0]
    assert he.energy_kev == pytest.approx(20520.46) and he.sigma_partial_b_unc == pytest.approx(1.2e-11)


def test_activation_separate_from_decay_lines(root):
    db = NucDB(root, overlay=False)
    (n,) = db.activation_gammas(element="N")
    assert (n.target, n.product) == ("N-15", "N-16") and n.half_life_s == pytest.approx(7.13)
    assert n.sigma_partial_b == pytest.approx(5.9e-8) and n.k0_unc == pytest.approx(0.03e-8)
    assert not db.gammas("N-16")                     # keine Vermischung mit Zerfallslinien


def test_isotope_values_are_secondary(root):
    db = NucDB(root, overlay=False)
    h1 = db.nuclide("H-1")
    assert h1.preferred("abundance_percent").source == "NUBASE2020"
    assert h1.value("sigma_capture_b") == pytest.approx(0.3326) and h1.value("g_factor_westcott") == 0.999
    assert "sigma_capture_b" not in db.nuclide("He-4").quantities  # 0.0 ohne Text = kein Wert


def test_elements(root):
    h = NucDB(root, overlay=False).element("H")
    assert h.get("atomic_weight_u") == pytest.approx(1.00794) and h.get("atomic_weight_source") == "PGAA-XLS"


def test_not_distributable(root):
    assert not [i for i in validate(root) if i.level == "error"]
    errs = [i for i in validate(root, distributable=True) if i.level == "error"]
    assert {i.file for i in errs} >= {"prompt_gamma.json", "activation_gamma.json", "nuclides.json", "elements.json"}


def test_local_build_refuses_package_snapshot():
    from nucdb.locate import PACKAGE_DATA
    with pytest.raises(ValueError):
        build_all(PACKAGE_DATA, "db-source", local=True)
    assert (PACKAGE_DATA / "manifest.json").is_file()   # nichts gelöscht


def test_package_snapshot_is_distributable():
    from nucdb.locate import PACKAGE_DATA
    assert not [i for i in validate(PACKAGE_DATA, distributable=True) if i.level == "error"]


REAL = Path(__file__).parents[1] / "db-source"


@pytest.mark.skipif(not (REAL / pgaa_xls.FILES["prompt"]).is_file(), reason="PGAA-Excel nicht vorhanden")
def test_real_files_parse():
    prompt = pgaa_xls.parse_lines(REAL / pgaa_xls.FILES["prompt"], kind="prompt")
    assert len(prompt) > 30000 and prompt[0]["target"] == "H-1"
