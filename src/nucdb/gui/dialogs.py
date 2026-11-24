"""Eingabedialoge des Editors. Jeder Dialog sammelt Felder und ruft ``submit(werte)`` auf.

Fehler (``ValueError``, gesperrtes Overlay …) werden im Dialog angezeigt; er bleibt dann offen.
"""

from __future__ import annotations

import re
from typing import Any, Callable

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from .. import units
from ..overlay import OverlayLockedError

Submit = Callable[[dict], Any]


class FormDialog(QDialog):
    def __init__(self, title: str, submit: Submit, parent: QWidget | None = None, intro: str | None = None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        self._submit = submit
        self.result_value: Any = None
        lay = QVBoxLayout(self)
        if intro:
            lab = QLabel(intro)
            lab.setWordWrap(True)
            lay.addWidget(lab)
        self.form = QFormLayout()
        lay.addLayout(self.form)
        self.error = QLabel()
        self.error.setStyleSheet("color: #b00020")
        self.error.setWordWrap(True)
        self.error.hide()
        lay.addWidget(self.error)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.try_accept)
        self.buttons.rejected.connect(self.reject)
        lay.addWidget(self.buttons)

    # Felder
    def line(self, label: str, placeholder: str = "", text: str = "") -> QLineEdit:
        w = QLineEdit(text)
        w.setPlaceholderText(placeholder)
        self.form.addRow(label, w)
        return w

    def check(self, label: str, checked: bool = False) -> QCheckBox:
        w = QCheckBox(label)
        w.setChecked(checked)
        self.form.addRow("", w)
        return w

    def combo(self, label: str, items: list[tuple[str, Any]]) -> QComboBox:
        w = QComboBox()
        for text, data in items:
            w.addItem(text, data)
        self.form.addRow(label, w)
        return w

    def values(self) -> dict:  # pragma: no cover - von Unterklassen überschrieben
        return {}

    def try_accept(self) -> bool:
        try:
            self.result_value = self._submit(self.values())
        except (ValueError, KeyError, OverlayLockedError) as e:
            msg = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
            self.error.setText(str(msg))
            self.error.show()
            return False
        self.accept()
        return True


def _opt(w: QLineEdit) -> str | None:
    t = w.text().strip()
    return t or None


class SourceField(QWidget):
    """Quellenauswahl (Pflicht für die zentrale Datenbank) mit Knopf „Neue Quelle …“."""

    def __init__(self, sources: Callable[[], dict[str, dict]], new_source: Callable[[QWidget], str | None] | None,
                 parent=None):
        super().__init__(parent)
        self._sources = sources
        self.combo = QComboBox()
        self.combo.setMinimumContentsLength(24)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.combo, 1)
        if new_source is not None:
            b = QPushButton("Neue Quelle …")
            b.clicked.connect(lambda: self._new(new_source))
            lay.addWidget(b)
        self.reload()

    def reload(self, select: str | None = None) -> None:
        cur = select or self.key()
        self.combo.clear()
        self.combo.addItem("– bitte wählen –", None)
        for key, s in sorted(self._sources().items()):
            flag = "" if s.get("redistributable", True) is not False else "  [nicht weitergebbar]"
            self.combo.addItem(f"{key} – {s.get('title') or ''}{flag}", key)
        if cur:
            i = self.combo.findData(cur)
            if i >= 0:
                self.combo.setCurrentIndex(i)

    def _new(self, new_source) -> None:
        key = new_source(self)
        if key:
            self.reload(key)

    def key(self) -> str | None:
        return self.combo.currentData()

    def set_key(self, key: str) -> None:
        i = self.combo.findData(key)
        if i >= 0:
            self.combo.setCurrentIndex(i)


class _CentralMixin:
    """Quelle + Kommentar am Ende eines Formulars (Quelle nur für die zentrale Datenbank)."""

    def add_source_and_comment(self: Any, central: bool, sources, new_source) -> None:
        self.source = None
        if central:
            self.source = SourceField(sources, new_source)
            self.form.addRow("Quelle *", self.source)
        self.comment = self.line("Kommentar", "Begründung / Bemerkung fürs Änderungsprotokoll")

    def common(self: Any) -> dict:
        d = {"comment": _opt(self.comment)}
        if self.source is not None:
            d["source"] = self.source.key()
        return d


