"""Importer AME2020/NUBASE2020 mit einem Auszug der Originaldateien (tests/data/amdc2020)."""

from pathlib import Path

import pytest

from nucdb import NucDB, units
from nucdb.fileformat import read_file
from nucdb.importers import amdc2020
from nucdb.maintenance import create_base, update_manifest
from nucdb.validate import validate

SRC = Path(__file__).parent / "data" / "amdc2020"


@pytest.fixture(scope="module")
def imported(tmp_path_factory):
    root = create_base(tmp_path_factory.mktemp("amdc") / "db")
    res = amdc2020.run(root, SRC)
    update_manifest(root)
    return root, res


@pytest.fixture(scope="module")
def db(imported):
    return NucDB(imported[0], overlay=False)


def test_masses_from_ame(db):
    co = db.nuclide("Co-60")
    assert co.value("mass_u") == 59.933815536          # exakt, ohne Rundungsrauschen
    assert co.unc("mass_u") == pytest.approx(0.433e-6)
    assert co.preferred("mass_u").source == "AME2020"
    assert co.value("binding_energy_per_nucleon_kev") == pytest.approx(8746.7692)
    assert co.value("q_beta_minus_kev") == pytest.approx(2822.8058)
    assert db.nuclide("Ra-226").value("q_alpha_kev") == pytest.approx(4870.7028)
    assert db.nuclide("n").value("mass_u") == pytest.approx(1.00866491590)


def test_q_ec_from_neighbour(db):
    # Q(EC) von Ni-60 = −Q(β⁻) von Co-60
    assert db.nuclide("Ni-60").value("q_ec_kev") == pytest.approx(-2822.8058)


def test_half_life_year_definition(db):
    co = db.nuclide("Co-60")
    v = co.preferred("half_life_s")
    assert v.source == "NUBASE2020"
    assert co.half_life("a") == pytest.approx(5.2714)
    assert v.value == pytest.approx(5.2714 * units.YEAR_S)
    assert db.nuclide("Rn-222").half_life("d") == pytest.approx(3.8215)


def test_stable_and_abundance(db):
    h1 = db.nuclide("H-1")
    assert h1.stable and h1.value("abundance_percent") == pytest.approx(99.9855)
    assert h1.unc("abundance_percent") == pytest.approx(0.0078)
    assert db.nuclide("Ta-180m").stable                 # stabiles Isomer bleibt erhalten


def test_isomer_naming_skips_short_states(db):
    ag = db.nuclide("Ag-110m")                         # NUBASE "n", das 660-ns-Isomer "m" entfällt
    assert ag.half_life("d") == pytest.approx(249.863)
    assert ag.fields["nubase_state"] == "n"
    assert not db.has_nuclide("Ag-110m2")
    assert db.nuclide("Ag-110m").value("level_energy_kev") == pytest.approx(117.59)


def test_decay_modes_and_subbranches(db):
    modes = {m.mode: m for m in db.decay_modes("Li-11")}
    assert modes["B-"].branching == 1.0
    assert modes["B-n"].parent_mode == "B-" and modes["B-n"].daughter == "Be-10"
    assert modes["B-n"].branching == pytest.approx(0.863) and modes["B-n"].branching_unc == pytest.approx(0.009)
    # Effektiver β⁻-Anteil zu Be-11 = 100 % minus aller Teilzweige mit anderer Tochter
    subs = sum(m.branching for m in modes.values() if m.parent_mode == "B-")
    assert modes["B-"].effective_branching == pytest.approx(1.0 - subs)


def test_ec_and_bplus_separate_when_they_add_up(db):
    modes = {m.mode: m for m in db.decay_modes("Ho-164")}
    assert modes["EC"].parent_mode is None and modes["EC"].effective_branching == pytest.approx(0.61)


def test_exponent_branching(db):
    a = next(m for m in db.decay_modes("I-113") if m.mode == "A")
    assert a.branching == pytest.approx(3.31e-7) and a.fields["branching_flag"] == "sys"


def test_isomer_decay(db):
    modes = {m.mode: m for m in db.decay_modes("Ag-110m")}
    assert modes["B-"].branching == pytest.approx(0.9867) and modes["IT"].daughter == "Ag-110"


def test_validates_and_is_idempotent(imported):
    root, res = imported
    assert not [i for i in validate(root) if i.level == "error"]
    before = (root / "nuclides.json").read_text()
    amdc2020.run(root, SRC)
    after = (root / "nuclides.json").read_text()
    assert before == after                              # erneuter Import ändert nichts
    srcs = {s["key"]: s for s in read_file(root / "sources.json")[1]}
    assert srcs["NUBASE2020"]["redistributable"] and "nubase_4.mas20.txt" in srcs["NUBASE2020"]["file_name"]


def test_manual_value_survives_reimport(imported):
    root, _ = imported
    from nucdb.fileformat import write_file
    head, recs = read_file(root / "nuclides.json")
    co = next(r for r in recs if r["name"] == "Co-60")
    for v in co["values"]["half_life_s"]:
        v.pop("preferred", None)
    co["values"]["half_life_s"].append({"value": 1.0e8, "source": "manual", "preferred": True})
    write_file(root / "nuclides.json", "nuclides", recs)
    amdc2020.run(root, SRC)
    db = NucDB(root, overlay=False)
    assert db.nuclide("Co-60").preferred("half_life_s").source == "manual"
    assert len(db.nuclide("Co-60").values("half_life_s")) == 2
