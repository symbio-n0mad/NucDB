import json
import math

import pytest

from nucdb import NucDB, UnknownNuclideError, physics
from nucdb.db import IncompatibleSchemaError
from nucdb.fileformat import dumps_file, read_file
from nucdb.validate import validate


def test_open_and_versions(db):
    assert db.data_version == "2026.11.0"
    assert db.schema_version.startswith("1.")


def test_nuclide_lookup_any_spelling(db):
    co = db.nuclide("60co")
    assert co.name == "Co-60" and co.z == 27 and co.n == 33
    with pytest.raises(UnknownNuclideError):
        db.nuclide("Cs-137")


def test_preferred_value_and_all_sources(db):
    co = db.nuclide("Co-60")
    assert co.half_life("a") == pytest.approx(5.2711)
    vals = co.values("half_life_s")
    assert [v.source for v in vals] == ["TEST-A", "TEST-B"] and vals[0].preferred and not vals[1].preferred


def test_single_value_counts_as_preferred(db):
    assert db.nuclide("Na-22").preferred("half_life_s").preferred


def test_decay_constant_and_stable(db):
    rn = db.nuclide("Rn-222")
    assert rn.decay_constant("1/h") == pytest.approx(math.log(2) / (3.8235 * 24))
    ni = db.nuclide("Ni-60")
    assert ni.half_life_s == math.inf and ni.decay_constant() == 0.0
    assert ni.format_half_life() == "stabil"


def test_gammas_only_preferred_source(db):
    lines = db.gammas("Co-60")
    assert [l.source for l in lines] == ["TEST-A", "TEST-A"]
    assert len(db.gammas("Co-60", all_sources=True)) == 3
    assert db.gammas("Co-60")[0].radiation == "G"


def test_betas_endpoint_and_mean(db):
    (b,) = db.betas("Co-60")
    assert b.energy_kev == 317.32 and b.mean_energy_kev == 95.77


def test_find_gammas_with_escape_and_special(db):
    m = db.find_gammas(609.3, tol_kev=1.0)
    assert m[0].kind == "decay" and m[0].line.nuclide == "Bi-214"
    se = db.find_gammas(1332.492 - physics.ELECTRON_MASS_KEV, tol_kev=0.5)
    assert any(x.kind == "single_escape" and x.line.nuclide == "Co-60" for x in se)
    de = db.find_gammas(1764.494 - 2 * physics.ELECTRON_MASS_KEV, tol_kev=0.5)
    assert any(x.kind == "double_escape" and x.line.nuclide == "Bi-214" for x in de)
    ann = db.find_gammas(511.0, tol_kev=0.5)
    assert ann[0].kind == "special" and ann[0].line.kind == "annihilation"
    assert not any(x.kind == "decay" for x in ann)              # ANN-Linien standardmäßig aus
    assert any(x.kind == "decay" for x in db.find_gammas(511.0, 0.5, include_annihilation=True))
    pb = db.find_gammas(74.97, tol_kev=0.1)
    assert pb and pb[0].line.origin == "Pb"


def test_find_gammas_never_returns_prompt(db):
    assert not any(m.kind == "prompt" for m in db.find_gammas(2223.2, tol_kev=1.0))
    p = db.find_prompt_gammas(2223.2, tol_kev=1.0)
    assert p and p[0].line.target == "H-1" and p[0].line.product == "H-2"
    assert db.prompt_gammas(element="h")[0].sigma_partial_b == 0.3326


def test_prompt_file_loaded_lazily(db):
    db.find_gammas(609.3)
    assert "prompt" not in db._cache
    db.prompt_gammas()
    assert "prompt" in db._cache


def test_chain_branching_and_order(db):
    ch = db.chain("Rn-222")
    order = list(ch.nuclides)
    assert order[0] == "Rn-222"
    assert order.index("Pb-214") < order.index("Bi-214") and order.index("At-218") < order.index("Bi-214")
    assert ch.unknown == ("Po-214",)          # fehlt in der Test-DB -> Datenfehler, nicht "stabil"
    assert {e.daughter for e in ch.daughters("Po-218")} == {"Pb-214", "At-218"}


def test_isomer_chain(db):
    ch = db.chain("99mTc")
    assert ch.nuclides == ("Tc-99m", "Tc-99")
    assert ch.open_ends == ("Tc-99",)        # Zerfall von Tc-99 fehlt in der Test-DB


def test_elements_and_sources(db):
    assert db.element("fe").name_de == "Eisen"
    assert db.element(92).symbol == "U"
    assert db.source("CODATA2018").redistributable
    assert "half_life_s" in db.quantities()


