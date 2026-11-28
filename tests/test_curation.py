import pytest

from nucdb import NucDB
from nucdb.curation import Curation, apply, overlay_entries
from nucdb.fileformat import read_file, write_file
from nucdb.validate import validate


@pytest.fixture()
def cur(dbdir, tmp_path):
    return Curation(tmp_path / "curation", dbdir)


def _errors(root, **kw):
    return [i for i in validate(root, **kw) if i.level == "error"]


def test_source_is_mandatory(cur):
    with pytest.raises(ValueError, match="Quelle"):
        cur.add_value("Co-60", "half_life_s", "5.27 a", source="")
    with pytest.raises(ValueError, match="user"):
        cur.add_value("Co-60", "half_life_s", "5.27 a", source="user")
    with pytest.raises(ValueError, match="Unbekannte Quelle"):
        cur.add_value("Co-60", "half_life_s", "5.27 a", source="NEU")


def test_add_source_and_value_replaces_same_source(cur, dbdir):
    cur.add_source("LAB-2026", title="Eigene Messreihe 2026", citation="Labor, Bericht 7/2026", year=2026)
    cur.add_value("Co-60", "half_life_s", "1925.20(25) d", source="LAB-2026", comment="Messung")
    cur.add_value("Co-60", "half_life_s", "1925.25(25) d", source="LAB-2026")      # ersetzt
    db = NucDB(dbdir, overlay=False)
    co = db.nuclide("Co-60")
    assert co.preferred("half_life_s").source == "LAB-2026"
    assert co.half_life("d") == pytest.approx(1925.25)
    assert [v.source for v in co.values("half_life_s")].count("LAB-2026") == 1
    assert db.source("LAB-2026").citation == "Labor, Bericht 7/2026"
    log = read_file(dbdir / "changelog.json")[1]
    assert len(log) == 3 and "Quelle LAB-2026" in log[1]["comment"]
    assert not _errors(dbdir)


def test_curation_survives_rebuild_and_is_idempotent(cur, dbdir, tmp_path):
    cur.add_emission("gamma", "Bi-214", "1120.287(10) keV", intensity="14,9 %", source="TEST-B")
    before = (dbdir / "decay_gamma.json").read_text()
    apply(cur.location, dbdir)                                     # zweimal anwenden: gleich
    apply(cur.location, dbdir)
    assert (dbdir / "decay_gamma.json").read_text() == before
    # „Neuaufbau“: zentrale Datei auf Importstand zurücksetzen, Kuration erneut anwenden
    from conftest import GAMMAS
    write_file(dbdir / "decay_gamma.json", "decay_gamma", GAMMAS)
    apply(cur.location, dbdir)
    assert (dbdir / "decay_gamma.json").read_text() == before


def test_remove_central_line_needs_reason(cur, dbdir):
    with pytest.raises(ValueError, match="Begründung"):
        cur.remove_emission("gamma", "Co-60", 1332.50, "TEST-B", comment="")
    cur.remove_emission("gamma", "Co-60", 1332.50, "TEST-B", comment="Dublette")
    db = NucDB(dbdir, overlay=False)
    assert [g.source for g in db.gammas("Co-60", all_sources=True) if g.energy_kev == pytest.approx(1332.5)] == []
    assert cur.removals()[0]["comment"] == "Dublette"
    with pytest.raises(ValueError, match="Keine"):
        cur.remove_emission("gamma", "Co-60", 999.0, "TEST-A", comment="x")


def test_remove_value_and_readd(cur, dbdir):
    cur.remove_value("Co-60", "half_life_s", "TEST-B", comment="veraltet")
    assert [v.source for v in NucDB(dbdir, overlay=False).nuclide("Co-60").values("half_life_s")] == ["TEST-A"]
    cur.add_value("Co-60", "half_life_s", "5.2714 a", source="TEST-B", preferred=False)
    assert len(NucDB(dbdir, overlay=False).nuclide("Co-60").values("half_life_s")) == 2
    assert not cur.removals()


