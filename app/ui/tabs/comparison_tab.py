"""Вкладка «Порівняння»: порівняльна таблиця двох моделей і діаграми «до / після»."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QTableView, QTabWidget, QVBoxLayout, QWidget

from app import palette
from app.export.charts import heatmaps_figure, protection_figure, role_operations_figure
from app.services.analysis import AnalysisResult
from app.services.comparison import ComparisonRow
from app.services.risk import ProtectionLevel
from app.ui.state import ModelState
from app.ui.table_models import CENTER, Column, RecordTableModel
from app.ui.tabs.base import ResultTab
from app.ui.widgets import ChartView, make_table, section

CHANGE_HINT = (
    "Зелене тло — захищеність зросла, червоне — знизилася.\n"
    "Для відсоткових показників зміна — у відсоткових пунктах (в. п.)."
)


@dataclass(frozen=True)
class _Line:
    """Рядок таблиці: заголовок групи показників (row = None) або сам показник."""

    section: str
    row: ComparisonRow | None = None


def comparison_lines(rows: tuple[ComparisonRow, ...]) -> list[_Line]:
    """Рядки порівняльної таблиці з заголовками груп показників."""
    lines: list[_Line] = []
    current = ""
    for row in rows:
        if row.section != current:
            current = row.section
            lines.append(_Line(current))
        lines.append(_Line(current, row))
    return lines


def _change_fill(line: _Line) -> str | None:
    """Тло зміни: зелене — захищеність зросла, червоне — знизилася."""
    if line.row is None:
        return palette.PAGE
    improved = line.row.improved
    if improved is None:
        return None
    return palette.PROTECTION_FILL[ProtectionLevel.HIGH if improved else ProtectionLevel.LOW]


class ComparisonTab(ResultTab):
    """Порівняння початкової та оптимізованої моделей."""

    def __init__(self, state: ModelState, parent: QWidget | None = None) -> None:
        super().__init__(state, parent)
        self._table: RecordTableModel[_Line] = RecordTableModel(self._columns(), parent=self)
        self._view = make_table(self._table, stretch_column=0)
        self._table_box = section("Показники", self._view)
        self._roles_chart = ChartView()
        self._protection_chart = ChartView()
        self._heatmap_chart = ChartView()
        self._charts = QTabWidget()
        self._charts.addTab(self._roles_chart, "Операції за ролями")
        self._charts.addTab(self._protection_chart, "Захищеність ресурсів")
        self._charts.addTab(self._heatmap_chart, "Теплові карти матриць")
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._table_box)
        splitter.addWidget(section("Діаграми", self._charts))
        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([720, 560])
        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)

    @property
    def table_view(self) -> QTableView:
        """Порівняльна таблиця."""
        return self._view

    @property
    def charts(self) -> QTabWidget:
        """Вкладки з діаграмами."""
        return self._charts

    def refresh(self, result: AnalysisResult) -> None:
        self._table.set_rows(comparison_lines(result.comparison))
        self._roles_chart.set_figure(role_operations_figure(result))
        self._protection_chart.set_figure(protection_figure(result))
        self._heatmap_chart.set_figure(heatmaps_figure(result))

    @staticmethod
    def _columns() -> list[Column[_Line]]:
        def label(line: _Line) -> str:
            return f"    {line.row.label}" if line.row is not None else line.section

        def trend(line: _Line) -> str:
            return f"{line.row.label}: {line.row.trend.value}" if line.row is not None else line.section

        return [
            Column(
                "Показник", label, tooltip=trend, bold=lambda line: line.row is None,
                fill=lambda line: palette.PAGE if line.row is None else None,
            ),
            Column(
                "Початкова", lambda line: line.row.initial_text if line.row else "",
                fill=lambda line: palette.PAGE if line.row is None else None, align=CENTER, width=76,
            ),
            Column(
                "Оптимізована", lambda line: line.row.optimized_text if line.row else "",
                fill=lambda line: palette.PAGE if line.row is None else None, align=CENTER, width=96,
            ),
            Column(
                "Зміна", lambda line: line.row.change_text if line.row else "",
                fill=_change_fill, align=CENTER, width=86, header_tooltip=CHANGE_HINT,
            ),
            Column(
                "Зміна, %", lambda line: line.row.change_percent_text if line.row else "",
                fill=_change_fill, align=CENTER, width=76, header_tooltip=CHANGE_HINT,
            ),
        ]
