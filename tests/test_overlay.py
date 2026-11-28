import pytest

from nucdb import NucDB
from nucdb.validate import validate


def test_add_user_nuclide_visible_to_other_instances(db, dbdir, tmp_path):
    db.user.add_nuclide("Mo-99", half_life="65,94 h", decays=[("Tc-99m", 0.8773, "B-"), ("Tc-99", 0.1227)])
    mo = db.nuclide("99Mo")
    assert mo.user and mo.half_life("h") == pytest.approx(65.94)
    assert {m.daughter for m in db.decay_modes("Mo-99")} == {"Tc-99m", "Tc-99"}
    # Ein anderes Tool (neue Instanz) sieht den Eintrag ebenfalls
    other = NucDB(dbdir, overlay=tmp_path / "overlay")
    assert other.nuclide("Mo-99").user
    assert other.chain("Mo-99").nuclides[:2] == ("Mo-99", "Tc-99m")
    # Zentrale Datei unverändert
    assert "Mo-99" not in (dbdir / "nuclides.json").read_text()
    assert not [i for i in validate(tmp_path / "overlay", overlay=True) if i.level == "error"]


def test_half_life_as_decay_constant(db):
    db.user.add_nuclide("Xe-135", half_life="2.1066e-5 1/s", stable=False)
    assert db.nuclide("Xe-135").half_life("h") == pytest.approx(9.14, rel=1e-3)


def test_unknown_daughter_rejected(db):
    with pytest.raises(ValueError, match="unbekannt"):
        db.user.add_nuclide("Sr-90", half_life="28.79 a", decays=[("Y-90", 1.0)])


def test_central_nuclide_cannot_be_redefined(db):
    with pytest.raises(ValueError, match="zentralen"):
        db.user.add_nuclide("Co-60", half_life="5 a")


def test_user_value_overrides_preferred(db):
    db.user.add_value("Co-60", "half_life_s", "1925.3(3) d")
    co = db.nuclide("Co-60")
    assert co.preferred("half_life_s").user
    assert co.half_life("d") == pytest.approx(1925.3)
    assert len(co.values("half_life_s")) == 3
    with pytest.raises(ValueError):
        db.user.add_value("Co-60", "no_such_quantity", 1)


def test_remove_user_nuclide(db):
    db.user.add_nuclide("Y-90", half_life="64.05 h", decays=[])
    db.user.add_nuclide("Sr-90", half_life="28.79 a", decays=[("Y-90", 1.0)])
    with pytest.raises(ValueError, match="Tochter"):
        db.user.remove_nuclide("Y-90")
    db.user.remove_nuclide("Sr-90")
    assert not db.has_nuclide("Sr-90")
    with pytest.raises(ValueError):
        db.user.remove_nuclide("Co-60")


def test_changelog_written(db, tmp_path):
    db.user.add_nuclide("Y-90", half_life="64.05 h", comment="Test")
    assert "Y-90" in (tmp_path / "overlay" / "changelog.json").read_text()


# --- eigene Linien (1.1) ---------------------------------------------------------------------

def test_add_gamma_visible_everywhere(db, dbdir, tmp_path):
    rec = db.user.add_gamma("Bi-214", "1,7645 MeV", intensity="15,3 %", note="eigene Messung")
    assert rec["energy_kev"] == pytest.approx(1764.5) and rec["intensity"] == pytest.approx(0.153)
    mine = [g for g in db.gammas("Bi-214") if g.user]
    assert len(mine) == 1 and mine[0].source == "user" and mine[0].radiation == "G" and mine[0].note == "eigene Messung"
    m = db.find_gammas(1764.5, 0.2)
    assert any(x.line.user for x in m if x.kind == "decay")
    other = NucDB(dbdir, overlay=tmp_path / "overlay")          # anderes Tool sieht die Linie
    assert any(g.user for g in other.gammas("Bi-214"))
    assert "1764.5" not in (dbdir / "decay_gamma.json").read_text()   # zentrale Datei unverändert


def test_add_gamma_with_uncertainty_and_replace(db):
    db.user.add_gamma("Co-60", "1332.50(3) keV", intensity=0.9998)
    db.user.add_gamma("Co-60", 1332.5, intensity=0.5)               # gleiche Energie → ersetzt
    mine = [g for g in db.gammas("Co-60") if g.user]
    assert len(mine) == 1 and mine[0].intensity == 0.5
    assert db.user.emissions("gamma", "Co-60")[0]["energy_kev"] == pytest.approx(1332.5)


def test_add_gamma_unknown_intensity_and_errors(db):
    db.user.add_gamma("Na-22", 1274.6)
    assert [g.intensity for g in db.gammas("Na-22") if g.user] == [None]
    with pytest.raises(ValueError, match="Unbekanntes Nuklid"):
        db.user.add_gamma("Cs-137", 661.7)
    with pytest.raises(ValueError, match="positiv"):
        db.user.add_gamma("Co-60", 0)
    with pytest.raises(ValueError, match="Bruchteil"):
        db.user.add_gamma("Co-60", 100.0, intensity=45.5)           # Prozent als Zahl verwechselt
    with pytest.raises(ValueError, match="type"):
        db.user.add_emission("beta", "Co-60", 318)


