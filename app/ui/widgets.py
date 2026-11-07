"""Допоміжні віджети: полотно діаграм, легенда, делегати й фабрики таблиць."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import (
    QAbstractItemModel,
    QPointF,
    QRectF,
    QSize,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QMainWindow,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QVBoxLayout,
    QWidget,
)

# Імпорт після PySide6: matplotlib обере саме цю прив'язку Qt.
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from app import palette
from app.ui.table_models import (
    CELL_ROLE,
    LEFT,
    SORT_ROLE,
    CellView,
    GlyphStyle,
    MatrixTableModel,
    ModelIndex,
    RecordTableModel,
)
from app.ui.theme import monospace_font

RESOURCE_COLUMN_WIDTH = 66
MATRIX_ROW_HEIGHT = 24
TABLE_ROW_HEIGHT = 24

GLYPH_COLORS: dict[GlyphStyle, str] = {
    GlyphStyle.GRANTED: palette.INK,
    GlyphStyle.GRANT: palette.GRANT_INK,
    GlyphStyle.ABSENT: palette.INK_MUTED,
    GlyphStyle.KEPT: palette.KEPT_INK,
    GlyphStyle.REMOVED: palette.STATUS_CRITICAL,
    GlyphStyle.ADDED: palette.ACCENT,
}


def hint_label(text: str) -> QLabel:
    """Приглушений пояснювальний текст із перенесенням рядків."""
    label = QLabel(text)
    label.setWordWrap(True)
    label.setProperty("role", "hint")
    return label


def section(title: str, content: QWidget | QLayout) -> QGroupBox:
    """Рамка з коротким заголовком і вмістом (без пояснювального тексту — він у підказках)."""
    box = QGroupBox(title)
    layout = QVBoxLayout(box)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(6)
    if isinstance(content, QWidget):
        layout.addWidget(content)
    else:
        layout.addLayout(content)
    return box


def fill_combo(combo: QComboBox, items: Sequence[tuple[str, str]], default: str | None = None) -> None:
    """Перезаповнює список, зберігаючи вибране значення (інакше — default або перший пункт)."""
    current = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    for label, value in items:
        combo.addItem(label, value)
    position = combo.findData(current)
    if position < 0 and default is not None:
        position = combo.findData(default)
    combo.setCurrentIndex(position if position >= 0 else 0)
    combo.blockSignals(False)


def show_status(widget: QWidget, text: str, timeout_ms: int = 6000) -> None:
    """Показує тимчасове повідомлення в рядку стану головного вікна."""
    window = widget.window()
    if isinstance(window, QMainWindow):
        window.statusBar().showMessage(text, timeout_ms)


def paint_cell(painter: QPainter, rect: QRectF, cell: CellView, font: QFont) -> None:
    """Малює клітинку матриці: фон рівня, літери «ЧЗРВ», позначку дозволу."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.fillRect(rect, QColor(cell.fill))
    metrics = QFontMetricsF(font)
    slot = max(metrics.horizontalAdvance(char) for char in "ЧЗРВ·") + 1.0
    x = rect.center().x() - slot * len(cell.glyphs) / 2
    baseline = rect.center().y() + (metrics.ascent() - metrics.descent()) / 2
    for char, style in cell.glyphs:
        glyph_font = QFont(font)
        glyph_font.setUnderline(style in (GlyphStyle.GRANT, GlyphStyle.ADDED))
        glyph_font.setStrikeOut(style is GlyphStyle.REMOVED)
        painter.setFont(glyph_font)
        painter.setPen(QColor(GLYPH_COLORS[style]))
        painter.drawText(QPointF(x + (slot - metrics.horizontalAdvance(char)) / 2, baseline), char)
        x += slot
    if cell.marker:
        size = min(10.0, rect.height() / 3)
        corner = QPolygonF(
            [
                QPointF(rect.right() - size, rect.top()),
                QPointF(rect.right(), rect.top()),
                QPointF(rect.right(), rect.top() + size),
            ]
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(palette.GRANT_INK))
        painter.drawPolygon(corner)
    painter.restore()