def test_add_nuclide_and_decay_mode(cur, dbdir):
    with pytest.raises(ValueError, match="Tochter"):
        cur.add_nuclide("Po-214", source="TEST-A", half_life="164.3 us", decays=[("Pb-210", 1.0, "A")])
    cur.add_nuclide("Pb-210", source="TEST-A", half_life="22.2 a")
    cur.add_nuclide("Po-214", source="TEST-A", half_life="164.3 us", decays=[("Pb-210", 1.0, "A")])
    db = NucDB(dbdir, overlay=False)
    assert db.nuclide("Po-214").half_life("us") == pytest.approx(164.3)
    assert db.chain("Rn-222").nuclides[-2:] == ("Po-214", "Pb-210")
    with pytest.raises(ValueError, match="schon"):
        cur.add_nuclide("Co-60", source="TEST-A")
    cur.add_decay_mode("Po-218", "At-218", 0.0003, mode="B-", source="TEST-A")
    assert {m.daughter: m.branching for m in NucDB(dbdir, overlay=False).decay_modes("Po-218")}["At-218"] == 0.0003
    assert not _errors(dbdir)


def test_non_redistributable_source_blocked_in_distributable_db(cur, dbdir, tmp_path):
    cur.distributable = False
    cur.add_source("PRIVAT", title="Interne Daten", redistributable=False)
    cur.add_emission("gamma", "Co-60", 100.0, intensity=0.01, source="PRIVAT")
    # Neuaufbau einer weitergebbaren DB lässt die Einträge weg
    write_file(dbdir / "sources.json", "sources",
               [s for s in read_file(dbdir / "sources.json")[1] if s["key"] != "PRIVAT"])
    from conftest import GAMMAS
    write_file(dbdir / "decay_gamma.json", "decay_gamma", GAMMAS)
    apply(cur.location, dbdir, distributable=True)
    assert "PRIVAT" not in (dbdir / "decay_gamma.json").read_text()
    assert not _errors(dbdir, distributable=True)
    cur2 = Curation(cur.location, dbdir)
    assert cur2.distributable
    with pytest.raises(ValueError, match="nicht weitergebbar"):
        cur2.add_value("Co-60", "half_life_s", 1.0, source="PRIVAT")


def test_adopt_overlay_entries(cur, db, dbdir):
    db.user.add_gamma("Bi-214", "1764.49(3) keV", intensity="15,3 %", note="eigene Messung")
    db.user.add_value("Co-60", "half_life_s", "1925.3(3) d")
    db.user.add_nuclide("Pb-210", half_life="22.2 a", stable=False)
    db.user.add_nuclide("Po-214", half_life="164.3 us", decays=[("Pb-210", 1.0, "A")])
    entries = overlay_entries(db.user, cur.central)
    kinds = sorted(e.kind for e in entries)
    assert kinds == ["gamma", "nuclide", "nuclide", "value"]
    po = next(e for e in entries if e.nuclide == "Po-214")
    with pytest.raises(ValueError, match="zuerst Pb-210"):
        cur.adopt(db.user, po, source="TEST-A")
    for e in entries:
        if e.nuclide != "Po-214":
            cur.adopt(db.user, e, source="TEST-B")
    cur.adopt(db.user, po, source="TEST-B")
    assert overlay_entries(db.user, cur.central) == []
    central = NucDB(dbdir, overlay=False)
    assert central.nuclide("Po-214").decay_source == "TEST-B"
    assert central.nuclide("Co-60").half_life("d") == pytest.approx(1925.3)
    assert any(g.source == "TEST-B" and g.energy_kev == pytest.approx(1764.49) for g in central.gammas("Bi-214", all_sources=True))
    assert "übernommen" in (db.user.location / "changelog.json").read_text()
    assert not _errors(dbdir)


def test_adopt_own_decays_of_central_nuclide(cur, db, dbdir):
    db.user.set_decays("Po-218", [("Pb-214", 1.0, "A")])
    entries = overlay_entries(db.user, cur.central)
    assert [(e.kind, e.nuclide) for e in entries] == [("decays", "Po-218")]
    cur.adopt(db.user, entries[0], source="TEST-B", comment="geprüft")
    assert overlay_entries(db.user, cur.central) == []
    central = NucDB(dbdir, overlay=False)
    assert central.nuclide("Po-218").decay_source == "TEST-B"
    assert [(m.daughter, m.source) for m in central.decay_modes("Po-218")] == [("Pb-214", "TEST-B")]
    assert len(central.decay_modes("Po-218", all_sources=True)) == 3        # TEST-A bleibt erhalten
    assert not _errors(dbdir)
    # übersteht den Neuaufbau (erneutes Anwenden) unverändert
    apply(cur.location, dbdir)
    assert [m.daughter for m in NucDB(dbdir, overlay=False).decay_modes("Po-218")] == ["Pb-214"]
