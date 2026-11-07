"""Тести GUI без показу вікон (платформа Qt «offscreen»): стан, табличні моделі, головне вікно."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QToolBar  # noqa: E402

from app.domain.models import Enterprise, Operation  # noqa: E402
from app.export.charts import CHARTS  # noqa: E402
from app.services.analysis import AnalysisResult  # noqa: E402
from app.ui.exporting import save_all_figures, scheme_images  # noqa: E402
from app.services.optimizer import build_min_privilege_model  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.matrix_data import role_matrix_data, user_matrix_data  # noqa: E402
from app.ui.scheme import SchemeScene, export_png, export_svg  # noqa: E402
from app.ui.state import ModelState  # noqa: E402
from app.ui.table_models import Column, GlyphStyle, RecordTableModel  # noqa: E402
from app.ui.matrix_data import role_changes_data, user_changes_data  # noqa: E402
from app.ui.tabs.base import ResultTab  # noqa: E402
from app.ui.tabs.comparison_tab import ComparisonTab, comparison_lines  # noqa: E402
from app.ui.tabs.optimization_tab import FUNCTION_RESOURCE_COLUMN, OptimizationTab  # noqa: E402
from app.ui.tabs.risk_tab import RiskTab  # noqa: E402
from app.ui.tabs.scheme_tab import SchemeTab  # noqa: E402
from app.ui.tabs.simulation_tab import SimulationTab  # noqa: E402
from app.ui.theme import apply_theme  # noqa: E402

R, W, E, D = Operation.READ, Operation.WRITE, Operation.EDIT, Operation.DELETE


@pytest.fixture(scope="module")
def qapp() -> QCoreApplication:
    app = QApplication.instance() or QApplication([])
    if isinstance(app, QApplication):
        apply_theme(app)
    return app


def test_state_undo_redo(qapp: QCoreApplication, enterprise: Enterprise) -> None:
    state = ModelState(enterprise)
    received: list[AnalysisResult] = []
    state.changed.connect(received.append)
    assert state.set_role_operations("EMPLOYEE", "R1", {R, W, E}) == []
    assert state.result.initial.user_stats.allowed == 305
    assert state.is_dirty and state.can_undo and not state.can_redo
    state.undo()
    assert state.result.initial.user_stats.allowed == 316
    assert state.can_redo
    state.redo()
    assert state.result.initial.user_stats.allowed == 305
    assert len(received) == 3


def test_state_rejects_invalid_and_ignores_noop(qapp: QCoreApplication, enterprise: Enterprise) -> None:
    state = ModelState(enterprise)
    broken = enterprise.with_resource(replace(enterprise.resource("R1"), name="  "))
    errors = state.apply(broken)
    assert errors and "назва не може бути порожньою" in errors[0]
    assert state.enterprise == enterprise
    assert state.apply(enterprise) == []
    assert not state.can_undo and not state.is_dirty


def test_state_user_rights(qapp: QCoreApplication, enterprise: Enterprise) -> None:
    state = ModelState(enterprise)
    assert state.set_user_rights("U12", "R2", {R}, "") == []
    assert state.enterprise.initial_model.grant("U12", "R2") is None
    assert len(state.result.findings) == 155


def test_matrix_data(qapp: QCoreApplication, result: AnalysisResult) -> None:
    roles = role_matrix_data(result, result.initial, show_findings=True)
    manager = next(row for row in roles.rows if row.key == "MANAGER")
    assert manager.cells[roles.column_keys.index("R5")].text == "Ч·РВ"
    assert roles.column_headers[0].startswith("R1 крит.")
    users = user_matrix_data(result, result.initial, show_findings=True)
    u12 = next(row for row in users.rows if row.key == "U12")
    cell = u12.cells[users.column_keys.index("R2")]
    assert cell.marker and cell.text == "ЧЗРВ" and "Надлишкові" in cell.tooltip
    assert [style for _char, style in cell.glyphs] == [
        GlyphStyle.GRANTED, GlyphStyle.GRANT, GlyphStyle.GRANT, GlyphStyle.GRANT,
    ]
    optimized = user_matrix_data(result, result.optimized, show_findings=False)
    assert not any(cell.marker for row in optimized.rows for cell in row.cells)


def test_record_model_editing(qapp: QCoreApplication) -> None:
    records = [["Початкова назва"]]
    failures: list[str] = []

    def rename(record: list[str], value: object) -> list[str]:
        if not str(value).strip():
            return ["Назва не може бути порожньою"]
        record[0] = str(value)
        return []

    model: RecordTableModel[list[str]] = RecordTableModel(
        [Column("Назва", lambda record: record[0], edit_value=lambda record: record[0], on_edit=rename)]
    )
    model.edit_failed.connect(failures.append)
    model.set_rows(records)
    index = model.index(0, 0)
    assert model.flags(index) & Qt.ItemFlag.ItemIsEditable
    assert model.setData(index, "Нова назва")
    assert records[0][0] == "Нова назва"
    assert not model.setData(index, " ")
    assert failures == ["Назва не може бути порожньою"]


def test_main_window_smoke(qapp: QCoreApplication, enterprise: Enterprise, tmp_path: Path) -> None:
    state = ModelState(enterprise)
    window = MainWindow(state)
    assert window.tabs.count() == 7
    assert window.minimumWidth() <= 1280 and window.minimumHeight() <= 800
    for index in range(window.tabs.count()):
        page = window.tabs.widget(index)
        assert isinstance(page, ResultTab)
        page.ensure_current()
    texts = " | ".join(label.text() for label in window.statusBar().findChildren(QLabel))
    assert "316 → 158" in texts and "39,5" in texts and "71,5" in texts

    scheme_tab = window.tabs.widget(1)
    assert isinstance(scheme_tab, SchemeTab) and isinstance(scheme_tab.scene, SchemeScene)
    export_png(scheme_tab.scene, tmp_path / "scheme.png")
    export_svg(scheme_tab.scene, tmp_path / "scheme.svg", "Схема")
    assert (tmp_path / "scheme.png").stat().st_size > 10_000
    assert "<svg" in (tmp_path / "scheme.svg").read_text(encoding="utf-8")

    risk_tab = window.tabs.widget(3)
    assert isinstance(risk_tab, RiskTab)
    proxy = risk_tab.findings_view.model()
    assert proxy.rowCount() == 158
    assert proxy.index(0, 6).data() == "Критичний"
    assert proxy.index(proxy.rowCount() - 1, 6).data() == "Низький"

    state.set_role_operations("GUEST", "R6", {R})
    texts = " | ".join(label.text() for label in window.statusBar().findChildren(QLabel))
    assert "312 → 158" in texts
    state.undo()
    window.deleteLater()


def test_changes_matrix_data(qapp: QCoreApplication, result: AnalysisResult) -> None:
    roles = role_changes_data(result)
    employee = next(row for row in roles.rows if row.key == "EMPLOYEE")
    cell = employee.cells[roles.column_keys.index("R1")]
    assert [style for _char, style in cell.glyphs] == [
        GlyphStyle.KEPT, GlyphStyle.KEPT, GlyphStyle.KEPT, GlyphStyle.REMOVED,
    ]
    assert cell.text == "ЧЗР·" and "Вилучено: В" in cell.tooltip
    users = user_changes_data(result)
    u12 = next(row for row in users.rows if row.key == "U12")
    finance = u12.cells[users.column_keys.index("R2")]
    assert all(style is GlyphStyle.REMOVED for _char, style in finance.glyphs)
    assert finance.text == "····"


def test_optimization_tab_rebuilds_model(qapp: QCoreApplication, enterprise: Enterprise) -> None:
    state = ModelState(enterprise)
    tab = OptimizationTab(state)
    tab.ensure_current()
    model = tab.functions_view.model()
    assert model.rowCount() == 14
    guest_row = next(row for row in range(model.rowCount()) if model.index(row, 0).data() == "Гість")
    index = model.index(guest_row, FUNCTION_RESOURCE_COLUMN)
    assert model.setData(index, "R4")
    assert state.optimized.role_operations("GUEST", "R6") == frozenset({R})  # еталон ще не перебудовано
    tab.ensure_current()
    assert tab.build_button.text().endswith("*")
    tab.build_model()
    tab.ensure_current()  # прихована вкладка оновлюється при показі
    assert not tab.build_button.text().endswith("*")
    assert state.optimized.role_operations("GUEST", "R4") == frozenset({R})
    assert state.optimized.role_operations("GUEST", "R6") == frozenset()
    state.undo()
    state.undo()
    assert state.optimized == build_min_privilege_model(enterprise)
    tab.deleteLater()


def test_comparison_tab(qapp: QCoreApplication, enterprise: Enterprise, result: AnalysisResult) -> None:
    lines = comparison_lines(result.comparison)
    sections = {row.section for row in result.comparison}
    assert len(lines) == len(result.comparison) + len(sections)
    tab = ComparisonTab(ModelState(enterprise))
    tab.ensure_current()
    model = tab.table_view.model()
    values = {
        model.index(row, 0).data().strip(): (model.index(row, 1).data(), model.index(row, 2).data())
        for row in range(model.rowCount())
    }
    assert values["Дозволені операції — матриця користувачів (з 480)"] == ("316", "158")
    assert values["Дозволені операції — матриця ролей (з 96)"] == ("67", "33")
    assert tab.charts.count() == 3
    tab.deleteLater()


def test_simulation_tab(qapp: QCoreApplication, enterprise: Enterprise) -> None:
    tab = SimulationTab(ModelState(enterprise))
    tab.ensure_current()
    tab.select_request("U20", "R2", R)
    initial, optimized = tab.cards
    assert initial.verdict_text == "ДОЗВОЛЕНО" and optimized.verdict_text == "ЗАБОРОНЕНО"
    tab.select_request("U03", "R1", D)
    assert initial.verdict_text == optimized.verdict_text == "ДОЗВОЛЕНО"
    tab.select_compromised("U12")
    before, after = tab.impact_panels
    assert "ризик: 105 із 130" in before.summary_text and "ризик: 33 із 130" in after.summary_text
    deletable_before = [row.resource_id for row in before.rows if "видалити" in row.abilities]
    deletable_after = [row.resource_id for row in after.rows if "видалити" in row.abilities]
    assert deletable_before == ["R1", "R2", "R3", "R4"] and deletable_after == []
    tab.deleteLater()


def test_save_all_figures_and_scheme_images(qapp: QCoreApplication, result: AnalysisResult, tmp_path: Path) -> None:
    saved = save_all_figures(result, tmp_path / "рисунки")
    names = sorted(path.name for path in saved)
    assert names == sorted(
        [f"{spec.file_stem}.png" for spec in CHARTS]
        + ["scheme_initial.png", "scheme_initial.svg", "scheme_optimized.png", "scheme_optimized.svg"]
    )
    assert all(path.stat().st_size > 5_000 for path in saved)
    images = scheme_images(result)
    assert set(images) == {"initial", "optimized"}
    assert all(data.startswith(b"\x89PNG") for data in images.values())


def test_toolbar_has_export_actions(qapp: QCoreApplication, enterprise: Enterprise) -> None:
    window = MainWindow(ModelState(enterprise))
    toolbar = window.findChild(QToolBar)
    texts = [action.text() for action in toolbar.actions()]
    for text in ("Відкрити модель…", "Зберегти модель", "Скинути до варіанту 7", "Експорт у Excel", "Звіт Word",
                 "Зберегти діаграми"):
        assert text in texts
    window.deleteLater()


def test_tab_shortcuts_and_compact_status(qapp: QCoreApplication, enterprise: Enterprise) -> None:
    window = MainWindow(ModelState(enterprise))
    titles = [window.tabs.tabText(index) for index in range(window.tabs.count())]
    assert "Висновки" not in titles
    assert [window.tabs.tabToolTip(index) for index in range(window.tabs.count())] == [
        f"Ctrl+{number}" for number in range(1, window.tabs.count() + 1)
    ]
    labels = [label.text() for label in window.statusBar().findChildren(QLabel) if label.text()]
    assert all(len(text) <= 40 for text in labels)
    window.deleteLater()
