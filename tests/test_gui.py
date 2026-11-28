"""Editor-Oberfläche, ohne Bildschirm (Qt offscreen). Übersprungen, wenn PySide6 fehlt."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from nucdb import NucDB  # noqa: E402
from nucdb.curation import Curation  # noqa: E402
from nucdb.gui.dialogs import parse_decays  # noqa: E402
from nucdb.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def win(qapp, db, dbdir, tmp_path):
    w = MainWindow(db, Curation(tmp_path / "curation", dbdir))
    yield w
    w.close()


def test_browse_and_search(win):
    assert win.nuc_model.rowCount() == 13
    win.search.setText("60Co")
    assert win.current == "Co-60"
    assert win.val_model.rowCount() == 2                     # T½ und Masse (bevorzugt)
    assert win.em_views["gamma"][1].rowCount() == 2
    win.all_sources.setChecked(True)
    assert win.val_model.rowCount() == 3
    win.search.setText("z=1")
    assert win.nuc_proxy.rowCount() == 2


def test_peak_search(win):
    win.peak_energy.setText("609,3")
    win.peak_search()
    assert any(getattr(m.line, "nuclide", None) == "Bi-214" for m in win.peak_model.rows)


def test_add_own_gamma_via_dialog(win, db):
    win.select_nuclide("Bi-214")
    d = win.make_emission_dialog("gamma", "1120.29(1) keV")
    d.intensity.setText("45.5")                               # Prozent als Zahl → Fehler bleibt im Dialog
    assert not d.try_accept() and "Bruchteil" in d.error.text()
    d.intensity.setText("14,9 %")
    assert d.try_accept()
    win._after_write("ok")
    assert [e.kind for e in win.ov_model.rows] == ["gamma"]
    assert any(g.user for g in db.gammas("Bi-214"))


def test_central_value_requires_source(win, dbdir):
    win.target.setCurrentIndex(1)
    assert win.central
    win.select_nuclide("Co-60")
    d = win.make_value_dialog("half_life_s")
    d.value.setText("1925.3(3) d")
    assert not d.try_accept() and "Quelle" in d.error.text()
    d.source.set_key("TEST-B")
    assert d.try_accept()
    win._after_write("ok")
    assert NucDB(dbdir, overlay=False).nuclide("Co-60").preferred("half_life_s").source == "TEST-B"
    assert any(r[0] == "zentral" for r in win.log_model.rows)


def test_parse_decays():
    assert parse_decays("Tc-99m 0.8773 B-\nTc-99 12,27 %\n") == [("Tc-99m", 0.8773, "B-"),
                                                                ("Tc-99", pytest.approx(0.1227))]
    with pytest.raises(ValueError):
        parse_decays("nur-ein-feld")


def test_own_decays_via_dialog(win, db):
    win.target.setCurrentIndex(0)                            # Ziel: Overlay
    assert not win.central
    win.select_nuclide("Po-218")
    d = win.make_own_decays_dialog()
    assert "Pb-214" in d.decays.toPlainText() and "At-218" in d.decays.toPlainText()
    d.decays.setPlainText("Pb-214 100 % A")
    assert d.try_accept()
    win._after_write("ok")
    assert [(m.daughter, m.user) for m in db.decay_modes("Po-218")] == [("Pb-214", True)]
    assert [e.kind for e in win.ov_model.rows] == ["decays"]
    assert win.dec_model.rowCount() == 1


def test_parse_decays_unknown_fraction():
    assert parse_decays("At-218 ? B-") == [("At-218", None, "B-")]
