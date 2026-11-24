"""Importer DDEP (Lara) und ENSDF/LiveChart mit kleinen Auszügen der Originaldaten."""

from pathlib import Path

import pytest

from nucdb import NucDB, units
from nucdb.fileformat import write_file
from nucdb.importers import ddep, livechart
from nucdb.maintenance import create_base, update_manifest
from nucdb.validate import validate

DATA = Path(__file__).parent / "data"
Y = units.YEAR_S


def _n(name, z, a, iso=0, stable=False, **vals):
    rec = {"name": name, "z": z, "a": a, "isomer": iso, "stable": stable, "values": {}}
    for q, v in vals.items():
        rec["values"][q] = [{"value": v, "source": "NUBASE2020"}]
    return rec


NUCLIDES = [
    _n("H-3", 1, 3, half_life_s=12.32 * Y), _n("He-3", 2, 3, stable=True),
    _n("Na-22", 11, 22, half_life_s=2.6018 * Y), _n("Ne-22", 10, 22, stable=True),
    _n("K-45", 19, 45, half_life_s=1068.6), _n("Ca-45", 20, 45, half_life_s=162.6 * 86400),
    _n("Co-60", 27, 60, half_life_s=5.2714 * Y), _n("Co-60m", 27, 60, 1, half_life_s=628.02, level_energy_kev=58.59),
    _n("Ni-60", 28, 60, stable=True), _n("Pb-206", 82, 206, stable=True), _n("Po-210", 84, 210, half_life_s=138.376 * 86400),
    _n("Pb-208", 82, 208, stable=True), _n("Tl-208", 81, 208, half_life_s=183.2), _n("Po-212", 84, 212, half_life_s=2.94e-7),
    _n("Bi-212", 83, 212, half_life_s=3633.0),
    _n("Te-132", 52, 132, half_life_s=3.204 * 86400), _n("I-132", 53, 132, half_life_s=2.295 * 3600),
    _n("Xe-132", 54, 132, stable=True), _n("Sr-90", 38, 90, half_life_s=28.79 * Y),
    _n("Y-90", 39, 90, half_life_s=64.05 * 3600), _n("Zr-90", 40, 90, stable=True),
    _n("Cs-137", 55, 137, half_life_s=30.08 * Y), _n("Ba-137", 56, 137, stable=True),
    _n("Ba-137m", 56, 137, 1, half_life_s=153.12, level_energy_kev=661.659),
]
MODES = [{"parent": "Cs-137", "mode": "B-", "daughter": "Ba-137", "branching": 1.0, "source": "NUBASE2020"}]


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    r = create_base(tmp_path_factory.mktemp("decay") / "db")
    from nucdb.importers.common import upsert_source
    upsert_source(r, {"key": "NUBASE2020", "title": "Test", "redistributable": True})
    write_file(r / "nuclides.json", "nuclides", NUCLIDES)
    write_file(r / "decay_modes.json", "decay_modes", MODES)
    update_manifest(r)
    ddep.run(r, DATA / "ddep")
    livechart.run(r, DATA / "livechart")
    update_manifest(r)
    return r


@pytest.fixture(scope="module")
def db(root):
    return NucDB(root, overlay=False)


def test_ddep_half_life_preferred_and_year(db):
    co = db.nuclide("Co-60")
    assert co.preferred("half_life_s").source == "DDEP"
    assert co.half_life("a") == pytest.approx(5.2711)
    assert co.decay_source == "DDEP"
    assert co.fields["ddep_reference"].startswith("INEEL")


def test_ddep_gammas_and_xrays(db):
    g = {round(x.energy_kev, 3): x for x in db.gammas("Co-60")}
    assert g[1332.492].intensity == pytest.approx(0.999826) and g[1332.492].radiation == "G"
    assert g[1332.492].source == "DDEP"                       # nicht die ENSDF-Zeile
    assert any(x.radiation == "XK" and x.xray_line == "Ka1" for x in g.values())
    ann = db.gammas("Na-22", radiation="ANN")
    assert ann and ann[0].energy_kev == pytest.approx(511.0)


def test_ddep_alpha_branching_derived(db):
    modes = {m.mode: m for m in db.decay_modes("Bi-212")}
    assert modes["B-"].branching == pytest.approx(0.6407)
    assert modes["A"].branching == pytest.approx(0.3593) and modes["A"].fields["branching_flag"] == "~"
    assert db.decay_modes("Po-210")[0].branching == 1.0