class MatrixDelegate(QStyledItemDelegate):
    """Делегат клітинок матриці: малює CellView; інші стовпці — стандартно."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._font = monospace_font(11.0, True)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: ModelIndex) -> None:
        cell = index.data(CELL_ROLE)
        if not isinstance(cell, CellView):
            super().paint(painter, option, index)
            return
        rect = QRectF(option.rect)
        paint_cell(painter, rect, cell, self._font)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hovered:
            painter.save()
            painter.setPen(QPen(QColor(palette.ACCENT), 2.0 if selected else 1.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(1, 1, -1, -1))
            painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index: ModelIndex) -> QSize:
        if not isinstance(index.data(CELL_ROLE), CellView):
            return super().sizeHint(option, index)
        metrics = QFontMetricsF(self._font)
        return QSize(int(metrics.horizontalAdvance("ЧЗРВ") + 24), int(metrics.height() + 8))


class CellSample(QWidget):
    """Зразок клітинки для легенди — намальований тим самим кодом, що й таблиця."""

    def __init__(self, cell: CellView, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cell = cell
        self._font = monospace_font(10.0, True)
        metrics = QFontMetricsF(self._font)
        self.setFixedSize(int(metrics.horizontalAdvance("ЧЗРВ") + 22), int(metrics.height() + 8))

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        rect = QRectF(self.rect())
        paint_cell(painter, rect, self._cell, self._font)
        painter.setPen(QPen(QColor(palette.AXIS), 1.0))
        painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))
        painter.end()


class LegendBar(QWidget):
    """Легенда в один рядок: зразки клітинок з підписами."""

    def __init__(self, items: Sequence[tuple[CellView, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
        for cell, text in items:
            pair = QHBoxLayout()
            pair.setSpacing(6)
            pair.addWidget(CellSample(cell))
            pair.addWidget(QLabel(text))
            layout.addLayout(pair)
        layout.addStretch(1)


class ChartView(QWidget):
    """Полотно для фігури matplotlib (FigureCanvasQTAgg); фігуру можна замінювати."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._canvas: FigureCanvasQTAgg | None = None
        self.setMinimumSize(320, 240)

    @property
    def figure(self) -> Figure | None:
        """Поточна фігура."""
        return self._canvas.figure if self._canvas is not None else None

    def set_figure(self, figure: Figure) -> None:
        """Показує нову фігуру замість попередньої."""
        canvas = FigureCanvasQTAgg(figure)  # type: ignore[no-untyped-call]
        canvas.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        if self._canvas is None:
            self._layout.addWidget(canvas)
        else:
            self._layout.replaceWidget(self._canvas, canvas)
            self._canvas.setParent(None)
            self._canvas.deleteLater()
        self._canvas = canvas
        canvas.draw_idle()  # type: ignore[no-untyped-call]


class ChoiceDelegate(QStyledItemDelegate):
    """Редактор-список для вибору значення (напр. ролі користувача)."""

    def __init__(
        self, choices: Callable[[], Sequence[tuple[str, str]]], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._choices = choices

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: ModelIndex) -> QWidget:
        combo = QComboBox(parent)
        for label, value in self._choices():
            combo.addItem(label, value)
        combo.activated.connect(lambda _position: self._commit(combo))
        return combo

    def _commit(self, combo: QComboBox) -> None:
        self.commitData.emit(combo)
        self.closeEditor.emit(combo, QAbstractItemDelegate.EndEditHint.NoHint)

    def setEditorData(self, editor: QWidget, index: ModelIndex) -> None:
        if isinstance(editor, QComboBox):
            position = editor.findData(index.data(Qt.ItemDataRole.EditRole))
            editor.setCurrentIndex(max(position, 0))

    def setModelData(self, editor: QWidget, model: QAbstractItemModel, index: ModelIndex) -> None:
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentData(), Qt.ItemDataRole.EditRole)