def test_special_lines(db):
    assert db.special_lines("sum")[0].energy_kev == pytest.approx(1021.9979)
    assert physics.backscatter(661.657) == pytest.approx(184.3, abs=0.1)
    assert physics.compton_edge(661.657) == pytest.approx(477.3, abs=0.1)


def test_validate_fixture_is_clean_except_expected(dbdir):
    issues = validate(dbdir)
    assert not [i for i in issues if i.level == "error"]
    assert any("Tochter Po-214 fehlt" in i.message for i in issues)


def test_validate_detects_problems(dbdir):
    head, recs = read_file(dbdir / "nuclides.json")
    recs.append({"name": "60Co", "z": 27, "a": 60, "values": {"half_life_s": [
        {"value": 1, "source": "NOPE"}, {"value": 2, "source": "TEST-A"}]}})
    (dbdir / "nuclides.json").write_text(dumps_file("nuclides", recs))
    msgs = " | ".join(i.message for i in validate(dbdir))
    assert "nicht kanonisch" in msgs and "unbekannte Quelle" in msgs and "bevorzugt" in msgs
    assert "Prüfsumme" in msgs


def test_canonical_file_format_roundtrip(dbdir):
    text = (dbdir / "decay_gamma.json").read_text()
    lines = text.splitlines()
    assert lines[0].startswith('{"format": "nucdb/decay_gamma"')
    assert lines[1] == ' "records": ['
    assert json.loads(text)["records"][0]["nuclide"] == "Na-22"   # sortiert nach Z
    # Schreiben ist stabil: zweimal schreiben ergibt denselben Text
    head, recs = read_file(dbdir / "decay_gamma.json")
    assert dumps_file("decay_gamma", recs) == text


def test_hand_edited_json_is_readable(dbdir, tmp_path):
    # Andere Tools dürfen die Datei beliebig formatieren
    data = json.loads((dbdir / "nuclides.json").read_text())
    (dbdir / "nuclides.json").write_text(json.dumps(data, indent=4))
    assert NucDB(dbdir, overlay=False).nuclide("Co-60").half_life("a") == pytest.approx(5.2711)


def test_incompatible_schema(dbdir):
    m = json.loads((dbdir / "manifest.json").read_text())
    m["schema_version"] = "9.0.0"
    (dbdir / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(IncompatibleSchemaError):
        NucDB(dbdir, overlay=False)


def test_package_snapshot_is_valid():
    from nucdb.locate import PACKAGE_DATA
    assert not [i for i in validate(PACKAGE_DATA) if i.level == "error"]
    assert NucDB(PACKAGE_DATA, overlay=False).special_lines("annihilation")


def test_find_gammas_ranking_and_filters(db):
    # Bewertung: Intensität × Abstand – die starke Linie gewinnt, auch wenn eine schwache näher liegt
    m = db.find_gammas(1332.5, tol_kev=1.0)
    assert m[0].line.source == "TEST-A" and m[0].score > 0
    assert db.find_gammas(609.3, 1.0, nuclides=["Co-60"]) == [] or \
        all(x.line.nuclide == "Co-60" for x in db.find_gammas(609.3, 1.0, nuclides=["Co-60"]) if x.kind != "special")
    assert not db.find_gammas(609.3, 1.0, min_half_life_s=86400, include_special=False)  # Bi-214 zu kurzlebig
    by_delta = db.find_gammas(1332.5, tol_kev=1.0, sort="delta")
    assert abs(by_delta[0].delta_kev) <= abs(by_delta[-1].delta_kev)


def test_chain_practically_stable(db):
    from nucdb import PRACTICALLY_STABLE_S, units
    ch = db.chain("99mTc", stable_above_s=1e5 * units.YEAR_S)       # Tc-99: 2,1·10⁵ a
    assert ch.nuclides == ("Tc-99m", "Tc-99")
    assert ch.practically_stable == ("Tc-99",) and ch.open_ends == ()
    assert db.chain("99mTc").practically_stable == ()
    assert db.nuclide("Tc-99").practically_stable(1e5 * units.YEAR_S)
    assert not db.nuclide("Tc-99").practically_stable()
    assert db.nuclide("Ni-60").practically_stable() and PRACTICALLY_STABLE_S > 3e22
    # Die Mutter selbst wird immer verfolgt
    assert db.chain("Tc-99", stable_above_s=1.0).practically_stable == ()


def test_chain_np237_ends_at_bi209_in_package_db():
    from nucdb import PRACTICALLY_STABLE_S
    db = NucDB(overlay=False)
    assert db.chain("Np-237").nuclides[-1] == "Tl-205"
    ch = db.chain("Np-237", stable_above_s=PRACTICALLY_STABLE_S)
    assert ch.practically_stable == ("Bi-209",) and not ch.daughters("Bi-209")
    assert db.nuclide("Bi-209").half_life_s < float("inf")             # Daten bleiben unverändert