def test_ddep_excludes_progeny_lines(db):
    # Bi-212.lara enthält die 8785-keV-Linie von Po-212 (Parent Po-212) – gehört nicht zu Bi-212
    alphas = db.alphas("Bi-212")
    assert not any(abs(a.energy_kev - 8785.17) < 0.01 for a in alphas)
    # β-verzögerte Alphas (a*) gehören dagegen zum Bi-212-Zerfall
    delayed = [a for a in alphas if a.get("beta_delayed")]
    assert delayed and all(a.energy_kev > 9000 for a in delayed)
    assert not db.has_nuclide("Ra-226D")


def test_livechart_beta_minus(db):
    (b,) = db.betas("H-3")
    assert b.source == "ENSDF-LiveChart" and b.type == "B-"
    assert b.energy_kev == pytest.approx(18.59, abs=0.01) and b.mean_energy_kev == pytest.approx(5.68, abs=0.01)


def test_livechart_beta_plus_endpoint_from_ec_energy(db):
    b = max(db.betas("Na-22"), key=lambda x: x.intensity)
    assert b.type == "B+" and b.energy_kev == pytest.approx(1568.63 - 1021.998, abs=0.01)
    assert b.intensity == pytest.approx(0.899) and b.ec_intensity == pytest.approx(0.1004)


def test_livechart_rejects_inconsistent_mean(db):
    bad = [b for b in db.betas("K-45") if b.get("note")]
    assert bad and bad[0].get("mean_energy_kev") is None


def test_livechart_isomer_assignment(db):
    m = db.emissions("gamma", "Co-60m", all_sources=True)
    assert [round(x.energy_kev, 3) for x in m] == [58.603]
    assert m[0].intensity == pytest.approx(0.0207)
    # Co-60 (DDEP bevorzugt): ENSDF-Zeilen nur mit all_sources
    assert any(x.source == "ENSDF-LiveChart" for x in db.gammas("Co-60", all_sources=True))


def test_electrons_and_fallback_to_ensdf(db):
    e = db.electrons("Na-22")
    assert e and all(x.source == "ENSDF-LiveChart" for x in e)   # DDEP hat keine Elektronen
    assert {x.type for x in e} <= {"AU", "CE"}


def test_valid(root):
    assert not [i for i in validate(root) if i.level == "error"]


def test_progeny_lines_belong_to_their_own_decay(db):
    # Sr-90.lara enthält die 2186-keV-Linie mit Parent Y-90: sie gehört zu Y-90, nicht zu Sr-90
    assert not db.gammas("Sr-90", radiation="G")
    assert any(abs(g.energy_kev - 2186.254) < 0.001 for g in db.gammas("Y-90"))


def test_progeny_without_own_file_taken_from_mother_file(db):
    # I-132 hat keine eigene DDEP-Datei; seine Linien stehen in der Te-132-Datei
    i132 = db.nuclide("I-132")
    assert i132.decay_source == "DDEP" and "Te-132" in i132.fields["ddep_reference"]
    top = max(db.gammas("I-132"), key=lambda g: g.intensity or 0)
    assert top.energy_kev == pytest.approx(667.714) and top.intensity == pytest.approx(0.987)
    # Gammas von Te-132 selbst enthalten keine I-132-Linie
    assert not any(abs(g.energy_kev - 667.714) < 0.01 for g in db.gammas("Te-132"))


def test_isomer_feeding_splits_branch(db):
    modes = {m.daughter: m for m in db.decay_modes("Cs-137")}
    assert modes["Ba-137m"].effective_branching == pytest.approx(0.947)
    assert modes["Ba-137m"].get("isomer_feeding") is True
    assert modes["Ba-137"].effective_branching == pytest.approx(0.053)
    assert set(db.chain("Cs-137").nuclides) == {"Cs-137", "Ba-137m", "Ba-137"}
    feeds = db.isomer_feedings("Cs-137")
    assert feeds and feeds[0]["isomer"] == "Ba-137m" and feeds[0]["method"] == "ENSDF-Niveaubilanz"


def test_isomer_feeding_not_applied_to_user_entries(db, tmp_path):
    from nucdb import NucDB
    own = NucDB(db.location, overlay=tmp_path / "ov")
    own.user.add_value("Cs-137", "half_life_s", "30.05 a")      # Werte ändern die Zweige nicht
    assert {m.daughter for m in own.decay_modes("Cs-137")} == {"Ba-137", "Ba-137m"}
