"""Flüssiger Viewer für eigene Nuklidkarten (riesige Bild-PDFs), mit Kalibrierung auf N/Z.

NucDB verteilt keine Nuklidkarte (Urheber- und Datenbankrecht). Wer eine eigene hat (z. B. die
Karlsruher Nuklidkarte als PDF der Uni), kann sie hier zum Vergleich und zur Recherche anzeigen.

Prinzip (nach ``nebenprojekte/show-pdf.py``): Die PDF-Seite wird **einmalig** in eine
Deep-Zoom-Kachelpyramide (512-px-JPEG-Kacheln in allen Zoomstufen) zerlegt. Der Viewer lädt dann nur
die sichtbaren Kacheln in passender Auflösung im Hintergrund. Egal wie groß das Original ist,
verarbeitet wird immer nur ungefähr Bildschirmgröße.

- Die Kacheln liegen im Cache des Benutzers (``~/.cache/nucdb/charts/…``), nie neben der PDF.
- Mit zwei (oder mehr) angeklickten bekannten Nukliden wird die Karte auf N/Z kalibriert. Dann
  zeigt der Viewer unter der Maus das Nuklid an, und der Editor kann zu jedem Nuklid springen.

Zum Erzeugen der Kacheln braucht es ``pymupdf`` und ``pyvips`` (Extra ``chart``); zum Anzeigen nur
PySide6. Eigenständig: ``python -m nucdb.gui.chartviewer karte.pdf``.

Bedienung: Mausrad/Pinch Zoom zur Maus · Ziehen verschieben · Doppelklick 2× · F einpassen ·
1 = 100 % · +/- zoomen · Pfeiltasten verschieben.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import xml.etree.ElementTree as ET
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QRunnable, QSettings, Qt, QThread, QThreadPool, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QFileDialog, QInputDialog, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QProgressDialog, QSpinBox, QToolBar, QWidget)

from .. import elements, names

TILE_SIZE = 512        # Kantenlänge der Kacheln beim Erzeugen
CACHE_TILES = 400      # Kacheln im Speicher (je ca. 1 MB)
MAX_ZOOM = 16.0        # max. Bildschirmpixel pro Bildpixel
OVERVIEW_MAX = 1024    # Übersichtsstufe, die immer im Speicher liegt
CALIBRATION = "calibration.json"
SEGMENT_COLORS = [QColor(0, 140, 255), QColor(0, 170, 60), QColor(200, 0, 200), QColor(255, 130, 0),
                  QColor(0, 170, 170), QColor(120, 80, 0)]

Progress = Callable[[str, int], None]      # (Text, Prozent 0…100 oder -1)


def _print_progress(text: str, pct: int) -> None:
    print(f"\r{text} {pct:3d} %" if pct >= 0 else text, end="" if pct >= 0 else "\n", flush=True)


def missing_build_modules() -> list[str]:
    """Module, die zum Erzeugen der Kacheln fehlen (leer = alles da)."""
    out = []
    for mod in ("pymupdf", "pyvips"):
        try:
            __import__(mod)
        except Exception:  # noqa: BLE001 - pyvips meldet fehlende libvips als OSError
            out.append(mod)
    return out


# ============================================================ Cache

def cache_root() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    return base / "nucdb" / "charts"


def tiles_dir(pdf: Path, page: int = 1, render: bool = False) -> Path:
    """Cache-Ordner für eine PDF-Seite; ändert sich, wenn die PDF ersetzt wird."""
    pdf = Path(pdf).resolve()
    st = pdf.stat()
    key = hashlib.sha1(f"{pdf}|{st.st_size}|{st.st_mtime_ns}|{page}|{render}".encode()).hexdigest()[:16]
    return cache_root() / f"{pdf.stem}-{key}"


def ready_dzi(path: Path, page: int = 1, render: bool = False) -> Path | None:
    """Fertige .dzi für eine PDF (oder die .dzi selbst), sonst ``None``."""
    path = Path(path)
    if path.suffix.lower() == ".dzi":
        return path if path.is_file() else None
    dzi = tiles_dir(path, page, render) / f"{path.stem}.dzi"
    return dzi if dzi.is_file() else None


def prepare(path: Path, page: int = 1, render: bool = False, rebuild: bool = False,
            progress: Progress = _print_progress) -> Path:
    """Pfad zur .dzi liefern; erzeugt die Kacheln, wenn nötig (einmalig, kann Minuten dauern)."""
    path = Path(path)
    if path.suffix.lower() == ".dzi":
        return path
    dzi = None if rebuild else ready_dzi(path, page, render)
    return dzi or build_tiles(path, tiles_dir(path, page, render), page - 1, render, progress)


# ============================================================ Kacheln erzeugen

def build_tiles(pdf: Path, out_dir: Path, page_no: int = 0, render: bool = False,
                progress: Progress = _print_progress) -> Path:
    """Zerlegt eine PDF-Seite einmalig in eine Deep-Zoom-Pyramide (JPEG-Kacheln)."""
    import gc
    import tempfile

    import pymupdf

    doc = pymupdf.open(str(pdf))
    if not 0 <= page_no < len(doc):
        raise ValueError(f"{pdf.name} hat nur {len(doc)} Seite(n)")
    page = doc[page_no]
    main = _main_image(page)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    base = out_dir / pdf.stem

    try:
        with tempfile.TemporaryDirectory(dir=out_dir, ignore_cleanup_errors=True) as tmp:
            img = None
            if main and not render:
                progress("Lese eingebettetes Bild …", -1)
                img = _extract(doc, page, main, progress)
            if img is None:
                if main:   # native Auflösung des Scans
                    dpi = max(main["w"], main["h"]) * 72 / max(main["rect"].width, main["rect"].height)
                else:
                    dpi = 300
                img = _render_strips(page, max(72.0, dpi), Path(tmp), progress)
            img = _normalize(img)

            text = f"Erzeuge Kacheln für {img.width} × {img.height} px (einmalig) …"
            progress(text, 0)
            last = [-1]

            def on_eval(_im, p):
                if p.percent != last[0]:
                    last[0] = p.percent
                    progress(text, int(p.percent))

            img.set_progress(True)
            img.signal_connect("eval", on_eval)
            img.dzsave(str(base), tile_size=TILE_SIZE, overlap=0, suffix=".jpg[Q=90]")
            progress("Kacheln fertig.", -1)
            del img
            gc.collect()       # Dateien freigeben, bevor der Temp-Ordner gelöscht wird (Windows)
    except BaseException:
        shutil.rmtree(out_dir, ignore_errors=True)     # keine halbe Pyramide zurücklassen
        raise
    (out_dir / "source.json").write_text(json.dumps({"pdf": str(Path(pdf).resolve()), "page": page_no + 1,
                                                     "render": render}, ensure_ascii=False))
    return out_dir / f"{pdf.stem}.dzi"


def _main_image(page):
    """Größtes Bild der Seite, falls es fast die ganze Seite füllt (ohne es zu dekodieren)."""
    images = page.get_images(full=True)
    if not images:
        return None
    best = max(images, key=lambda i: i[2] * i[3])
    try:
        rect = page.get_image_bbox(best)
    except Exception:  # noqa: BLE001
        return None
    if rect.is_empty or rect.is_infinite:
        return None
    if rect.width * rect.height < 0.8 * page.rect.width * page.rect.height:
        return None
    return {"xref": best[0], "w": best[2], "h": best[3], "rect": rect}


def _extract(doc, page, main, progress: Progress):
    """Eingebettetes Bild 1:1 übernehmen (schnell, wenig RAM). None, wenn das nicht sauber geht."""
    import pyvips

    try:
        data = doc.extract_image(main["xref"])["image"]
        img = pyvips.Image.new_from_buffer(data, "")
    except Exception:  # noqa: BLE001
        return None            # Format, das pyvips nicht lesen kann (JPX, JBIG2, ...)
    rot = {90: "rot90", 180: "rot180", 270: "rot270"}.get(page.rotation)
    if rot:
        img = getattr(img, rot)()

    # Gegenprobe: sieht das extrahierte Bild aus wie die gerenderte Seite?
    # (fängt gespiegelte/gedrehte Platzierung, invertierte Farben, Overlays ab)
    try:
        ref, _ref_pix = _pix_to_vips(page.get_pixmap(matrix=_fit_matrix(page, 256), alpha=False))
        thumb = pyvips.Image.thumbnail_buffer(data, max(img.width, img.height) // 8 + 1)
        if rot:
            thumb = getattr(thumb, rot)()
        thumb = _normalize(thumb).resize(ref.width / thumb.width, vscale=ref.height / thumb.height)
        if thumb.bands != ref.bands:
            thumb, ref = thumb.colourspace("srgb"), ref.colourspace("srgb")
        diff = (thumb - ref).abs().avg()
    except Exception:  # noqa: BLE001
        diff = 255
    if diff > 20:
        progress("Extrahiertes Bild weicht von der Seitenansicht ab, rendere stattdessen.", -1)
        return None
    return img


def _render_strips(page, dpi, tmp: Path, progress: Progress):
    """Seite in Streifen rendern (MuPDF verweigert riesige Pixmaps am Stück)."""
    import pymupdf
    import pyvips

    zoom = dpi / 72
    r = page.rect
    total_w, total_h = round(r.width * zoom), round(r.height * zoom)
    rows = max(64, 100_000_000 // (total_w * 3))          # ca. 100 MB pro Streifen
    text = f"Rendere Seite mit {dpi:.0f} dpi ({total_w} × {total_h} px) …"
    files, y = [], 0
    while y < total_h:
        h = min(rows, total_h - y)
        clip = pymupdf.Rect(r.x0, r.y0 + y / zoom, r.x1, r.y0 + (y + h) / zoom)
        strip, _pix = _pix_to_vips(page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip, alpha=False))
        strip = strip.crop(0, 0, min(strip.width, total_w), min(strip.height, h))
        if (strip.width, strip.height) != (total_w, h):        # Rundung um 1 px ausgleichen
            strip = strip.embed(0, 0, total_w, h, extend="copy")
        f = tmp / f"{len(files):05d}.v"
        strip.write_to_file(str(f))
        files.append(f)
        y += h
        progress(text, 100 * y // total_h)
    strips = [pyvips.Image.new_from_file(str(f)) for f in files]
    # arrayjoin macht alle Zellen so hoch wie den höchsten Streifen -> zurechtschneiden
    return pyvips.Image.arrayjoin(strips, across=1).crop(0, 0, total_w, total_h)


def _fit_matrix(page, size):
    import pymupdf
    z = size / max(page.rect.width, page.rect.height)
    return pymupdf.Matrix(z, z)


def _pix_to_vips(pix):
    """PyMuPDF-Pixmap -> pyvips-Bild. Gibt (bild, pixmap) zurück; die Pixmap muss leben, solange das Bild benutzt wird."""
    import pymupdf
    import pyvips

    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)
    if pix.n not in (1, 3):
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    img = pyvips.Image.new_from_memory(pix.samples_mv, pix.width, pix.height, pix.n, "uchar")
    return img, pix


def _normalize(img):
    """Auf 8 bit sRGB bzw. Graustufen ohne Alpha bringen (JPEG-tauglich)."""
    if img.interpretation == "cmyk":
        img = img.colourspace("srgb")
    if img.hasalpha():
        img = img.flatten(background=[255] * (img.bands - 1))
    if img.format != "uchar":
        img = img.colourspace("srgb" if img.bands >= 3 else "b-w")
    return img


# ============================================================ Kalibrierung N/Z ↔ Bildpixel

@dataclass
class _Segment:
    seg: int
    fx: tuple[float, float]          # x = fx[0] + fx[1]·N
    fy: tuple[float, float]          # y = fy[0] + fy[1]·Z
    nmin: int
    nmax: int
    zmin: int
    zmax: int

    def to_image(self, n: float, z: float) -> QPointF:
        return QPointF(self.fx[0] + self.fx[1] * n, self.fy[0] + self.fy[1] * z)

    def to_nz(self, pt: QPointF) -> tuple[int, int]:
        return round((pt.x() - self.fx[0]) / self.fx[1]), round((pt.y() - self.fy[0]) / self.fy[1])

    def outside(self, n: float, z: float) -> tuple[float, float]:
        """(Abstand in Z, Abstand in N) außerhalb des kalibrierten Bereichs, in Kästchen.

        Der Abschnitt gilt für seinen Z-Bereich; N dient nur zur Unterscheidung bei Überlappung.
        """
        dz = max(self.zmin - z, 0, z - self.zmax)
        dn = max(self.nmin - n, 0, n - self.nmax)
        return dz, dn


@dataclass
class Calibration:
    """Zuordnung N → x und Z → y (Mitte der Nuklidkästchen) aus angeklickten Nukliden.

    Nuklidkarten sind Gitter mit N waagerecht und Z senkrecht. Große Wandkarten (z. B. die Karlsruher)
    sind aber in **Abschnitte** (Streifen) zerlegt, die versetzt nebeneinander liegen. Deshalb gehört
    jeder Kalibrierpunkt zu einem Abschnitt; je Abschnitt genügen zwei Punkte mit verschiedenem N und Z,
    am besten das Nuklid mit dem kleinsten und das mit dem größten Z des Streifens. Der Z-Bereich der
    Punkte legt fest, wofür der Abschnitt gilt.
    """
    points: list[dict]

    @classmethod
    def load(cls, folder: Path) -> "Calibration":
        p = Path(folder) / CALIBRATION
        try:
            return cls(list(json.loads(p.read_text(encoding="utf-8")).get("points", [])))
        except (OSError, ValueError):
            return cls([])

    def save(self, folder: Path) -> None:
        (Path(folder) / CALIBRATION).write_text(json.dumps({"points": self.points}, ensure_ascii=False, indent=1),
                                                encoding="utf-8")

    def add(self, nuclide: str, x: float, y: float, segment: int = 1) -> None:
        canon = names.normalize(nuclide)
        nid = names.parse(canon)
        key = (nid.a - nid.z, nid.z, segment)
        self.points = [p for p in self.points if (p["n"], p["z"], p.get("segment", 1)) != key]
        self.points.append({"nuclide": canon, "n": nid.a - nid.z, "z": nid.z, "x": x, "y": y, "segment": segment})

    def segment_ids(self) -> list[int]:
        return sorted({int(p.get("segment", 1)) for p in self.points})

    @staticmethod
    def _fit(us: list[float], vs: list[float]) -> tuple[float, float] | None:
        if len(set(us)) < 2:
            return None
        mu, mv = sum(us) / len(us), sum(vs) / len(vs)
        slope = sum((u - mu) * (v - mv) for u, v in zip(us, vs)) / sum((u - mu) ** 2 for u in us)
        return None if slope == 0 else (mv - slope * mu, slope)

    def segments(self) -> list[_Segment]:
        out = []
        for sid in self.segment_ids():
            pts = [p for p in self.points if int(p.get("segment", 1)) == sid]
            fx = self._fit([p["n"] for p in pts], [p["x"] for p in pts])
            fy = self._fit([p["z"] for p in pts], [p["y"] for p in pts])
            if fx and fy:
                out.append(_Segment(sid, fx, fy, min(p["n"] for p in pts), max(p["n"] for p in pts),
                                    min(p["z"] for p in pts), max(p["z"] for p in pts)))
        return out

    @property
    def ready(self) -> bool:
        return bool(self.segments())

    def segment_ready(self, sid: int) -> bool:
        return any(s.seg == sid for s in self.segments())

    def _best(self, n: float, z: float) -> _Segment | None:
        segs = self.segments()
        return min(segs, key=lambda s: s.outside(n, z)) if segs else None

    def to_image(self, n: float, z: float) -> QPointF | None:
        s = self._best(n, z)
        return None if s is None else s.to_image(n, z)

    def to_nz(self, pt: QPointF, valid: Callable[[int, int], bool] | None = None,
              max_dz: float = 1.0) -> tuple[int, int] | None:
        """Nuklid unter einem Bildpunkt. Bei mehreren passenden Abschnitten gewinnt einer, in dem es das
        Nuklid gibt (``valid``) und der am wenigsten außerhalb seines Bereichs liegt."""
        cands = []
        for s in self.segments():
            n, z = s.to_nz(pt)
            dz, dn = s.outside(n, z)
            if dz <= max_dz and n >= 0 and z >= 0:
                ok = valid(n, z) if valid else True
                cands.append((not ok, dz, dn, (n, z)))
        return min(cands)[3] if cands else None

    def cell_size(self, n: float = 0, z: float = 0) -> tuple[float, float] | None:
        s = self._best(n, z)
        return None if s is None else (abs(s.fx[1]), abs(s.fy[1]))


def nuclide_label(n: int, z: int) -> str:
    try:
        return f"{elements.symbol(z)}-{n + z}"
    except (KeyError, IndexError, ValueError):
        return f"Z={z}, N={n}"


# ============================================================ Kachelquelle

class TileSource:
    """Deep-Zoom-Pyramide: name.dzi + name_files/<stufe>/<spalte>_<zeile>.<fmt>"""

    def __init__(self, dzi):
        dzi = Path(dzi)
        root = ET.parse(dzi).getroot()
        size = next(e for e in root.iter() if e.tag.endswith("Size"))
        self.dzi = dzi
        self.width = int(size.get("Width"))
        self.height = int(size.get("Height"))
        self.tile = int(root.get("TileSize"))
        self.overlap = int(root.get("Overlap", "0"))
        self.fmt = root.get("Format")
        self.dir = dzi.with_name(dzi.stem + "_files")
        self.max_level = max(int(p.name) for p in self.dir.iterdir() if p.name.isdigit())

    # k = Verkleinerungsstufe: 0 = Original, 1 = halbe Größe, ...
    def level_size(self, k):
        f = 1 << k
        return (self.width + f - 1) // f, (self.height + f - 1) // f

    def grid(self, k):
        w, h = self.level_size(k)
        return math.ceil(w / self.tile), math.ceil(h / self.tile)

    def path(self, k, col, row):
        return self.dir / str(self.max_level - k) / f"{col}_{row}.{self.fmt}"


# ============================================================ Hintergrund-Laden

class _Signals(QObject):
    loaded = Signal(object, object)      # key, QImage | None (fehlt) | "skip"


class _TileJob(QRunnable):
    def __init__(self, key, path, state, signals):
        super().__init__()
        self.key, self.path, self.state, self.signals = key, path, state, signals

    def run(self):
        if self.key not in self.state.wanted:        # inzwischen weggescrollt
            self.signals.loaded.emit(self.key, "skip")
            return
        img = QImage(str(self.path))
        self.signals.loaded.emit(self.key, None if img.isNull() else img)


# ============================================================ Viewer-Widget

class TileViewer(QWidget):
    zoomChanged = Signal(float)
    hovered = Signal(QPointF)            # Bildkoordinate unter der Maus
    clicked = Signal(QPointF)            # Klick ohne Ziehen, Bildkoordinate

    def __init__(self, src: TileSource, parent=None):
        super().__init__(parent)
        self.src = src
        self.scale = 1.0                     # Bildschirm-px pro Bild-px
        self.origin = QPointF(0, 0)          # Bildkoordinate in der linken oberen Ecke
        self.cache = OrderedDict()           # key -> QPixmap, LRU
        self.pending, self.missing = set(), set()
        self.state = SimpleNamespace(wanted=set())
        self.signals = _Signals()
        self.signals.loaded.connect(self._on_loaded)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(max(2, min(8, QThreadPool.globalInstance().maxThreadCount())))
        self._drag = None
        self._press = None
        self.marker: tuple[QPointF, QPointF, str] | None = None   # Mitte, Halbgröße, Text
        self.points: list[tuple[QPointF, int]] = []               # Kalibrierpunkte (Punkt, Abschnitt)
        self._pending_center: tuple[QPointF, float | None] | None = None
        self.fitted = False                  # erster Resize (Einpassen) ist erfolgt
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMouseTracking(True)
        self._load_overview()

    # ---------------------------------------------------------- Übersicht
    def _load_overview(self):
        k = 0
        while max(self.src.level_size(k)) > OVERVIEW_MAX and k < self.src.max_level:
            k += 1
        self.ov_k = k
        self.overview = {}
        cols, rows = self.src.grid(k)
        for c in range(cols):
            for r in range(rows):
                img = QImage(str(self.src.path(k, c, r)))
                if not img.isNull():
                    self.overview[(k, c, r)] = QPixmap.fromImage(img)

    # ---------------------------------------------------------- Ansicht
    def fit(self):
        w, h = max(1, self.width()), max(1, self.height())
        self.scale = min(w / self.src.width, h / self.src.height)
        self.origin = QPointF(self.src.width / 2 - w / 2 / self.scale,
                              self.src.height / 2 - h / 2 / self.scale)
        self._changed()

    def zoom_at(self, factor, pos: QPointF):
        lo = 0.5 * min(self.width() / self.src.width, self.height() / self.src.height)
        new = min(MAX_ZOOM, max(lo, self.scale * factor))
        anchor = self.origin + pos / self.scale
        self.scale = new
        self.origin = anchor - pos / new
        self._changed()

    def pan(self, dx, dy):
        self.origin = self.origin - QPointF(dx, dy) / self.scale
        self.update()

    def center_on(self, pt: QPointF, scale: float | None = None) -> None:
        """Bildpunkt in die Fenstermitte holen, optional mit neuem Maßstab."""
        if self.width() <= 1 or not self.isVisible():      # noch nicht angezeigt: beim ersten Resize
            self._pending_center = (pt, scale)
            return
        if scale is not None:
            self.scale = min(MAX_ZOOM, scale)
        self.origin = pt - QPointF(self.width(), self.height()) / 2 / self.scale
        self._changed()

    def set_marker(self, center: QPointF | None, half: QPointF | None = None, text: str = "") -> None:
        self.marker = None if center is None else (center, half or QPointF(0, 0), text)
        self.update()

    def to_image(self, pos: QPointF) -> QPointF:
        return self.origin + pos / self.scale

    def _changed(self):
        self.update()
        self.zoomChanged.emit(self.scale)

    # ---------------------------------------------------------- Zeichnen
    def paintEvent(self, _event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(45, 45, 45))
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        dpr = self.devicePixelRatioF()

        # gröbste Stufe, deren Kacheln noch mindestens so fein sind wie die Bildschirmpixel
        px = self.scale * dpr
        k = int(math.floor(math.log2(1 / px))) if px < 1 else 0
        k = max(0, min(k, self.src.max_level))
        visible = self._visible_tiles(k) if k < self.ov_k else []

        # 1) Übersicht als Hintergrund
        for key, pm in self.overview.items():
            self._draw(p, key, pm, dpr)

        # 2) gröbere Kacheln aus dem Cache als Platzhalter für fehlende
        missing_now, fallback = [], {}
        for key in visible:
            if key in self.cache:
                continue
            missing_now.append(key)
            kk, c, r = key
            for up in range(1, 4):
                pk = (kk + up, c >> up, r >> up)
                if pk[0] >= self.ov_k:
                    break
                if pk in self.cache:
                    fallback[pk] = self.cache[pk]
                    break
        for key, pm in fallback.items():
            self._draw(p, key, pm, dpr)

        # 3) passende Kacheln
        for key in visible:
            pm = self.cache.get(key)
            if pm is not None:
                self.cache.move_to_end(key)
                self._draw(p, key, pm, dpr)

        self._draw_overlay(p)
        p.end()
        self._request(missing_now)

    def _draw_overlay(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for pt, seg in self.points:
            s = (pt - self.origin) * self.scale
            p.setPen(QPen(SEGMENT_COLORS[(seg - 1) % len(SEGMENT_COLORS)], 3))
            p.drawEllipse(s, 7, 7)
            p.drawText(s + QPointF(9, -9), str(seg))
        if self.marker is None:
            return
        c, half, text = self.marker
        s = (c - self.origin) * self.scale
        hw, hh = max(10.0, half.x() * self.scale), max(10.0, half.y() * self.scale)
        pen = QPen(QColor(230, 30, 30), 3)
        p.setPen(pen)
        p.drawRect(QRectF(s.x() - hw, s.y() - hh, 2 * hw, 2 * hh))
        if text:
            p.drawText(QPointF(s.x() + hw + 6, s.y() - hh), text)

    def _draw(self, p, key, pm, dpr):
        k, c, r = key
        f = 1 << k
        ts, ov = self.src.tile, self.src.overlap
        lw, lh = self.src.level_size(k)
        sx, sy = (ov if c else 0), (ov if r else 0)
        sw = min(ts, lw - c * ts, pm.width() - sx)
        sh = min(ts, lh - r * ts, pm.height() - sy)
        if sw <= 0 or sh <= 0:
            return
        ox, oy, s = self.origin.x(), self.origin.y(), self.scale

        def snap(v):                       # auf Gerätepixel runden -> keine Haarlinien zwischen Kacheln
            return round(v * dpr) / dpr

        x0 = snap((c * ts * f - ox) * s)
        x1 = snap(((c * ts + sw) * f - ox) * s)
        y0 = snap((r * ts * f - oy) * s)
        y1 = snap(((r * ts + sh) * f - oy) * s)
        p.drawPixmap(QRectF(x0, y0, x1 - x0, y1 - y0), pm, QRectF(sx, sy, sw, sh))

    def _visible_tiles(self, k):
        f, ts = 1 << k, self.src.tile
        cols, rows = self.src.grid(k)
        x0, y0 = self.origin.x() / f, self.origin.y() / f
        x1 = (self.origin.x() + self.width() / self.scale) / f
        y1 = (self.origin.y() + self.height() / self.scale) / f
        c0, c1 = max(0, int(x0 // ts)), min(cols - 1, int(x1 // ts))
        r0, r1 = max(0, int(y0 // ts)), min(rows - 1, int(y1 // ts))
        cx, cy = (x0 + x1) / 2 / ts, (y0 + y1) / 2 / ts
        keys = [(k, c, r) for r in range(r0, r1 + 1) for c in range(c0, c1 + 1)]
        keys.sort(key=lambda t: (t[1] + 0.5 - cx) ** 2 + (t[2] + 0.5 - cy) ** 2)   # Mitte zuerst
        return keys

    # ---------------------------------------------------------- Laden
    def _request(self, keys):
        self.state.wanted = set(keys)
        for key in keys:
            if key in self.pending or key in self.missing:
                continue
            self.pending.add(key)
            self.pool.start(_TileJob(key, self.src.path(*key), self.state, self.signals))

    def _on_loaded(self, key, img):
        self.pending.discard(key)
        if isinstance(img, str):                 # übersprungen
            if key in self.state.wanted:
                self.update()
            return
        if img is None:
            self.missing.add(key)
            return
        self.cache[key] = QPixmap.fromImage(img)
        while len(self.cache) > CACHE_TILES:
            self.cache.popitem(last=False)
        self.update()

    def shutdown(self):
        self.state.wanted = set()
        self.pool.clear()
        self.pool.waitForDone(2000)

    # ---------------------------------------------------------- Eingabe
    def resizeEvent(self, e):  # noqa: N802
        old = e.oldSize()
        if old.width() <= 0 or old.height() <= 0:
            self.fit()
            self.fitted = True
            if self._pending_center is not None:
                pt, scale = self._pending_center
                self._pending_center = None
                self.origin = pt - QPointF(self.width(), self.height()) / 2 / (scale or self.scale)
                self.scale = min(MAX_ZOOM, scale or self.scale)
                self.origin = pt - QPointF(self.width(), self.height()) / 2 / self.scale
                self.zoomChanged.emit(self.scale)
        else:                                    # Mittelpunkt beibehalten
            centre = self.origin + QPointF(old.width(), old.height()) / 2 / self.scale
            self.origin = centre - QPointF(self.width(), self.height()) / 2 / self.scale
        super().resizeEvent(e)

    def wheelEvent(self, e):  # noqa: N802
        dy = e.angleDelta().y()
        if dy:
            self.zoom_at(1.0015 ** dy, e.position())

    def event(self, e):
        if (e.type() == QEvent.Type.NativeGesture
                and e.gestureType() == Qt.NativeGestureType.ZoomNativeGesture):
            self.zoom_at(1 + e.value(), e.position())
            return True
        return super().event(e)

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = self._press = e.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):  # noqa: N802
        if self._drag is not None:
            d = e.position() - self._drag
            self._drag = e.position()
            self.pan(d.x(), d.y())
        self.hovered.emit(self.to_image(e.position()))

    def mouseReleaseEvent(self, e):  # noqa: N802
        if self._press is not None and (e.position() - self._press).manhattanLength() < 4:
            self.clicked.emit(self.to_image(e.position()))
        self._drag = self._press = None
        self.unsetCursor()

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        self.zoom_at(2.0, e.position())

    def keyPressEvent(self, e):  # noqa: N802
        key = e.key()
        centre = QPointF(self.width() / 2, self.height() / 2)
        step_x, step_y = self.width() / 5, self.height() / 5
        if key == Qt.Key.Key_F:
            self.fit()
        elif key == Qt.Key.Key_1:
            self.zoom_at(1 / self.scale, centre)
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.zoom_at(1.25, centre)
        elif key == Qt.Key.Key_Minus:
            self.zoom_at(0.8, centre)
        elif key == Qt.Key.Key_Left:
            self.pan(step_x, 0)
        elif key == Qt.Key.Key_Right:
            self.pan(-step_x, 0)
        elif key == Qt.Key.Key_Up:
            self.pan(0, step_y)
        elif key == Qt.Key.Key_Down:
            self.pan(0, -step_y)
        else:
            super().keyPressEvent(e)


# ============================================================ Kacheln im Hintergrund erzeugen

class TileBuilder(QThread):
    """Führt :func:`prepare` in einem eigenen Thread aus, damit die Oberfläche bedienbar bleibt."""
    progress = Signal(str, int)
    done = Signal(object)              # Path der .dzi
    failed = Signal(str)

    def __init__(self, pdf: Path, page: int = 1, render: bool = False, rebuild: bool = False, parent=None):
        super().__init__(parent)
        self.pdf, self.page, self.render, self.rebuild = Path(pdf), page, render, rebuild

    def run(self):
        try:
            dzi = prepare(self.pdf, self.page, self.render, self.rebuild,
                          progress=lambda t, p: self.progress.emit(t, p))
        except Exception as e:  # noqa: BLE001 - Meldung für die Oberfläche
            self.failed.emit(f"{type(e).__name__}: {e}")
        else:
            self.done.emit(dzi)


# ============================================================ Fenster

class ChartWindow(QMainWindow):
    """Fenster mit eigener Nuklidkarte: öffnen, kalibrieren, zu Nukliden springen.

    ``nuclide_picked`` meldet ein angeklicktes Nuklid (kanonischer Name), wenn die Karte kalibriert ist
    und nicht gerade kalibriert wird – der Editor zeigt es dann an.
    """
    nuclide_picked = Signal(str)
    SETTINGS_KEY = "chart/last_pdf"

    def __init__(self, parent=None, has_nuclide: Callable[[str], bool] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Eigene Nuklidkarte")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.resize(1400, 900)
        self.has_nuclide = has_nuclide or (lambda _n: True)
        self.viewer: TileViewer | None = None
        self.folder: Path | None = None
        self.calibration = Calibration([])
        self.calibrating = False
        self._builder: TileBuilder | None = None
        self._pending_jump: str | None = None

        tb = QToolBar("Karte")
        tb.setMovable(False)
        self.addToolBar(tb)
        tb.addAction("Karte öffnen …", self.choose_file)
        self.act_cal = tb.addAction("Kalibrieren", self.toggle_calibration)
        self.act_cal.setCheckable(True)
        tb.addWidget(QLabel(" Abschnitt: "))
        self.segment = QSpinBox()
        self.segment.setRange(1, 20)
        self.segment.setToolTip("Große Karten bestehen aus versetzten Streifen. Jeder Streifen ist ein eigener "
                                "Abschnitt mit eigenen Kalibrierpunkten.")
        tb.addWidget(self.segment)
        tb.addAction("Kalibrierung löschen", self.reset_calibration)
        tb.addSeparator()
        tb.addWidget(QLabel(" Nuklid: "))
        self.goto = QLineEdit()
        self.goto.setPlaceholderText("z. B. Co-60")
        self.goto.setMaximumWidth(140)
        self.goto.returnPressed.connect(lambda: self.show_nuclide(self.goto.text()))
        tb.addWidget(self.goto)
        tb.addAction("Zeigen", lambda: self.show_nuclide(self.goto.text()))

        self.placeholder = QLabel("Keine Nuklidkarte geöffnet.\n\n„Karte öffnen …“ wählt eine eigene Nuklidkarte "
                                  "(PDF mit eingescanntem Bild oder .dzi).\nNucDB liefert keine Karte mit.")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCentralWidget(self.placeholder)
        self.hover = QLabel()
        self.zoom = QLabel()
        self.statusBar().addWidget(self.hover, 1)
        self.statusBar().addPermanentWidget(self.zoom)

    # ---------------------------------------------------------- Datei
    @staticmethod
    def settings() -> QSettings:
        return QSettings("NucOffice", "NucDB")

    def last_file(self) -> Path | None:
        v = self.settings().value(self.SETTINGS_KEY)
        return Path(v) if v and Path(v).exists() else None

    def choose_file(self) -> None:
        start = str(self.last_file() or Path.home())
        fn, _f = QFileDialog.getOpenFileName(self, "Eigene Nuklidkarte öffnen", start,
                                             "Nuklidkarte (*.pdf *.dzi);;Alle Dateien (*)")
        if fn:
            self.open_file(Path(fn))

    def open_file(self, path: Path, *, page: int = 1, rebuild: bool = False) -> None:
        """Karte öffnen; fehlen die Kacheln, werden sie (einmalig) im Hintergrund erzeugt."""
        path = Path(path)
        dzi = None if rebuild else ready_dzi(path, page)
        if dzi is not None:
            self._show(dzi, path)
            return
        missing = missing_build_modules()
        if missing:
            QMessageBox.warning(self, "Nuklidkarte", "Zum einmaligen Aufbereiten der PDF fehlen: "
                                f"{', '.join(missing)}.\n\npip install 'nucdb[chart]'")
            return
        dlg = QProgressDialog("Nuklidkarte wird einmalig aufbereitet …", None, 0, 100, self)
        dlg.setWindowTitle("Nuklidkarte")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setValue(0)
        self._builder = b = TileBuilder(path, page, rebuild=rebuild, parent=self)

        def prog(text: str, pct: int) -> None:
            dlg.setLabelText(text)
            if pct >= 0:
                dlg.setValue(pct)

        def finished(dzi_path) -> None:
            dlg.close()
            self._show(Path(dzi_path), path)

        def failed(msg: str) -> None:
            dlg.close()
            QMessageBox.critical(self, "Nuklidkarte", f"Aufbereiten fehlgeschlagen:\n{msg}")

        b.progress.connect(prog)
        b.done.connect(finished)
        b.failed.connect(failed)
        b.start()

    def wait_for_builder(self, ms: int = -1) -> bool:
        """(Für Tests) auf den Kachelaufbau warten."""
        return self._builder.wait(ms if ms >= 0 else 2**31 - 1) if self._builder else True

    def _show(self, dzi: Path, original: Path) -> None:
        if self.viewer is not None:
            self.viewer.shutdown()
        src = TileSource(dzi)
        self.viewer = TileViewer(src)
        self.viewer.zoomChanged.connect(self._zoom_text)
        self.viewer.hovered.connect(self._hover_text)
        self.viewer.clicked.connect(self._clicked)
        self.setCentralWidget(self.viewer)
        self.folder = dzi.parent
        self.calibration = Calibration.load(self.folder)
        self._update_points()
        self.setWindowTitle(f"Eigene Nuklidkarte – {original.name}")
        if original.suffix.lower() == ".pdf":
            self.settings().setValue(self.SETTINGS_KEY, str(original.resolve()))
        self._size = f"{src.width:,} × {src.height:,} px".replace(",", ".")
        self.viewer.setFocus()
        if not self.calibration.ready:
            self.statusBar().showMessage("Noch nicht kalibriert: „Kalibrieren“ wählen und je Streifen (Abschnitt) "
                                         "das Nuklid mit dem kleinsten und dem größten Z anklicken.", 20000)
        if self._pending_jump:
            name, self._pending_jump = self._pending_jump, None
            self.show_nuclide(name)

    def _zoom_text(self, s: float) -> None:
        self.zoom.setText(f"{s * 100:.1f} %   ·   {self._size}")

    def _hover_text(self, pt: QPointF) -> None:
        nz = self.calibration.to_nz(pt, self._valid)
        if nz is None:
            self.hover.setText(f"x = {pt.x():.0f}, y = {pt.y():.0f}")
        else:
            n, z = nz
            self.hover.setText(f"N = {n}, Z = {z}  →  {nuclide_label(n, z)}")

    # ---------------------------------------------------------- Kalibrieren und Springen
    def toggle_calibration(self, on: bool | None = None) -> None:
        self.calibrating = self.act_cal.isChecked() if on is None else on
        self.act_cal.setChecked(self.calibrating)
        if self.calibrating:
            self.statusBar().showMessage(
                "Kalibrieren: Mitte eines bekannten Nuklids anklicken und Namen eingeben. Je Streifen der Karte einen "
                "eigenen Abschnitt wählen und darin das Nuklid mit dem kleinsten und dem größten Z anklicken. "
                "Danach „Kalibrieren“ erneut drücken.", 60000)
        else:
            self.statusBar().clearMessage()

    def _valid(self, n: int, z: int) -> bool:
        try:
            return self.has_nuclide(nuclide_label(n, z))
        except ValueError:
            return False

    def add_calibration_point(self, nuclide: str, pt: QPointF, segment: int | None = None) -> None:
        self.calibration.add(nuclide, pt.x(), pt.y(), self.segment.value() if segment is None else segment)
        if self.folder is not None:
            self.calibration.save(self.folder)
        self._update_points()

    def reset_calibration(self) -> None:
        self.calibration = Calibration([])
        if self.folder is not None:
            self.calibration.save(self.folder)
        self._update_points()
        if self.viewer:
            self.viewer.set_marker(None)

    def _update_points(self) -> None:
        if self.viewer is not None:
            self.viewer.points = [(QPointF(p["x"], p["y"]), int(p.get("segment", 1)))
                                  for p in self.calibration.points]
            self.viewer.update()

    def _clicked(self, pt: QPointF) -> None:
        if self.calibrating:
            seg = self.segment.value()
            guess = ""
            own = [s for s in self.calibration.segments() if s.seg == seg]
            if own:
                guess = nuclide_label(*own[0].to_nz(pt))
            name, ok = QInputDialog.getText(self, "Kalibrierpunkt", f"Abschnitt {seg}: welches Nuklid ist das?",
                                            text=guess)
            if ok and name.strip():
                try:
                    self.add_calibration_point(name, pt)
                except ValueError as e:
                    QMessageBox.warning(self, "Kalibrierpunkt", str(e))
                    return
                n = sum(1 for p in self.calibration.points if int(p.get("segment", 1)) == seg)
                self.statusBar().showMessage(f"Abschnitt {seg}: {n} Kalibrierpunkt(e)"
                                             + (" – kalibriert." if self.calibration.segment_ready(seg) else
                                                " – noch einen mit anderem N und Z."), 10000)
            return
        nz = self.calibration.to_nz(pt, self._valid)
        if nz is not None:
            name = nuclide_label(*nz)
            try:
                if self.has_nuclide(name):
                    self.nuclide_picked.emit(names.normalize(name))
            except ValueError:
                pass

    def show_nuclide(self, name: str) -> bool:
        """Zum Nuklid springen und es markieren. Liefert ``False`` ohne Karte/Kalibrierung."""
        try:
            nid = names.parse(names.normalize(name))
        except ValueError:
            self.statusBar().showMessage(f"Unbekannter Nuklidname: {name}", 6000)
            return False
        if self.viewer is None:
            self._pending_jump = name
            return False
        pt = self.calibration.to_image(nid.a - nid.z, nid.z)
        if pt is None:
            self.statusBar().showMessage("Karte ist noch nicht kalibriert („Kalibrieren“).", 8000)
            return False
        cw, ch = self.calibration.cell_size(nid.a - nid.z, nid.z)
        self.viewer.set_marker(pt, QPointF(cw / 2, ch / 2), names.normalize(name))
        # so zoomen, dass ein Kästchen etwa 80 px breit ist (nicht kleiner als jetzt)
        current = self.viewer.scale if self.viewer.fitted else 0.0
        self.viewer.center_on(pt, max(current, 80 / max(cw, 1e-9)))
        self.goto.setText(names.normalize(name))
        return True

    def closeEvent(self, e):  # noqa: N802
        if self.viewer is not None:
            self.viewer.shutdown()
        super().closeEvent(e)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Flüssiger Viewer für eigene Nuklidkarten (große Bild-PDFs)")
    ap.add_argument("file", nargs="?", help="PDF oder .dzi (Standard: zuletzt geöffnete Karte)")
    ap.add_argument("--page", type=int, default=1, help="Seite, ab 1 gezählt")
    ap.add_argument("--render", action="store_true", help="Seite rendern statt Bild extrahieren")
    ap.add_argument("--rebuild", action="store_true", help="Kacheln neu erzeugen")
    ap.add_argument("--nuclide", help="gleich zu diesem Nuklid springen (Karte muss kalibriert sein)")
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    win = ChartWindow()
    path = Path(args.file).resolve() if args.file else win.last_file()
    if path is not None and (args.render or args.page != 1):
        prepare(path, args.page, args.render, args.rebuild)          # Sonderfälle im Vordergrund
        win._show(ready_dzi(path, args.page, args.render), path)
    elif path is not None:
        win.open_file(path, page=args.page, rebuild=args.rebuild)
    if args.nuclide:
        win._pending_jump = args.nuclide
        if win.viewer is not None:
            win.show_nuclide(args.nuclide)
    win.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