class ValueDialog(FormDialog, _CentralMixin):
    def __init__(self, nuclide: str, quantities: dict[str, dict], submit: Submit, *, central: bool,
                 sources=None, new_source=None, quantity: str | None = None, parent=None):
        target = "zentrale Datenbank" if central else "Ergänzungsdatenbank (eigener Eintrag)"
        super().__init__(f"Wert für {nuclide}", submit, parent, intro=f"Ziel: {target}")
        items = [(f"{q} – {d.get('description') or ''} [{d.get('unit') or '–'}]", q)
                 for q, d in sorted(quantities.items())]
        self.quantity = self.combo("Größe", items)
        if quantity:
            self.quantity.setCurrentIndex(max(0, self.quantity.findData(quantity)))
        self.value = self.line("Wert *", "z. B. 5,2714(5) a  ·  2.92e-6 1/s  ·  59.9338")
        self.unc = self.line("Unsicherheit", "leer = aus der Eingabe (Klammer) bzw. unbekannt")
        self.preferred = self.check("bevorzugter Wert (übersteuert die anderen)", True)
        self.add_source_and_comment(central, sources, new_source)

    def values(self) -> dict:
        if not self.value.text().strip():
            raise ValueError("Bitte einen Wert eingeben")
        return {"quantity": self.quantity.currentData(), "value": self.value.text().strip(),
                "unc": _opt(self.unc), "preferred": self.preferred.isChecked(), **self.common()}


KINDS = [("Gamma/Röntgen", "gamma"), ("Alpha", "alpha"), ("Beta", "beta"), ("Elektronen", "electron")]


class EmissionDialog(FormDialog, _CentralMixin):
    def __init__(self, nuclide: str, submit: Submit, *, central: bool, kind: str = "gamma", sources=None,
                 new_source=None, energy: str = "", parent=None):
        target = "zentrale Datenbank" if central else "Ergänzungsdatenbank (eigene Linie, sofort in allen Tools)"
        super().__init__(f"Linie für {nuclide}", submit, parent, intro=f"Ziel: {target}")
        self.kind = self.combo("Strahlung", KINDS)
        self.kind.setCurrentIndex(max(0, self.kind.findData(kind)))
        self.energy = self.line("Energie *", "z. B. 1764.49(3) keV  ·  1,7645 MeV (Beta: Endpunkt)", energy)
        self.energy_unc = self.line("Energie-Unsicherheit", "keV, leer = aus der Eingabe")
        self.intensity = self.line("Intensität", "pro Zerfall: 0.153 oder 15,3 %; leer = unbekannt")
        self.intensity_unc = self.line("Intensitäts-Unsicherheit", "0.002 oder 0,2 %")
        self.radiation = self.combo("Linienart", [("G – Gamma", "G"), ("XK – K-Röntgen", "XK"),
                                                  ("XL – L-Röntgen", "XL")])
        self.type_beta = self.combo("Typ", [("B- (β⁻)", "B-"), ("B+ (β⁺)", "B+")])
        self.type_electron = self.line("Typ", "z. B. CE K, CE L, Auger K")
        self.mean = self.line("mittlere Energie", "nur Beta, keV")
        self.note = self.line("Notiz", "erscheint bei der Linie, z. B. „eigene Messung“")
        self.add_source_and_comment(central, sources, new_source)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self._kind_changed()

    def _kind_changed(self) -> None:
        k = self.kind.currentData()
        for w, show in ((self.radiation, k == "gamma"), (self.type_beta, k == "beta"),
                        (self.type_electron, k == "electron"), (self.mean, k == "beta")):
            w.setVisible(show)
            self.form.labelForField(w).setVisible(show)

    def values(self) -> dict:
        if not self.energy.text().strip():
            raise ValueError("Bitte eine Energie eingeben")
        k = self.kind.currentData()
        fields: dict[str, Any] = {}
        if k == "gamma":
            fields["radiation"] = self.radiation.currentData()
        elif k == "beta":
            fields["type"] = self.type_beta.currentData()
            if _opt(self.mean):
                fields["mean_energy_kev"] = units.parse_quantity(self.mean.text(), "energy", default_unit="keV").value
        elif k == "electron":
            fields["type"] = _opt(self.type_electron)
        return {"kind": k, "energy": self.energy.text().strip(), "energy_unc": _opt(self.energy_unc),
                "intensity": _opt(self.intensity), "intensity_unc": _opt(self.intensity_unc),
                "note": _opt(self.note), **fields, **self.common()}


_DECAY_LINE = re.compile(r"^\s*(\S+)\s+(.+?)(?:\s+([A-Za-z][A-Za-z0-9+\-]*))?\s*$")


