"""Табличні моделі Qt (власні QAbstractTableModel) для QTableView.

RecordTableModel — таблиця записів, стовпці якої описано об'єктами Column;
MatrixTableModel — матриця доступу: клітинки «ЧЗРВ», кольори рівнів і позначки.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, Generic, TypeVar, Union

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QObject, QPersistentModelIndex, Qt, Signal
from PySide6.QtGui import QColor, QFont

from app import palette
from app.domain.models import GAP_MARK, NO_OPERATIONS, Operation, OperationSet, operations_cell
from app.services.matrix import CellDiff, cell_level

T = TypeVar("T")
ModelIndex = Union[QModelIndex, QPersistentModelIndex]

SORT_ROLE = int(Qt.ItemDataRole.UserRole)
CELL_ROLE = int(Qt.ItemDataRole.UserRole) + 1

LEFT = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
CENTER = Qt.AlignmentFlag.AlignCenter
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

_ROOT = QModelIndex()


@dataclass(frozen=True)
class Column(Generic[T]):
    """Опис стовпця таблиці записів."""

    title: str
    text: Callable[[T], str]
    tooltip: Callable[[T], str] | None = None
    fill: Callable[[T], str | None] | None = None  # колір фону клітинки
    align: Qt.AlignmentFlag = LEFT
    sort_key: Callable[[T], int | float | str] | None = None  # лише прості типи: їх порівнює Qt
    bold: bool | Callable[[T], bool] = False  # для всього стовпця або окремих записів
    width: int | None = None
    edit_value: Callable[[T], Any] | None = None  # значення для редактора
    on_edit: Callable[[T, Any], list[str]] | None = None  # застосування зміни; повертає помилки
    checked: Callable[[T], bool] | None = None  # стовпець-прапорець
    header_tooltip: str = ""  # пояснення до заголовка стовпця


def _is_checked(value: Any) -> bool:
    """Перетворює значення CheckStateRole (перелік або ціле) на логічне."""
    if isinstance(value, Qt.CheckState):
        return value == Qt.CheckState.Checked
    return int(value) == Qt.CheckState.Checked.value


class RecordTableModel(QAbstractTableModel, Generic[T]):
    """Таблиця записів: рядок — запис, стовпці — описи Column."""

    edit_failed = Signal(str)

    def __init__(
        self,
        columns: Sequence[Column[T]],
        row_header: Callable[[T], str] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._columns = list(columns)
        self._rows: list[T] = []
        self._row_header = row_header
        self._bold = QFont()
        self._bold.setBold(True)

    @property
    def columns(self) -> list[Column[T]]:
        """Описи стовпців."""
        return self._columns

    @property
    def records(self) -> list[T]:
        """Поточні записи."""
        return list(self._rows)

    def record(self, row: int) -> T:
        """Запис за номером рядка."""
        return self._rows[row]

    def set_rows(self, rows: Sequence[T]) -> None:
        """Оновлює записи; за тієї ж кількості рядків зберігає виділення та прокрутку."""
        new_rows = list(rows)
        if new_rows and len(new_rows) == len(self._rows):
            self._rows = new_rows
            last = self.index(len(new_rows) - 1, len(self._columns) - 1)
            self.dataChanged.emit(self.index(0, 0), last)
            self.headerDataChanged.emit(Qt.Orientation.Vertical, 0, len(new_rows) - 1)
        else:
            self.beginResetModel()
            self._rows = new_rows
            self.endResetModel()

    def rowCount(self, parent: ModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: ModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(self._columns)

    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        record = self._rows[index.row()]
        column = self._columns[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return column.text(record)
        if role == Qt.ItemDataRole.EditRole:
            return column.edit_value(record) if column.edit_value else column.text(record)
        if role == Qt.ItemDataRole.ToolTipRole:
            return column.tooltip(record) if column.tooltip else None
        if role == Qt.ItemDataRole.BackgroundRole and column.fill is not None:
            color = column.fill(record)
            return QColor(color) if color else None
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return column.align.value
        if role == Qt.ItemDataRole.FontRole and column.bold:
            bold = column.bold(record) if callable(column.bold) else column.bold
            return self._bold if bold else None
        if role == Qt.ItemDataRole.CheckStateRole and column.checked is not None:
            state = Qt.CheckState.Checked if column.checked(record) else Qt.CheckState.Unchecked
            return state.value
        if role == SORT_ROLE:
            return column.sort_key(record) if column.sort_key else column.text(record)
        return None

    def flags(self, index: ModelIndex) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        column = self._columns[index.column()]
        if column.on_edit is not None:
            if column.checked is not None:
                flags |= Qt.ItemFlag.ItemIsUserCheckable
            else:
                flags |= Qt.ItemFlag.ItemIsEditable
        return flags

    def setData(self, index: ModelIndex, value: Any, role: int = Qt.ItemDataRole.EditRole) -> bool:
        if not index.isValid():
            return False
        column = self._columns[index.column()]
        if column.on_edit is None:
            return False
        if column.checked is not None:
            if role != Qt.ItemDataRole.CheckStateRole:
                return False
            value = _is_checked(value)
        elif role != Qt.ItemDataRole.EditRole:
            return False
        errors = column.on_edit(self._rows[index.row()], value)
        if errors:
            self.edit_failed.emit("\n".join(errors))
            return False
        return True

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        if orientation == Qt.Orientation.Horizontal:
            if section >= len(self._columns):
                return None
            if role == Qt.ItemDataRole.DisplayRole:
                return self._columns[section].title
            if role == Qt.ItemDataRole.ToolTipRole:
                return self._columns[section].header_tooltip or None
            return None
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if self._row_header is not None and section < len(self._rows):
            return self._row_header(self._rows[section])
        return str(section + 1)


class GlyphStyle(Enum):
    """Стиль літери операції в клітинці матриці."""

    GRANTED = "надано"
    GRANT = "індивідуальний дозвіл"
    ABSENT = "немає"
    KEPT = "збережено"
    REMOVED = "вилучено"
    ADDED = "додано"


@dataclass(frozen=True)
class CellView:
    """Вигляд клітинки матриці: літери зі стилями, колір фону, позначка, підказка."""

    glyphs: tuple[tuple[str, GlyphStyle], ...]
    fill: str
    marker: bool  # позначка індивідуального дозволу (трикутник у куті)
    tooltip: str
    text: str  # текстове подання для копіювання й читачів екрана


def access_cell(
    operations: OperationSet,
    grant_operations: OperationSet = NO_OPERATIONS,
    tooltip: str = "",
) -> CellView:
    """Клітинка матриці доступу: «ЧЗРВ» з «·» на місці відсутніх операцій.

    Колір — за найнебезпечнішою операцією; літери з індивідуального дозволу
    мають окремий стиль, а сама клітинка — позначку.
    """
    glyphs = tuple(
        (operation.short, GlyphStyle.GRANT if operation in grant_operations else GlyphStyle.GRANTED)
        if operation in operations
        else (GAP_MARK, GlyphStyle.ABSENT)
        for operation in Operation
    )
    return CellView(
        glyphs=glyphs,
        fill=palette.CELL_FILL[cell_level(operations)],
        marker=bool(grant_operations & operations),
        tooltip=tooltip,
        text=operations_cell(operations),
    )


def diff_cell(diff: CellDiff, tooltip: str = "") -> CellView:
    """Клітинка матриці змін: збережені операції — зелені, вилучені — червоні закреслені,
    додані — підкреслені; змінені клітинки мають світло-червоне тло."""
    glyphs = tuple(
        (operation.short, GlyphStyle.KEPT)
        if operation in diff.kept
        else (operation.short, GlyphStyle.REMOVED)
        if operation in diff.removed
        else (operation.short, GlyphStyle.ADDED)
        if operation in diff.added
        else (GAP_MARK, GlyphStyle.ABSENT)
        for operation in Operation
    )
    if diff.changed:
        fill = palette.CHANGED_FILL
    elif diff.kept:
        fill = palette.WHITE
    else:
        fill = palette.TRACK
    return CellView(
        glyphs=glyphs,
        fill=fill,
        marker=False,
        tooltip=tooltip,
        text=operations_cell(diff.kept | diff.added),
    )


@dataclass(frozen=True)
class MatrixRow:
    """Рядок матриці: суб'єкт (роль або користувач) і його клітинки."""

    key: str
    header: str
    tooltip: str
    info: tuple[str, ...]  # значення додаткових текстових стовпців
    cells: tuple[CellView, ...]


