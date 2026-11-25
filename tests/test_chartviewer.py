"""Eigene Nuklidkarte: Kalibrierung, Kachelaufbau (im Cache), Fenster und Editor-Anbindung."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QPointF, QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from nucdb.gui import chartviewer as cv  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Cache und Einstellungen nur im Testordner."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    ini = str(tmp_path / "settings.ini")
    monkeypatch.setattr(cv.ChartWindow, "settings", staticmethod(lambda: QSettings(ini, QSettings.Format.IniFormat)))


def test_calibration_single_strip():
    c = cv.Calibration([])
    c.add("La-117", 440, 10111)             # N=60, Z=57
    assert not c.ready                       # ein Punkt reicht nicht
    c.add("Pb-180", 6935, 5821)              # N=98, Z=82
    assert c.ready
    pt = c.to_image(98, 82)
    assert (pt.x(), pt.y()) == pytest.approx((6935, 5821))
    assert c.to_nz(QPointF(6935 + 20, 5821 - 30)) == (98, 82)
    assert c.to_nz(QPointF(440, 10111 + 171 * 30)) is None      # weit außerhalb des Z-Bereichs
    w, h = c.cell_size()
    assert w == pytest.approx(170.9, abs=0.1) and h == pytest.approx(171.6, abs=0.1)


def test_calibration_strips_are_separate():
    c = cv.Calibration([])
    # Streifen 1: Z 0…20 unten links, Streifen 2: Z 21…40 versetzt rechts oben
    c.add("H-1", 100, 2000, 1)
    c.add("Ca-40", 100 + 20 * 50, 2000 - 20 * 50, 1)
    c.add("Sc-41", 3000, 1500, 2)
    c.add("Zr-90", 3000 + 30 * 50, 1500 - 19 * 50, 2)
    assert c.segment_ids() == [1, 2]
    co = c.to_image(33, 27)                  # Co-60 liegt in Streifen 2
    assert co.x() == pytest.approx(3000 + 13 * 50)
    assert c.to_nz(co) == (33, 27)
    assert c.to_nz(c.to_image(6, 6)) == (6, 6)   # C-12 in Streifen 1


def test_calibration_persists(tmp_path):
    c = cv.Calibration([])
    c.add("Co-60", 1.0, 2.0, 3)
    c.save(tmp_path)
    assert cv.Calibration.load(tmp_path).points == c.points
    assert cv.Calibration.load(tmp_path / "fehlt").points == []
    with pytest.raises(ValueError):
        c.add("Xx-1", 0, 0)


def _make_pdf(path):
    pymupdf = pytest.importorskip("pymupdf")
    pyvips = pytest.importorskip("pyvips")
    # Gitterbild 2000 x 1200 px (Kästchen 100 px), als „Scan“ in eine Seite gelegt
    img = pyvips.Image.black(2000, 1200) + 255
    for x in range(0, 2000, 100):
        img = img.draw_rect(0, x, 0, 3, 1200, fill=True)
    for y in range(0, 1200, 100):
        img = img.draw_rect(0, 0, y, 2000, 3, fill=True)
    png = img.cast("uchar").write_to_buffer(".png")
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=360)
    page.insert_image(page.rect, stream=png)
    doc.save(str(path))


def test_build_tiles_in_cache_not_next_to_pdf(tmp_path):
    if cv.missing_build_modules():
        pytest.skip("pymupdf/pyvips fehlen")
    pdf = tmp_path / "src" / "karte.pdf"
    pdf.parent.mkdir()
    _make_pdf(pdf)
    msgs = []
    dzi = cv.prepare(pdf, progress=lambda t, p: msgs.append(p))
    assert dzi.is_file() and str(dzi).startswith(str(tmp_path / "cache"))
    assert sorted(p.name for p in pdf.parent.iterdir()) == ["karte.pdf"]     # Quellordner unverändert
    src = cv.TileSource(dzi)
    assert (src.width, src.height) == (2000, 1200)
    assert max(msgs) == 100
    assert cv.prepare(pdf) == dzi                                            # zweites Mal: sofort
    os.utime(pdf, (time.time() + 10, time.time() + 10))                     # PDF ersetzt → neuer Cache
    assert cv.ready_dzi(pdf) is None


def test_chart_window_open_calibrate_jump(qapp, tmp_path):
    if cv.missing_build_modules():
        pytest.skip("pymupdf/pyvips fehlen")
    pdf = tmp_path / "karte.pdf"
    _make_pdf(pdf)
    w = cv.ChartWindow(has_nuclide=lambda n: True)
    w.resize(800, 600)
    w.show()
    w.open_file(pdf)                          # Kacheln im Hintergrund-Thread
    assert w.wait_for_builder(60000)
    for _ in range(50):
        qapp.processEvents()
        if w.viewer is not None:
            break
        time.sleep(0.05)
    assert w.viewer is not None and w.last_file() == pdf.resolve()
    w.add_calibration_point("H-1", QPointF(50, 1150), 1)           # N=0, Z=1
    w.add_calibration_point("O-16", QPointF(850, 450), 1)          # N=8, Z=8
    picked = []
    w.nuclide_picked.connect(picked.append)
    assert w.show_nuclide("C-12")
    c, half, text = w.viewer.marker
    assert (c.x(), c.y()) == pytest.approx((650, 650)) and text == "C-12"
    w._clicked(QPointF(655, 640))
    assert picked == ["C-12"]
    # Kalibrierung liegt beim Cache und wird beim nächsten Öffnen geladen
    w2 = cv.ChartWindow()
    w2.open_file(pdf)
    assert w2.calibration.ready
    w.close()
    w2.close()


def test_editor_follows_selection(qapp, db, tmp_path, monkeypatch):
    if cv.missing_build_modules():
        pytest.skip("pymupdf/pyvips fehlen")
    from nucdb.gui.main_window import MainWindow
    pdf = tmp_path / "karte.pdf"
    _make_pdf(pdf)
    cv.prepare(pdf)
    cv.ChartWindow.settings().setValue(cv.ChartWindow.SETTINGS_KEY, str(pdf.resolve()))
    win = MainWindow(db, None)
    win.open_chart()
    chart = win.chart
    assert chart.viewer is not None                          # zuletzt gewählte Karte geöffnet
    chart.add_calibration_point("H-1", QPointF(50, 1150), 1)
    chart.add_calibration_point("O-16", QPointF(850, 450), 1)
    win.select_nuclide("Ne-22")                               # N=12, Z=10 → außerhalb des Bildes, egal
    assert chart.viewer.marker[2] == "Ne-22"
    chart.nuclide_picked.emit("Co-60")
    assert win.current == "Co-60"
    win.close()
    assert not chart.isVisible()