class SpinDelegate(QStyledItemDelegate):
    """Редактор цілого числа в заданих межах (напр. коефіцієнт критичності K)."""

    def __init__(self, minimum: int, maximum: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._minimum = minimum
        self._maximum = maximum

    def createEditor(self, parent: QWidget, option: QStyleOptionViewItem, index: ModelIndex) -> QWidget:
        spin = QSpinBox(parent)
        spin.setRange(self._minimum, self._maximum)
        spin.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return spin

    def setEditorData(self, editor: QWidget, index: ModelIndex) -> None:
        if isinstance(editor, QSpinBox):
            editor.setValue(int(index.data(Qt.ItemDataRole.EditRole)))

    def setModelData(self, editor: QWidget, model: QAbstractItemModel, index: ModelIndex) -> None:
        if isinstance(editor, QSpinBox):
            editor.interpretText()
            model.setData(index, editor.value(), Qt.ItemDataRole.EditRole)


def make_table(
    model: QAbstractItemModel,
    *,
    sortable: bool = False,
    row_header: bool = False,
    stretch_column: int | None = None,
) -> QTableView:
    """Таблиця записів зі стандартними налаштуваннями застосунку.

    stretch_column — стовпець, що забирає вільну ширину (інакше — останній);
    так таблиця вміщується без горизонтальної прокрутки.
    """
    view = QTableView()
    if sortable:
        proxy = QSortFilterProxyModel(view)
        proxy.setSourceModel(model)
        proxy.setSortRole(SORT_ROLE)
        view.setModel(proxy)
        view.setSortingEnabled(True)
    else:
        view.setModel(model)
    view.setAlternatingRowColors(True)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setWordWrap(False)
    view.verticalHeader().setVisible(row_header)
    view.verticalHeader().setDefaultSectionSize(TABLE_ROW_HEIGHT)
    header = view.horizontalHeader()
    header.setDefaultAlignment(LEFT)
    header.setHighlightSections(False)
    if isinstance(model, RecordTableModel):
        for position, column in enumerate(model.columns):
            if column.width is not None:
                view.setColumnWidth(position, column.width)
    if stretch_column is None:
        header.setStretchLastSection(True)
    else:
        header.setStretchLastSection(False)
        header.setSectionResizeMode(stretch_column, QHeaderView.ResizeMode.Stretch)
    return view


def fit_table_height(view: QTableView, rows: int) -> None:
    """Фіксує висоту таблиці так, щоб rows рядків було видно без вертикальної прокрутки."""
    header = view.horizontalHeader().sizeHint().height()
    body = rows * view.verticalHeader().defaultSectionSize()
    view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    view.setFixedHeight(header + body + 2 * view.frameWidth() + 2)


def make_matrix_view(model: MatrixTableModel) -> QTableView:
    """Таблиця-матриця: клітинки «ЧЗРВ», клацання по клітинці — редагування."""
    view = QTableView()
    view.setModel(model)
    view.setItemDelegate(MatrixDelegate(view))
    view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectItems)
    view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    view.setMouseTracking(True)
    view.setCornerButtonEnabled(False)
    vertical = view.verticalHeader()
    vertical.setDefaultSectionSize(MATRIX_ROW_HEIGHT)
    vertical.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    vertical.setDefaultAlignment(LEFT)
    horizontal = view.horizontalHeader()
    horizontal.setDefaultSectionSize(RESOURCE_COLUMN_WIDTH)
    horizontal.setMinimumSectionSize(60)
    horizontal.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
    horizontal.setHighlightSections(False)
    return view


def fit_matrix_columns(view: QTableView, model: MatrixTableModel, info_width: int = 110) -> None:
    """Ширина стовпців матриці: додаткові поля — info_width, ресурси — однакова."""
    info = len(model.matrix.info_titles)
    for column in range(info):
        view.setColumnWidth(column, info_width)
    for column in range(info, model.columnCount()):
        view.setColumnWidth(column, RESOURCE_COLUMN_WIDTH)