@dataclass(frozen=True)
class MatrixData:
    """Повний вміст матриці для відображення."""

    info_titles: tuple[str, ...]
    column_keys: tuple[str, ...]
    column_headers: tuple[str, ...]
    column_tooltips: tuple[str, ...]
    rows: tuple[MatrixRow, ...]


_EMPTY_MATRIX = MatrixData((), (), (), (), ())


class MatrixTableModel(QAbstractTableModel):
    """Матриця доступу: рядки — суб'єкти, стовпці — додаткові поля та ресурси."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._data = _EMPTY_MATRIX

    @property
    def matrix(self) -> MatrixData:
        """Поточний вміст матриці."""
        return self._data

    def set_matrix(self, data: MatrixData) -> None:
        """Оновлює матрицю; за тієї ж форми зберігає виділення."""
        same_shape = (
            len(data.rows) == len(self._data.rows)
            and len(data.info_titles) == len(self._data.info_titles)
            and len(data.column_keys) == len(self._data.column_keys)
            and bool(data.rows)
        )
        if same_shape:
            self._data = data
            last = self.index(len(data.rows) - 1, self.columnCount() - 1)
            self.dataChanged.emit(self.index(0, 0), last)
            self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.columnCount() - 1)
            self.headerDataChanged.emit(Qt.Orientation.Vertical, 0, len(data.rows) - 1)
        else:
            self.beginResetModel()
            self._data = data
            self.endResetModel()

    def cell_key(self, index: ModelIndex) -> tuple[str, str] | None:
        """(суб'єкт, ресурс) для клітинки-ресурсу; None — для додаткових стовпців."""
        info = len(self._data.info_titles)
        if not index.isValid() or index.column() < info:
            return None
        return self._data.rows[index.row()].key, self._data.column_keys[index.column() - info]

    def rowCount(self, parent: ModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(self._data.rows)

    def columnCount(self, parent: ModelIndex = _ROOT) -> int:
        return 0 if parent.isValid() else len(self._data.info_titles) + len(self._data.column_keys)

    def data(self, index: ModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        row = self._data.rows[index.row()]
        info = len(self._data.info_titles)
        if index.column() < info:
            if role == Qt.ItemDataRole.DisplayRole:
                return row.info[index.column()]
            if role == Qt.ItemDataRole.ToolTipRole:
                return row.tooltip
            if role == Qt.ItemDataRole.TextAlignmentRole:
                return LEFT.value
            return None
        cell = row.cells[index.column() - info]
        if role == Qt.ItemDataRole.DisplayRole:
            return cell.text
        if role == Qt.ItemDataRole.ToolTipRole:
            return cell.tooltip
        if role == Qt.ItemDataRole.BackgroundRole:
            return QColor(cell.fill)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return CENTER.value
        if role == CELL_ROLE:
            return cell
        return None

    def headerData(
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> Any:
        info = len(self._data.info_titles)
        if orientation == Qt.Orientation.Horizontal:
            if section < info:
                return self._data.info_titles[section] if role == Qt.ItemDataRole.DisplayRole else None
            position = section - info
            if position >= len(self._data.column_keys):
                return None
            if role == Qt.ItemDataRole.DisplayRole:
                return self._data.column_headers[position]
            if role == Qt.ItemDataRole.ToolTipRole:
                return self._data.column_tooltips[position]
            return None
        if section >= len(self._data.rows):
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            return self._data.rows[section].header
        if role == Qt.ItemDataRole.ToolTipRole:
            return self._data.rows[section].tooltip
        return None