def parse_decays(text: str) -> list[tuple]:
    """Zeilen „Tochter Anteil [Art]“ lesen, Anteil als Bruchteil oder in %."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.strip().startswith("#"):
            continue
        m = _DECAY_LINE.match(line)
        if not m:
            raise ValueError(f"Zerfallsweg Zeile {n}: „Tochter Anteil [Art]“ erwartet, z. B. „Tc-99m 87,73 % B-“")
        frac = units.parse_quantity(m.group(2), "fraction").value
        out.append((m.group(1), frac, m.group(3)) if m.group(3) else (m.group(1), frac))
    return out


class NuclideDialog(FormDialog, _CentralMixin):
    def __init__(self, submit: Submit, *, central: bool, sources=None, new_source=None, parent=None):
        target = "zentrale Datenbank" if central else "Ergänzungsdatenbank (eigenes Nuklid)"
        super().__init__("Neues Nuklid", submit, parent, intro=f"Ziel: {target}")
        self.name = self.line("Name *", "z. B. Mo-99, 99mTc, Ag-110m")
        self.half_life = self.line("Halbwertszeit", "z. B. 65,94 h  ·  2.92e-6 1/s")
        self.stable = self.check("stabil")
        self.decays = QPlainTextEdit()
        self.decays.setPlaceholderText("je Zeile: Tochter Anteil [Art]\nTc-99m 0.8773 B-\nTc-99 12,27 % B-")
        self.decays.setFixedHeight(90)
        self.form.addRow("Zerfallswege", self.decays)
        self.note = self.line("Notiz")
        self.add_source_and_comment(central, sources, new_source)

    def values(self) -> dict:
        if not self.name.text().strip():
            raise ValueError("Bitte einen Namen eingeben")
        return {"name": self.name.text().strip(), "half_life": _opt(self.half_life),
                "stable": self.stable.isChecked(), "decays": parse_decays(self.decays.toPlainText()),
                "note": _opt(self.note), **self.common()}


class DecayModeDialog(FormDialog, _CentralMixin):
    def __init__(self, parent_name: str, submit: Submit, *, sources, new_source=None, parent=None):
        super().__init__(f"Zerfallsweg von {parent_name}", submit, parent, intro="Ziel: zentrale Datenbank. "
                         "Derselbe Weg (Tochter, Art) derselben Quelle wird ersetzt.")
        self.daughter = self.line("Tochter *", "z. B. Tc-99m")
        self.mode = self.line("Art", "NUBASE-Schreibweise: B-, B+, EC, A, IT, SF …")
        self.branching = self.line("Anteil", "0.8773 oder 87,73 %; leer = unbekannt")
        self.add_source_and_comment(True, sources, new_source)

    def values(self) -> dict:
        b = _opt(self.branching)
        return {"daughter": self.daughter.text().strip(), "mode": _opt(self.mode),
                "branching": None if b is None else units.parse_quantity(b, "fraction").value, **self.common()}


class SourceDialog(FormDialog):
    def __init__(self, submit: Submit, parent=None):
        super().__init__("Neue Quelle", submit, parent, intro="Jeder Eintrag in der zentralen Datenbank verweist "
                         "auf eine Quelle. Bitte so angeben, dass man den Wert nachschlagen kann.")
        self.key = self.line("Kurzname *", "z. B. DDEP-2024, LAB-Bericht-7")
        self.title = self.line("Titel *")
        self.citation = self.line("Zitierweise", "Autoren, Titel, Zeitschrift (Jahr)")
        self.authors = self.line("Autoren")
        self.year = self.line("Jahr")
        self.url = self.line("URL")
        self.doi = self.line("DOI")
        self.license = self.line("Lizenz/Nutzung", "z. B. Fakten, frei zitierbar")
        self.redistributable = self.check("darf mit NucDB weitergegeben werden", True)
        self.comment = self.line("Kommentar")

    def values(self) -> dict:
        year = _opt(self.year)
        if year is not None and not year.isdigit():
            raise ValueError("Jahr bitte als Zahl")
        return {"key": self.key.text().strip(), "title": self.title.text().strip(), "citation": _opt(self.citation),
                "authors": _opt(self.authors), "year": int(year) if year else None, "url": _opt(self.url),
                "doi": _opt(self.doi), "license": _opt(self.license),
                "redistributable": self.redistributable.isChecked(), "comment": _opt(self.comment)}


class AdoptDialog(FormDialog):
    def __init__(self, description: str, submit: Submit, *, sources, new_source=None, parent=None):
        super().__init__("In die zentrale Datenbank übernehmen", submit, parent,
                         intro=f"{description}\n\nDer Eintrag bekommt die gewählte Quelle (Quellenpflicht) und "
                               "steht danach in der zentralen Datenbank.")
        self.source = SourceField(sources, new_source)
        self.form.addRow("Quelle *", self.source)
        self.comment = self.line("Kommentar", "z. B. geprüft anhand …")
        self.remove = self.check("danach aus der Ergänzungsdatenbank entfernen", True)

    def values(self) -> dict:
        return {"source": self.source.key(), "comment": _opt(self.comment),
                "remove_from_overlay": self.remove.isChecked()}


class ReasonDialog(FormDialog):
    def __init__(self, what: str, submit: Submit, parent=None):
        super().__init__("Aus der zentralen Datenbank entfernen", submit, parent,
                         intro=f"{what}\n\nDie Entfernung wird im Kurationsordner vermerkt und übersteht "
                               "einen Neuaufbau. Bitte begründen.")
        self.reason = self.line("Begründung *", "z. B. Dublette, Druckfehler der Quelle …")

    def values(self) -> dict:
        return {"comment": self.reason.text().strip()}


__all__ = ["FormDialog", "ValueDialog", "EmissionDialog", "NuclideDialog", "DecayModeDialog", "SourceDialog",
           "AdoptDialog", "ReasonDialog", "SourceField", "parse_decays", "KINDS"]
