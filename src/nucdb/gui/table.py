"""Einfaches Tabellenmodell: Zeilenobjekte + Spaltenfunktionen, sortierbar, eigene Einträge markiert."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

ROW_ROLE = Qt.ItemDataRole.UserRole
SORT_ROLE = Qt.ItemDataRole.UserRole + 1
USER_BRUSH = QBrush(QColor(30, 110, 200))


@dataclass
class Column:
    header: str
    text: Callable[[Any], Any]
    sort: Callable[[Any], Any] | None = None      # Sortierschlüssel (Standard: Text)
    tooltip: Callable[[Any], str | None] | None = None
    align_right: bool = False


def _is_user(row: Any) -> bool:
    if isinstance(row, tuple):
        return any(getattr(x, "user", False) is True for x in row)
    return getattr(row, "user", False) is True


class RecordModel(QAbstractTableModel):
    def __init__(self, columns: Sequence[Column], rows: Sequence[Any] = (), parent=None):
        super().__init__(parent)
        self.columns = list(columns)
        self.rows: list[Any] = list(rows)
        self._bold = QFont()
        self._bold.setBold(True)

    def set_rows(self, rows: Sequence[Any]) -> None:
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802 (Qt)
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.columns[section].header
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self.rows[index.row()]
        col = self.columns[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            v = col.text(row)
            return "" if v is None else str(v)
        if role == ROW_ROLE:
            return row
        if role == SORT_ROLE:
            v = col.sort(row) if col.sort else col.text(row)
            return (1, "") if v is None else (0, v)
        if role == Qt.ItemDataRole.ToolTipRole and col.tooltip:
            return col.tooltip(row)
        if role == Qt.ItemDataRole.ForegroundRole and _is_user(row):
            return USER_BRUSH
        if role == Qt.ItemDataRole.TextAlignmentRole and col.align_right:
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None


class SortProxy(QSortFilterProxyModel):
    """Sortiert nach ``SORT_ROLE``; Filter über eine Funktion auf dem Zeilenobjekt."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSortRole(SORT_ROLE)
        self.row_filter: Callable[[Any], bool] | None = None

    def lessThan(self, left, right) -> bool:  # noqa: N802
        a, b = left.data(SORT_ROLE), right.data(SORT_ROLE)
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)

    def filterAcceptsRow(self, source_row, source_parent) -> bool:  # noqa: N802
        if self.row_filter is None:
            return True
        return self.row_filter(self.sourceModel().rows[source_row])

    def set_filter(self, func: Callable[[Any], bool] | None) -> None:
        if hasattr(self, "beginFilterChange"):          # Qt ≥ 6.10
            self.beginFilterChange()
            self.row_filter = func
            self.endFilterChange()
        else:
            self.row_filter = func
            self.invalidateFilter()


def make_table(columns: Sequence[Column], parent=None) -> tuple[QTableView, RecordModel, SortProxy]:
    model = RecordModel(columns, parent=parent)
    proxy = SortProxy(parent)
    proxy.setSourceModel(model)
    view = QTableView(parent)
    view.setModel(proxy)
    view.setSortingEnabled(True)
    view.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setAlternatingRowColors(True)
    view.verticalHeader().setVisible(False)
    view.verticalHeader().setDefaultSectionSize(22)
    view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    view.horizontalHeader().setStretchLastSection(True)
    return view, model, proxy


def selected_row(view: QTableView) -> Any:
    idx = view.selectionModel().selectedRows() if view.selectionModel() else []
    return idx[0].data(ROW_ROLE) if idx else None
