"""Hauptfenster des Editors: Nuklide browsen, suchen, bearbeiten; Peak-Suche; Overlay übernehmen."""

from __future__ import annotations

import math
from typing import Any, Callable

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
                               QPushButton, QSplitter, QTabWidget, QToolBar, QVBoxLayout, QWidget)

from .. import names, units
from ..curation import Curation, OverlayEntry, overlay_entries, remove_overlay_entry
from ..db import NucDB
from ..models import DecayMode, Emission, Nuclide, Value
from ..overlay import OverlayLockedError
from . import dialogs
from .table import ROW_ROLE, Column, make_table, selected_row

EMISSION_TABS = [("gamma", "Gamma/Röntgen"), ("alpha", "Alpha"), ("beta", "Beta"), ("electron", "Elektronen")]


def _g(x: float | None, digits: int = 6) -> str:
    return "" if x is None else f"{x:.{digits}g}"


def _pct(x: float | None) -> str:
    return "" if x is None else f"{x * 100:.4g}"


def _origin(obj: Any) -> str:
    return "eigen" if getattr(obj, "user", False) else "zentral"


class MainWindow(QMainWindow):
    """Editor. ``curation`` = Schreibzugriff auf die zentrale Datenbank (``None`` = nur Overlay)."""

    def __init__(self, db: NucDB, curation: Curation | None = None):
        super().__init__()
        self.db = db
        self.curation = curation
        self._central_nuclides: set[str] | None = None
        self.current: str | None = None
        self.setWindowTitle(f"NucDB-Editor – {db.location}")
        self.resize(1280, 800)
        self._build_toolbar()
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.addTab(self._build_nuclide_tab(), "Nuklide")
        self.tabs.addTab(self._build_peak_tab(), "Peak-Suche")
        self.tabs.addTab(self._build_overlay_tab(), "Eigene Einträge")
        self.tabs.addTab(self._build_sources_tab(), "Quellen")
        self.tabs.addTab(self._build_log_tab(), "Änderungsprotokoll")
        self.tabs.currentChanged.connect(lambda _i: self._refresh_aux())
        self.refresh_all()

    # ------------------------------------------------------------------------------------
    # Aufbau
    # ------------------------------------------------------------------------------------
    def _build_toolbar(self) -> None:
        tb = QToolBar("Werkzeuge")
        tb.setMovable(False)
        self.addToolBar(tb)
        tb.addWidget(QLabel(" Ziel: "))
        self.target = QComboBox()
        self.target.addItem("Eigene Ergänzungen (Overlay)", "overlay")
        if self.curation is not None:
            self.target.addItem("Zentrale Datenbank (Pflege, Quellenpflicht)", "central")
        if self.db.user is None:
            self.target.model().item(0).setEnabled(False)
            if self.curation is not None:
                self.target.setCurrentIndex(1)
        self.target.setToolTip("Wohin neue Einträge geschrieben werden. Die zentrale Datenbank lässt sich nur "
                               "mit Kurationsordner bearbeiten (nucdb editor --curation …).")
        tb.addWidget(self.target)
        tb.addSeparator()
        for text, slot, key in (("Neues Nuklid …", self.new_nuclide, "Ctrl+N"),
                                ("Neue Quelle …", self.new_source_dialog, None),
                                ("Neu laden", self.reload, "F5"),
                                ("Nuklidkarte", self.open_chart, "Ctrl+K")):
            a = QAction(text, self)
            a.triggered.connect(slot)
            if key:
                a.setShortcut(QKeySequence(key))
            tb.addAction(a)
            if text == "Neue Quelle …":
                self.act_new_source = a
        self.act_new_source.setEnabled(self.curation is not None)
        info = QLabel()
        info.setText(f"  Daten {self.db.data_version} · Schema {self.db.schema_version}"
                     + ("" if self.curation is None else f" · Kuration: {self.curation.location}"))
        tb.addWidget(info)

    def _build_nuclide_tab(self) -> QWidget:
        split = QSplitter()
        left = QWidget()
        ll = QVBoxLayout(left)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Suchen: Co-60, 60Co, Cobalt, Z=27, A=60 …")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        ll.addWidget(self.search)
        row = QHBoxLayout()
        self.only_user = QCheckBox("nur mit eigenen Einträgen")
        self.only_user.toggled.connect(self._apply_filter)
        self.hide_short = QCheckBox("T½ ≥ 1 s")
        self.hide_short.toggled.connect(self._apply_filter)
        row.addWidget(self.only_user)
        row.addWidget(self.hide_short)
        row.addStretch()
        ll.addLayout(row)
        cols = [Column("Nuklid", lambda n: n.name, lambda n: (n.z, n.a, n.isomer)),
                Column("Z", lambda n: n.z, align_right=True), Column("N", lambda n: n.n, align_right=True),
                Column("A", lambda n: n.a, align_right=True),
                Column("T½", lambda n: n.format_half_life(),
                       lambda n: n.half_life_s if n.half_life_s is not None else -1.0),
                Column("Zerfallsdaten", lambda n: n.decay_source or "")]
        self.nuc_view, self.nuc_model, self.nuc_proxy = make_table(cols, self)
        self.nuc_view.selectionModel().selectionChanged.connect(self._nuclide_selected)
        ll.addWidget(self.nuc_view)
        self.count_label = QLabel()
        ll.addWidget(self.count_label)
        split.addWidget(left)

        right = QWidget()
        rl = QVBoxLayout(right)
        self.header = QLabel("Kein Nuklid gewählt")
        self.header.setTextFormat(Qt.TextFormat.RichText)
        self.header.setWordWrap(True)
        self.header.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        rl.addWidget(self.header)
        opts = QHBoxLayout()
        self.all_sources = QCheckBox("alle Quellen zeigen (sonst nur die bevorzugte)")
        self.all_sources.toggled.connect(lambda _b: self.show_nuclide(self.current))
        opts.addWidget(self.all_sources)
        opts.addStretch()
        self.chart_follow = QCheckBox("Nuklidkarte folgt")
        self.chart_follow.setToolTip("Eigene Nuklidkarte zeigt das gewählte Nuklid (Karte muss kalibriert sein)")
        self.chart_follow.setChecked(True)
        b = QPushButton("In Nuklidkarte zeigen")
        b.clicked.connect(lambda: self.open_chart(self.current))
        opts.addWidget(self.chart_follow)
        opts.addWidget(b)
        rl.addLayout(opts)
        self.detail = QTabWidget()
        rl.addWidget(self.detail, 1)

        vcols = [Column("Größe", lambda r: r[0]),
                 Column("Wert", lambda r: self._fmt_value(r[0], r[1]), lambda r: self._num(r[1].value)),
                 Column("±", lambda r: "" if r[0] == "half_life_s" else _g(r[1].unc)),
                 Column("Quelle", lambda r: r[1].source),
                 Column("bevorzugt", lambda r: "✓" if r[1].preferred else ""),
                 Column("Herkunft", lambda r: _origin(r[1])),
                 Column("Originaltext", lambda r: r[1].text or "")]
        self.val_view, self.val_model, _ = make_table(vcols, self)
        self.detail.addTab(self._with_buttons(self.val_view, self.add_value, self.remove_selected_value),
                           "Werte")
        dcols = [Column("Art", lambda m: m.mode or "?"),
                 Column("Tochter", lambda m: m.daughter or ""),
                 Column("Anteil %", lambda m: _pct(m.branching), lambda m: m.branching, align_right=True),
                 Column("± %", lambda m: _pct(m.branching_unc), align_right=True),
                 Column("effektiv %", lambda m: _pct(m.effective_branching)
                        + (" (Info)" if m.informational else ""), lambda m: m.effective_branching or 0.0,
                        align_right=True),
                 Column("Quelle", lambda m: m.source), Column("Herkunft", _origin)]
        self.dec_view, self.dec_model, _ = make_table(dcols, self)
        self.dec_view.doubleClicked.connect(lambda idx: self._jump_to_daughter())
        self.detail.addTab(self._with_buttons(self.dec_view, self.add_decay_mode, self.remove_selected_decay_mode),
                           "Zerfall")
        self.em_views: dict[str, Any] = {}
        for kind, title in EMISSION_TABS:
            cols = [Column("Energie keV", lambda e: _g(e.energy_kev, 8), lambda e: e.energy_kev, align_right=True),
                    Column("±", lambda e: _g(e.energy_kev_unc), align_right=True),
                    Column("Intensität %", lambda e: _pct(e.intensity), lambda e: e.intensity or -1.0,
                           align_right=True),
                    Column("± %", lambda e: _pct(e.intensity_unc), align_right=True),
                    Column("Typ", lambda e: e.get("radiation") or e.get("type") or "")]
            if kind == "beta":
                cols.append(Column("E_mittel keV", lambda e: _g(e.get("mean_energy_kev")),
                                   lambda e: e.get("mean_energy_kev") or 0.0, align_right=True))
            cols += [Column("Quelle", lambda e: e.source), Column("Herkunft", _origin),
                     Column("Notiz", lambda e: e.get("note") or e.get("flag") or "")]
            view, model, _ = make_table(cols, self)
            self.em_views[kind] = (view, model)
            self.detail.addTab(self._with_buttons(view, lambda _=False, k=kind: self.add_emission(k),
                                                  lambda _=False, k=kind: self.remove_selected_emission(k)), title)
        split.addWidget(right)
        split.setSizes([430, 850])
        return split

    def _with_buttons(self, view, add: Callable, remove: Callable) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(view, 1)
        row = QHBoxLayout()
        b1 = QPushButton("Hinzufügen …")
        b1.clicked.connect(add)
        b2 = QPushButton("Entfernen …")
        b2.clicked.connect(remove)
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch()
        lay.addLayout(row)
        return w

    def _build_peak_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.peak_energy = QLineEdit()
        self.peak_energy.setPlaceholderText("Energie, z. B. 609.3 oder 1,4608 MeV")
        self.peak_tol = QLineEdit("1.0")
        self.peak_tol.setMaximumWidth(80)
        self.peak_minhl = QLineEdit()
        self.peak_minhl.setPlaceholderText("min. T½, z. B. 1 h")
        self.peak_minhl.setMaximumWidth(160)
        b = QPushButton("Suchen")
        b.clicked.connect(self.peak_search)
        self.peak_energy.returnPressed.connect(self.peak_search)
        for x in (QLabel("Energie:"), self.peak_energy, QLabel("± keV:"), self.peak_tol, self.peak_minhl, b):
            row.addWidget(x)
        row.addStretch()
        lay.addLayout(row)
        cols = [Column("erwartet keV", lambda m: _g(m.energy_kev, 8), lambda m: m.energy_kev, align_right=True),
                Column("Δ keV", lambda m: f"{m.delta_kev:+.3f}", lambda m: abs(m.delta_kev), align_right=True),
                Column("Nuklid", lambda m: getattr(m.line, "nuclide", None) or getattr(m.line, "origin", None)
                       or "—"),
                Column("Art", lambda m: {"decay": "Linie", "single_escape": "Single-Escape",
                                         "double_escape": "Double-Escape", "special": "Sonderlinie"}.get(m.kind, m.kind)
                       + (f" ({m.line.kind})" if m.kind == "special" else "")),
                Column("Intensität %", lambda m: _pct(getattr(m.line, "intensity", None)),
                       lambda m: getattr(m.line, "intensity", None) or -1.0, align_right=True),
                Column("Bewertung", lambda m: f"{m.score:.3g}", lambda m: m.score, align_right=True),
                Column("Quelle", lambda m: m.line.source),
                Column("Herkunft", lambda m: _origin(m.line))]
        self.peak_view, self.peak_model, _ = make_table(cols, self)
        self.peak_view.doubleClicked.connect(lambda _i: self._jump_from_peak())
        lay.addWidget(self.peak_view, 1)
        hint = QLabel("Doppelklick öffnet das Nuklid. Sortiert nach Bewertung (Intensität × Nähe). "
                      "Prompt-Gammas werden hier nie gemischt.")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        return w

    def _build_overlay_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        loc = self.db.overlay_location
        lab = QLabel(f"Ergänzungsdatenbank: {loc or '— (abgeschaltet)'}. Einträge hier sehen alle Tools; "
                     "sie sind nicht weitergebbar, bis sie mit einer echten Quelle übernommen werden.")
        lab.setWordWrap(True)
        lay.addWidget(lab)
        cols = [Column("Art", lambda e: {"nuclide": "Nuklid", "value": "Wert", "decays": "Zerfallswege", "gamma": "Gamma", "alpha": "Alpha",
                                         "beta": "Beta", "electron": "Elektron"}.get(e.kind, e.kind)),
                Column("Nuklid", lambda e: e.nuclide, lambda e: names.sort_key(e.nuclide)),
                Column("Inhalt", lambda e: e.description),
                Column("angelegt", lambda e: e.added_at or "")]
        self.ov_view, self.ov_model, _ = make_table(cols, self)
        self.ov_view.doubleClicked.connect(lambda _i: self._jump_from_overlay())
        lay.addWidget(self.ov_view, 1)
        row = QHBoxLayout()
        self.btn_adopt = QPushButton("In zentrale Datenbank übernehmen …")
        self.btn_adopt.clicked.connect(self.adopt_selected)
        self.btn_adopt.setEnabled(self.curation is not None)
        if self.curation is None:
            self.btn_adopt.setToolTip("Nur mit Kurationsordner (nucdb editor --curation …)")
        b = QPushButton("Löschen …")
        b.clicked.connect(self.delete_overlay_selected)
        row.addWidget(self.btn_adopt)
        row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        return w

    def _build_sources_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        cols = [Column("Kurzname", lambda s: s.key), Column("Titel", lambda s: s.get("title") or ""),
                Column("weitergebbar", lambda s: "ja" if s.redistributable else "nein"),
                Column("Herkunft", _origin),
                Column("Zitierweise", lambda s: s.citation, tooltip=lambda s: s.get("url") or s.get("doi"))]
        self.src_view, self.src_model, _ = make_table(cols, self)
        lay.addWidget(self.src_view, 1)
        return w

    def _build_log_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        cols = [Column("Zeit", lambda r: r[1].get("changed_at", "")), Column("Ort", lambda r: r[0]),
                Column("Datei", lambda r: r[1].get("file", "")), Column("Eintrag", lambda r: r[1].get("record", "")),
                Column("Feld", lambda r: r[1].get("field") or ""),
                Column("alt", lambda r: "" if r[1].get("old") is None else r[1]["old"]),
                Column("neu", lambda r: "" if r[1].get("new") is None else r[1]["new"]),
                Column("Kommentar", lambda r: r[1].get("comment") or "")]
        self.log_view, self.log_model, _ = make_table(cols, self)
        self.log_view.sortByColumn(0, Qt.SortOrder.DescendingOrder)
        lay.addWidget(self.log_view, 1)
        return w

    # ------------------------------------------------------------------------------------
    # Anzeigen
    # ------------------------------------------------------------------------------------
    @staticmethod
    def _num(v: Any) -> Any:
        return v if isinstance(v, (int, float)) else str(v)

    def _fmt_value(self, q: str, v: Value) -> str:
        if q == "half_life_s" and isinstance(v.value, (int, float)):
            return "stabil" if v.value == math.inf else units.format_time(v.value, "auto", v.unc)
        unit = (self.db.quantities().get(q) or {}).get("unit") or ""
        val = _g(v.value, 10) if isinstance(v.value, float) else str(v.value)
        return f"{val} {unit}".strip()

    def refresh_all(self) -> None:
        self._central_nuclides = None
        self.nuc_model.set_rows(self.db.nuclides())
        self._apply_filter()
        self.show_nuclide(self.current)
        self._refresh_aux()

    def _refresh_aux(self) -> None:
        """Nebentabs (Overlay, Quellen, Protokoll) auffrischen."""
        self.ov_model.set_rows(self._overlay_entries())
        self.src_model.set_rows(list(self.db.sources().values()))
        rows = []
        if self.curation is not None:
            rows += [("zentral", r) for r in self.curation.changelog()]
        else:
            from ..fileformat import read_file
            p = self.db.location / "changelog.json"
            if p.is_file():
                rows += [("zentral", r) for r in read_file(p)[1]]
        if self.db.user is not None:
            rows += [("eigen", r) for r in self.db.user._load("changelog")]
        self.log_model.set_rows(rows)

    def _overlay_entries(self) -> list[OverlayEntry]:
        if self.db.user is None:
            return []
        central = self.curation.central if self.curation else NucDB(self.db.location, overlay=False)
        return overlay_entries(self.db.user, central)

    def _user_nuclides(self) -> set[str]:
        if self._central_nuclides is None:
            names_ = {e.nuclide for e in self._overlay_entries()}
            self._central_nuclides = names_
        return self._central_nuclides

    def _apply_filter(self) -> None:
        text = self.search.text().strip()
        only_user = self.only_user.isChecked()
        min1s = self.hide_short.isChecked()
        user_set = self._user_nuclides() if only_user else set()
        canon = None
        if text:
            try:
                canon = names.normalize(text)
            except names.NuclideNameError:
                canon = None
        low = text.lower()
        zf = af = None
        for part in low.replace(",", " ").split():
            if part.startswith("z=") and part[2:].isdigit():
                zf = int(part[2:])
            if part.startswith("a=") and part[2:].isdigit():
                af = int(part[2:])
        def element_names(z: int) -> list[str]:
            try:
                el = self.db.element(z)
                return [el.name_de, el.name_en, el.symbol]
            except KeyError:
                return []

        def pred(n: Nuclide) -> bool:
            if only_user and n.name not in user_set:
                return False
            if min1s and (n.half_life_s is None or n.half_life_s < 1):
                return False
            if not text:
                return True
            if canon is not None:
                return n.name == canon or n.name.startswith(canon + "m")
            if zf is not None or af is not None:
                return (zf is None or n.z == zf) and (af is None or n.a == af)
            return low in n.name.lower() or any(low in x.lower() for x in element_names(n.z))
        self.nuc_proxy.set_filter(pred)
        self.count_label.setText(f"{self.nuc_proxy.rowCount()} von {self.nuc_model.rowCount()} Nukliden "
                                 "(blau = eigene Einträge)")
        for r in range(self.nuc_proxy.rowCount()):
            n = self.nuc_proxy.index(r, 0).data(ROW_ROLE)
            if self.nuc_proxy.rowCount() == 1 or (canon is not None and n.name == canon):
                self.nuc_view.selectRow(r)
                break

    def _nuclide_selected(self, *_a) -> None:
        n = selected_row(self.nuc_view)
        if n is not None and n.name != self.current:
            self.show_nuclide(n.name)

    def show_nuclide(self, name: str | None) -> None:
        self.current = name if name and self.db.has_nuclide(name) else None
        if self.current is None:
            self.header.setText("Kein Nuklid gewählt")
            for m in (self.val_model, self.dec_model, *[m for _v, m in self.em_views.values()]):
                m.set_rows([])
            return
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            n = self.db.nuclide(self.current)
            allsrc = self.all_sources.isChecked()
            el = self.db.element(n.z)
            flags = []
            if n.user:
                flags.append("<span style='color:#1e6ec8'>eigenes Nuklid (Overlay)</span>")
            if n.fields.get("note"):
                flags.append(str(n.fields.get("note")))
            self.header.setText(
                f"<b style='font-size:15pt'>{n.name}</b> &nbsp; {el.name_de} · Z={n.z} N={n.n} A={n.a}"
                + (f" · Isomer {n.isomer}" if n.isomer else "")
                + f"<br>T½ = {n.format_half_life(decimal_comma=True)}"
                + (f" · Zerfallsdaten: {n.decay_source}" if n.decay_source else "")
                + ("<br>" + " · ".join(flags) if flags else ""))
            vals = [(q, v) for q in n.quantities for v in (n.values(q) if allsrc else n.values(q)[:1])]
            self.val_model.set_rows(vals)
            self.dec_model.set_rows(self.db.decay_modes(n.name, all_sources=allsrc))
            for kind, (_view, model) in self.em_views.items():
                model.set_rows(self.db.emissions(kind, n.name, all_sources=allsrc))
            for i, (kind, title) in enumerate(EMISSION_TABS, start=2):
                self.detail.setTabText(i, f"{title} ({self.em_views[kind][1].rowCount()})")
            for view in (self.val_view, self.dec_view, *[v for v, _m in self.em_views.values()]):
                view.resizeColumnsToContents()
        finally:
            QGuiApplication.restoreOverrideCursor()
        if self.chart is not None and self.chart.isVisible() and self.chart_follow.isChecked():
            self.chart.show_nuclide(self.current)

    # ------------------------------------------------------------------------------------
    # Eigene Nuklidkarte (wird nicht mitgeliefert)
    # ------------------------------------------------------------------------------------
    chart = None

    def open_chart(self, nuclide: str | None = None) -> None:
        """Fenster mit der eigenen Nuklidkarte öffnen (zuletzt gewählte PDF), optional zu einem Nuklid."""
        from .chartviewer import ChartWindow
        if self.chart is None:
            self.chart = ChartWindow(None, has_nuclide=self.db.has_nuclide)
            self.chart.nuclide_picked.connect(self._chart_picked)
            last = self.chart.last_file()
            if last is not None:
                self.chart.open_file(last)
        self.chart.show()
        self.chart.raise_()
        self.chart.activateWindow()
        if nuclide:
            self.chart.show_nuclide(nuclide)

    def _chart_picked(self, name: str) -> None:
        if self.db.has_nuclide(name) and name != self.current:
            follow = self.chart_follow.isChecked()
            self.chart_follow.setChecked(False)          # Karte nicht wegspringen lassen
            try:
                self.select_nuclide(name)
            finally:
                self.chart_follow.setChecked(follow)

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt)
        if self.chart is not None:
            self.chart.close()
        super().closeEvent(event)

    def select_nuclide(self, name: str) -> None:
        self.search.setText(name)
        self.tabs.setCurrentIndex(0)
        self.show_nuclide(names.normalize(name))

    def _jump_to_daughter(self) -> None:
        m = selected_row(self.dec_view)
        if m is not None and m.daughter and self.db.has_nuclide(m.daughter):
            self.select_nuclide(m.daughter)

    def _jump_from_peak(self) -> None:
        m = selected_row(self.peak_view)
        nuc = getattr(m.line, "nuclide", None) if m is not None else None
        if nuc:
            self.select_nuclide(nuc)

    def _jump_from_overlay(self) -> None:
        e = selected_row(self.ov_view)
        if e is not None and self.db.has_nuclide(e.nuclide):
            self.select_nuclide(e.nuclide)

    # ------------------------------------------------------------------------------------
    # Schreiben
    # ------------------------------------------------------------------------------------
    @property
    def central(self) -> bool:
        return self.target.currentData() == "central"

    def _require_target(self) -> bool:
        if self.central:
            return True
        if self.db.user is None:
            QMessageBox.information(self, "NucDB", "Die Ergänzungsdatenbank ist abgeschaltet.")
            return False
        return True

    def _after_write(self, msg: str) -> None:
        self.db.reload()
        self.refresh_all()
        self.statusBar().showMessage(msg, 8000)

    def _sources(self) -> dict[str, dict]:
        return self.curation.sources() if self.curation else {}

    def _run(self, dlg: dialogs.FormDialog, msg: str) -> Any:
        """Dialog modal zeigen; nach Erfolg neu laden. Liefert das Ergebnis oder ``None``."""
        if dlg.exec() == dialogs.FormDialog.DialogCode.Accepted:
            self._after_write(msg)
            return dlg.result_value
        return None

    def new_source_dialog(self, parent=None) -> str | None:
        if self.curation is None:
            return None
        dlg = dialogs.SourceDialog(lambda v: self.curation.add_source(**v), parent or self)
        rec = self._run(dlg, "Quelle angelegt")
        return rec["key"] if rec else None

    def _new_source_cb(self):
        return (lambda parent: self.new_source_dialog(parent)) if self.curation else None

    def make_value_dialog(self, quantity: str | None = None) -> dialogs.ValueDialog:
        name = self.current

        def submit(v: dict) -> Any:
            if self.central:
                return self.curation.add_value(name, v.pop("quantity"), v.pop("value"), **v)
            v.pop("source", None)
            return self.db.user.add_value(name, v.pop("quantity"), v.pop("value"), **v)
        return dialogs.ValueDialog(name, self.db.quantities(), submit, central=self.central, sources=self._sources,
                                   new_source=self._new_source_cb(), quantity=quantity, parent=self)

    def add_value(self) -> None:
        if self.current and self._require_target():
            self._run(self.make_value_dialog(), f"Wert für {self.current} gespeichert")

    def make_emission_dialog(self, kind: str, energy: str = "") -> dialogs.EmissionDialog:
        name = self.current

        def submit(v: dict) -> Any:
            k, e = v.pop("kind"), v.pop("energy")
            if self.central:
                return self.curation.add_emission(k, name, e, **v)
            v.pop("source", None)
            return self.db.user.add_emission(k, name, e, **v)
        return dialogs.EmissionDialog(name, submit, central=self.central, kind=kind, sources=self._sources,
                                      new_source=self._new_source_cb(), energy=energy, parent=self)

    def add_emission(self, kind: str) -> None:
        if self.current and self._require_target():
            self._run(self.make_emission_dialog(kind), f"Linie für {self.current} gespeichert")

    def make_nuclide_dialog(self) -> dialogs.NuclideDialog:
        def submit(v: dict) -> Any:
            name = v.pop("name")
            if self.central:
                return self.curation.add_nuclide(name, **v)
            v.pop("source", None)
            return self.db.user.add_nuclide(name, **v)
        return dialogs.NuclideDialog(submit, central=self.central, sources=self._sources,
                                     new_source=self._new_source_cb(), parent=self)

    def new_nuclide(self) -> None:
        if self._require_target():
            name = self._run(self.make_nuclide_dialog(), "Nuklid angelegt")
            if name:
                self.select_nuclide(name)

    def add_decay_mode(self) -> None:
        if not self.current:
            return
        if not self.central:
            if self._require_target():
                self._run(self.make_own_decays_dialog(), f"Eigene Zerfallswege für {self.current} gespeichert")
            return
        name = self.current

        def submit(v: dict) -> Any:
            return self.curation.add_decay_mode(name, v.pop("daughter"), v.pop("branching"), **v)
        self._run(dialogs.DecayModeDialog(name, submit, sources=self._sources, new_source=self._new_source_cb(),
                                          parent=self), "Zerfallsweg gespeichert")

    def make_own_decays_dialog(self) -> dialogs.OwnDecaysDialog:
        """Eigene Zerfallswege (Overlay) bearbeiten; vorbelegt mit den gerade gültigen Zweigen."""
        name = self.current
        own = [(r.get("daughter"), r.get("branching"), r.get("mode")) for r in self.db.user.decays(name)]
        if not own:
            own = [(m.daughter, m.effective_branching, m.mode) for m in self.db.decay_modes(name)
                   if not m.informational and m.daughter]

        def submit(v: dict) -> Any:
            return self.db.user.set_decays(name, v["decays"], comment=v["comment"])
        return dialogs.OwnDecaysDialog(name, submit, current=own, parent=self)

    def _confirm(self, text: str) -> bool:
        return QMessageBox.question(self, "NucDB", text) == QMessageBox.StandardButton.Yes

    def _central_removal(self, what: str, func: Callable[[str], Any]) -> None:
        if self.curation is None:
            QMessageBox.information(self, "NucDB", "Einträge der zentralen Datenbank lassen sich nur mit "
                                    "Kurationsordner entfernen (nucdb editor --curation …).")
            return
        self._run(dialogs.ReasonDialog(what, lambda v: func(v["comment"]), self), "Aus zentraler Datenbank entfernt")

    def remove_selected_value(self) -> None:
        r = selected_row(self.val_view)
        if r is None:
            return
        q, v = r
        if v.user:
            entry = next((e for e in self._overlay_entries() if e.kind == "value" and e.nuclide == self.current
                          and e.quantity == q and e.record.get("value") == v.value), None)
            if entry and self._confirm(f"Eigenen Wert {q} = {self._fmt_value(q, v)} löschen?"):
                self._guard(lambda: remove_overlay_entry(self.db.user, entry), "Eigener Wert gelöscht")
            return
        self._central_removal(f"{self.current}: {q} = {self._fmt_value(q, v)} (Quelle {v.source})",
                              lambda c: self.curation.remove_value(self.current, q, v.source, comment=c))

    def remove_selected_emission(self, kind: str) -> None:
        e: Emission | None = selected_row(self.em_views[kind][0])
        if e is None:
            return
        if e.user:
            if self._confirm(f"Eigene Linie {e.energy_kev:g} keV von {e.nuclide} löschen?"):
                self._guard(lambda: self.db.user.remove_emission(kind, e.nuclide, e.energy_kev), "Eigene Linie gelöscht")
            return
        self._central_removal(f"{e.nuclide}: {kind} {e.energy_kev:g} keV (Quelle {e.source})",
                              lambda c: self.curation.remove_emission(kind, e.nuclide, e.energy_kev, e.source,
                                                                      comment=c))

    def remove_selected_decay_mode(self) -> None:
        m: DecayMode | None = selected_row(self.dec_view)
        if m is None:
            return
        if m.user:
            if self.db.has_nuclide(m.parent) and not self.db.nuclide(m.parent).user:
                if self._confirm(f"Eigene Zerfallswege von {m.parent} löschen? Danach gelten wieder die "
                                 "Zweige der zentralen Datenbank."):
                    self._guard(lambda: self.db.user.remove_decays(m.parent), "Eigene Zerfallswege gelöscht")
            else:
                QMessageBox.information(self, "NucDB", "Zerfallswege eigener Nuklide mit „Hinzufügen“ (Ziel "
                                        "Ergänzungsdatenbank) ändern oder unter „Eigene Einträge“ löschen.")
            return
        self._central_removal(f"{m.parent} → {m.daughter} ({m.mode}, Quelle {m.source})",
                              lambda c: self.curation.remove_decay_mode(m.parent, m.daughter, m.mode, m.source,
                                                                        comment=c))

    def _guard(self, func: Callable[[], Any], msg: str) -> bool:
        try:
            func()
        except (ValueError, OverlayLockedError) as e:
            QMessageBox.warning(self, "NucDB", str(e))
            return False
        self._after_write(msg)
        return True

    def adopt_selected(self) -> None:
        e: OverlayEntry | None = selected_row(self.ov_view)
        if e is None or self.curation is None:
            return

        def submit(v: dict) -> Any:
            return self.curation.adopt(self.db.user, e, **v)
        self._run(dialogs.AdoptDialog(f"{e.nuclide}: {e.description}", submit, sources=self._sources,
                                      new_source=self._new_source_cb(), parent=self), "Übernommen")

    def delete_overlay_selected(self) -> None:
        e: OverlayEntry | None = selected_row(self.ov_view)
        if e is not None and self._confirm(f"Eigenen Eintrag löschen?\n{e.nuclide}: {e.description}"):
            self._guard(lambda: remove_overlay_entry(self.db.user, e), "Eigener Eintrag gelöscht")

    # ------------------------------------------------------------------------------------
    # Peak-Suche
    # ------------------------------------------------------------------------------------
    def peak_search(self) -> None:
        try:
            e = units.parse_quantity(self.peak_energy.text(), "energy", default_unit="keV").value
            tol = units.parse_quantity(self.peak_tol.text() or "1", "energy", default_unit="keV").value
            mh = self.peak_minhl.text().strip()
            min_hl = units.parse_quantity(mh, "half_life").value if mh else None
        except ValueError as ex:
            self.statusBar().showMessage(str(ex), 8000)
            return
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            res = self.db.find_gammas(e, tol, min_half_life_s=min_hl)
        finally:
            QGuiApplication.restoreOverrideCursor()
        self.peak_model.set_rows(res)
        self.peak_view.resizeColumnsToContents()
        self.statusBar().showMessage(f"{len(res)} Treffer bei {e:g} ± {tol:g} keV", 8000)

    # ------------------------------------------------------------------------------------
    # Neu laden
    # ------------------------------------------------------------------------------------
    def reload(self) -> None:
        self.db.reload()
        if self.curation is not None:
            self.curation.central.reload()
        self.refresh_all()
        self.statusBar().showMessage("Neu geladen", 4000)

    def changeEvent(self, event) -> None:  # noqa: N802 (Qt)
        # Änderungen anderer Tools am Overlay übernehmen, sobald das Fenster aktiv wird
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            QTimer.singleShot(0, self._check_external)
        super().changeEvent(event)

    def _check_external(self) -> None:
        if self.db.reload_if_changed():
            self.refresh_all()
            self.statusBar().showMessage("Ergänzungsdatenbank wurde von einem anderen Programm geändert – "
                                         "neu geladen", 8000)