def test_remove_gamma_only_own(db):
    db.user.add_gamma("Bi-214", 1764.5, intensity=0.15)
    assert db.user.remove_gamma("Bi-214", 1764.5) == 1
    assert not [g for g in db.gammas("Bi-214") if g.user]
    with pytest.raises(ValueError, match="Keine eigene"):
        db.user.remove_gamma("Bi-214", 609.312)                     # zentrale Linie bleibt


def test_add_beta_and_alpha(db):
    db.user.add_emission("beta", "Co-60", "317.9 keV", intensity=0.9988, type="B-", mean_energy_kev=95.8)
    b = [x for x in db.betas("Co-60") if x.user][0]
    assert b.type == "B-" and b.mean_energy_kev == 95.8
    db.user.add_emission("alpha", "Rn-222", "5489.5 keV", intensity="99,92 %")
    assert any(a.user for a in db.alphas("Rn-222"))


def test_lock_blocks_and_stale_lock_is_taken_over(db, monkeypatch, tmp_path):
    import os, time
    from nucdb import overlay
    lock = tmp_path / "overlay" / overlay.LOCK_NAME
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("fremd")
    monkeypatch.setattr(overlay, "LOCK_TIMEOUT_S", 0.2)
    with pytest.raises(overlay.OverlayLockedError):
        db.user.add_gamma("Co-60", 1000.0)
    old = time.time() - overlay.LOCK_STALE_S - 5
    os.utime(lock, (old, old))                                      # abgestürztes Programm
    db.user.add_gamma("Co-60", 1000.0)
    assert not lock.exists()


def test_reload_if_changed(db, dbdir, tmp_path):
    other = NucDB(dbdir, overlay=tmp_path / "overlay")
    other.gammas("Co-60")                                           # Zwischenspeicher füllen
    assert not other.overlay_changed()
    db.user.add_gamma("Co-60", 1000.0, intensity=0.01)
    assert other.overlay_changed()
    assert not any(g.user for g in other.gammas("Co-60"))           # noch alter Stand
    assert other.reload_if_changed() is True
    assert any(g.user for g in other.gammas("Co-60"))
    assert other.reload_if_changed() is False


def test_own_decays_replace_central_branches(db, dbdir, tmp_path):
    ch = db.chain("Rn-222")
    assert "At-218" in ch.nuclides
    db.user.set_decays("Po-218", [("Pb-214", 1.0, "A")], comment="eigene Auswertung")
    modes = db.decay_modes("Po-218")
    assert [(m.daughter, m.branching, m.user) for m in modes] == [("Pb-214", 1.0, True)]
    assert len(db.decay_modes("Po-218", all_sources=True)) == 3
    assert "At-218" not in db.chain("Rn-222").nuclides
    # Andere Tools sehen es ebenfalls, die zentrale Datei bleibt unverändert
    other = NucDB(dbdir, overlay=tmp_path / "overlay")
    assert [m.daughter for m in other.decay_modes("Po-218")] == ["Pb-214"]
    assert "At-218" in (dbdir / "decay_modes.json").read_text()
    assert db.user.has_own_decays("Po-218") and not db.nuclide("Po-218").user
    # erneut setzen ersetzt, entfernen stellt die zentralen Zweige wieder her
    db.user.set_decays("Po-218", [("Pb-214", 0.9, "A", 0.01), ("At-218", None, "B-")])
    assert [(m.daughter, m.branching_unc) for m in db.decay_modes("Po-218")] == [("Pb-214", 0.01), ("At-218", None)]
    assert db.user.remove_decays("Po-218") == 2
    assert {m.daughter for m in db.decay_modes("Po-218")} == {"Pb-214", "At-218"}
    assert not any(m.user for m in db.decay_modes("Po-218"))
    assert not [i for i in validate(tmp_path / "overlay", overlay=True) if i.level == "error"]


def test_own_decays_errors(db):
    with pytest.raises(ValueError, match="stabil"):
        db.user.set_decays("Ni-60", [("Co-60", 1.0)])
    with pytest.raises(ValueError, match="unbekannt"):
        db.user.set_decays("Co-60", [("Ni-61", 1.0)])
    with pytest.raises(ValueError, match="remove_decays"):
        db.user.set_decays("Co-60", [])
    with pytest.raises(ValueError, match="Bruchteil"):
        db.user.set_decays("Co-60", [("Ni-60", 99.9)])
    with pytest.raises(ValueError, match="keine eigenen"):
        db.user.remove_decays("Co-60")
    with pytest.raises(ValueError, match="Unbekanntes"):
        db.user.set_decays("Sr-90", [("Ni-60", 1.0)])


def test_own_decays_skip_isomer_feeding(tmp_path):
    """Grunddatenbank: Mo-99 wird sonst automatisch auf Tc-99m/Tc-99 aufgeteilt."""
    db = NucDB(overlay=tmp_path / "ov")
    assert any(m.fields.get("isomer_feeding") for m in db.decay_modes("Mo-99"))
    db.user.set_decays("Mo-99", [("Tc-99m", 0.8775, "B-"), ("Tc-99", 0.1225, "B-")], comment="Zertifikat")
    modes = db.decay_modes("Mo-99")
    assert sorted((m.daughter, m.effective_branching) for m in modes) == [("Tc-99", 0.1225), ("Tc-99m", 0.8775)]
    assert all(m.user for m in modes)
