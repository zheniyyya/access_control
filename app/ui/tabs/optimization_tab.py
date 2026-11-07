"""Вкладка «Оптимізація»: службові функції ролей, модель мінімальних привілеїв і матриця змін.

Службові функції можна редагувати (назва, ресурс, операції), додавати й видаляти.
Кнопка «Побудувати модель мінімальних привілеїв» перебудовує еталон: права
ролі на ресурсі = об'єднання операцій її службових функцій, індивідуальних
дозволів немає. Усі показники застосунку після цього перераховуються.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import palette
from app.domain.models import NO_OPERATIONS, DutyFunction, Operation, Role, operations_code
from app.services.analysis import AnalysisResult
from app.services.matrix import CellDiff, cell_level
from app.services.optimizer import CellJustification, build_min_privilege_model, function_count
from app.ui.dialogs import OperationsDialog
from app.ui.matrix_data import (
    role_changes_data,
    role_matrix_data,
    user_changes_data,
    user_matrix_data,
)
from app.ui.state import ModelState
from app.ui.table_models import CENTER, Column, MatrixTableModel, RecordTableModel, diff_cell
from app.ui.tabs.base import ResultTab
from app.ui.widgets import (
    ChoiceDelegate,
    LegendBar,
    fit_matrix_columns,
    fit_table_height,
    make_matrix_view,
    make_table,
    section,
    show_status,
)

FUNCTION_RESOURCE_COLUMN = 2
FUNCTION_OPERATIONS_COLUMN = 3
NEW_FUNCTION_NAME = "Нова службова функція"
BUILD_TEXT = "Побудувати модель мінімальних привілеїв"
_R, _W, _E, _D = Operation.READ, Operation.WRITE, Operation.EDIT, Operation.DELETE


@dataclass(frozen=True)
class _FunctionRow:
    """Рядок таблиці службових функцій: роль, номер функції в ролі та сама функція."""

    role: Role
    index: int
    function: DutyFunction


class OptimizationTab(ResultTab):
    """Побудова моделі мінімальних привілеїв зі службових функцій ролей."""

    def __init__(self, state: ModelState, parent: QWidget | None = None) -> None:
        super().__init__(state, parent)
        self._functions: RecordTableModel[_FunctionRow] = RecordTableModel(self._function_columns(), parent=self)
        self._functions.edit_failed.connect(self._show_error)
        self._justification: RecordTableModel[CellJustification] = RecordTableModel(
            self._justification_columns(), parent=self
        )
        self._roles = MatrixTableModel(self)
        self._users = MatrixTableModel(self)
        self._role_changes = MatrixTableModel(self)
        self._user_changes = MatrixTableModel(self)

        self._functions_view = make_table(self._functions, stretch_column=1)
        self._functions_view.setItemDelegateForColumn(
            FUNCTION_RESOURCE_COLUMN, ChoiceDelegate(self._resource_choices, self._functions_view)
        )
        self._functions_view.clicked.connect(self._edit_operations)
        add_button = QPushButton("Додати функцію")
        add_button.setToolTip("Додати службову функцію до ролі виділеного рядка")
        add_button.clicked.connect(self._add_function)
        remove_button = QPushButton("Видалити функцію")
        remove_button.clicked.connect(self._remove_function)
        principles_button = QPushButton("Принципи…")
        principles_button.setToolTip("Принципи, закладені в модель мінімальних привілеїв (обґрунтування)")
        principles_button.clicked.connect(self.show_principles)
        self._build_button = QPushButton(BUILD_TEXT)
        self._build_button.setToolTip(
            "Права ролі на ресурсі = об'єднання операцій її службових функцій; "
            "індивідуальні дозволи скасовуються"
        )
        self._build_button.setDefault(True)
        font = self._build_button.font()
        font.setBold(True)
        self._build_button.setFont(font)
        self._build_button.clicked.connect(self.build_model)
        buttons = QHBoxLayout()
        buttons.addWidget(add_button)
        buttons.addWidget(remove_button)
        buttons.addStretch(1)
        buttons.addWidget(principles_button)
        self._model_status = QLabel()
        self._model_status.setWordWrap(True)
        self._model_status.setMargin(6)
        functions_layout = QVBoxLayout()
        functions_layout.addWidget(self._functions_view, 1)
        functions_layout.addLayout(buttons)
        functions_layout.addWidget(self._build_button)
        functions_layout.addWidget(self._model_status)
        self._functions_box = section("Службові функції ролей", functions_layout)

        self._role_view = make_matrix_view(self._roles)
        self._user_view = make_matrix_view(self._users)
        self._role_changes_view = make_matrix_view(self._role_changes)
        self._user_changes_view = make_matrix_view(self._user_changes)
        self._role_box = section("Ролі", self._role_view)
        self._user_box = section("Користувачі", self._user_view)
        optimized_page = QWidget()
        optimized_layout = QVBoxLayout(optimized_page)
        optimized_layout.addWidget(self._role_box)
        optimized_layout.addWidget(self._user_box, 1)

        legend = LegendBar(
            [
                (diff_cell(CellDiff(frozenset({_R, _W}), NO_OPERATIONS, NO_OPERATIONS)), "збережено"),
                (diff_cell(CellDiff(frozenset({_R}), frozenset({_W, _E, _D}), NO_OPERATIONS)), "вилучено"),
                (diff_cell(CellDiff(NO_OPERATIONS, NO_OPERATIONS, NO_OPERATIONS)), "без доступу"),
            ]
        )
        self._role_changes_box = section("Ролі", self._role_changes_view)
        self._user_changes_box = section("Користувачі", self._user_changes_view)
        changes_page = QWidget()
        changes_layout = QVBoxLayout(changes_page)
        changes_layout.addWidget(legend)
        changes_layout.addWidget(self._role_changes_box)
        changes_layout.addWidget(self._user_changes_box, 1)

        self._justification_view = make_table(self._justification, stretch_column=6)
        justification_page = QWidget()
        justification_layout = QVBoxLayout(justification_page)
        justification_layout.addWidget(self._justification_view)

        self._details = QTabWidget()
        self._details.addTab(optimized_page, "Оптимізована матриця")
        self._details.addTab(changes_page, "Матриця змін")
        self._details.addTab(justification_page, "Обґрунтування")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._functions_box)
        splitter.addWidget(self._details)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 7)
        splitter.setSizes([500, 820])
        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)

    @property
    def functions_view(self) -> QTableView:
        """Таблиця службових функцій."""
        return self._functions_view

    @property
    def build_button(self) -> QPushButton:
        """Кнопка «Побудувати модель мінімальних привілеїв» (« *» — еталон застарів)."""
        return self._build_button

    @property
    def details(self) -> QTabWidget:
        """Вкладки з оптимізованою матрицею, матрицею змін та обґрунтуванням."""
        return self._details

    def refresh(self, result: AnalysisResult) -> None:
        enterprise = result.enterprise
        self._functions.set_rows(
            [
                _FunctionRow(role, index, function)
                for role in enterprise.roles
                for index, function in enumerate(role.functions)
            ]
        )
        self._functions_box.setTitle(f"Службові функції ролей ({function_count(enterprise)})")
        self._update_model_status(result)

        optimized = result.optimized
        self._roles.set_matrix(role_matrix_data(result, optimized, show_findings=False))
        self._users.set_matrix(user_matrix_data(result, optimized, show_findings=False))
        self._role_changes.set_matrix(role_changes_data(result))
        self._user_changes.set_matrix(user_changes_data(result))
        for view, model in ((self._role_view, self._roles), (self._role_changes_view, self._role_changes)):
            fit_matrix_columns(view, model)
            fit_table_height(view, len(enterprise.roles))
        for view, model in ((self._user_view, self._users), (self._user_changes_view, self._user_changes)):
            fit_matrix_columns(view, model, info_width=96)
        self._role_box.setTitle(
            f"Ролі · дозволено {optimized.role_stats.allowed} із {optimized.role_stats.total} "
            f"(було {result.initial.role_stats.allowed})"
        )
        self._user_box.setTitle(
            f"Користувачі · дозволено {optimized.user_stats.allowed} із {optimized.user_stats.total} "
            f"(було {result.initial.user_stats.allowed})"
        )
        removed_roles = sum(len(diff.removed) for row in result.role_changes.values() for diff in row.values())
        removed_users = sum(len(diff.removed) for row in result.user_changes.values() for diff in row.values())
        self._role_changes_box.setTitle(f"Ролі · вилучено {removed_roles}")
        self._user_changes_box.setTitle(f"Користувачі · вилучено {removed_users}")
        self._justification.set_rows(result.justification)

    def _update_model_status(self, result: AnalysisResult) -> None:
        """Чи відповідає поточний еталон службовим функціям і чи він коректний."""
        up_to_date = build_min_privilege_model(result.enterprise) == result.optimized.model
        problems: list[str] = []
        details: list[str] = []  # подробиці — у спливній підказці
        if not up_to_date:
            problems.append("Функції змінено — побудуйте модель заново")
        if result.uncovered:
            problems.append("Не всі функції забезпечено правами")
            details += [f"{role.name}: «{function.name}»" for role, function in result.uncovered]
        if not result.is_subset:
            problems.append("Модель надає нові права")
            details.append("Оптимізована модель надає права, яких немає в початковій")
        warning = bool(problems)
        if warning:
            text = " · ".join(problems)
        else:
            text = f"Модель актуальна · порушень П1–П8: {len(result.optimized.violations)}"
        fill = palette.tint(palette.STATUS_WARNING, 0.30) if warning else palette.tint(palette.STATUS_GOOD, 0.20)
        stroke = palette.STATUS_WARNING if warning else palette.STATUS_GOOD
        self._model_status.setText(text)
        self._model_status.setToolTip("\n".join(details))
        self._model_status.setStyleSheet(
            f"background: {fill}; border-left: 4px solid {stroke}; border-radius: 3px;"
        )
        self._build_button.setText(BUILD_TEXT + ("" if up_to_date else " *"))

    def _function_columns(self) -> list[Column[_FunctionRow]]:
        return [
            Column("Роль", lambda row: row.role.name, width=112, bold=True),
            Column(
                "Службова функція",
                lambda row: row.function.name,
                tooltip=lambda row: row.function.name,
                edit_value=lambda row: row.function.name,
                on_edit=lambda row, value: self._update_function(row, replace(row.function, name=str(value).strip())),
            ),
            Column(
                "Ресурс",
                lambda row: row.function.resource_id,
                tooltip=lambda row: self._resource_name(row.function.resource_id),
                align=CENTER,
                width=64,
                edit_value=lambda row: row.function.resource_id,
                on_edit=lambda row, value: self._update_function(row, replace(row.function, resource_id=str(value))),
            ),
            Column(
                "Операції",
                lambda row: operations_code(row.function.operations),
                tooltip=lambda _row: "Клацніть, щоб змінити операції",
                fill=lambda row: palette.CELL_FILL[cell_level(row.function.operations)],
                align=CENTER,
                width=76,
            ),
        ]

    def _justification_columns(self) -> list[Column[CellJustification]]:
        def changed_fill(row: CellJustification) -> str | None:
            return palette.CHANGED_FILL if row.removed or row.added else None

        return [
            Column("Роль", lambda row: self.result.enterprise.role(row.role_id).name, width=104),
            Column("Ресурс", lambda row: row.resource_id, tooltip=lambda row: self._resource_name(row.resource_id),
                   align=CENTER, width=58),
            Column("Було", lambda row: operations_code(row.initial), align=CENTER, width=56),
            Column("Стало", lambda row: operations_code(row.optimized), align=CENTER, width=56),
            Column("Вилучено", lambda row: operations_code(row.removed), fill=changed_fill, align=CENTER, width=72),
            Column("Правила", lambda row: ", ".join(row.rule_codes) or "—", width=96),
            Column("Обґрунтування", lambda row: row.text, tooltip=lambda row: row.text),
        ]

    def _resource_name(self, resource_id: str) -> str:
        enterprise = self.result.enterprise
        if resource_id not in enterprise.resource_ids:
            return resource_id
        resource = enterprise.resource(resource_id)
        return f"{resource.id} «{resource.name}»"

    def _resource_choices(self) -> list[tuple[str, str]]:
        return [(f"{resource.id} — {resource.name}", resource.id) for resource in self.state.enterprise.resources]

    def _apply_role(self, role: Role) -> list[str]:
        enterprise = self.state.enterprise
        if enterprise.role(role.id) == role:
            return []
        return self.state.apply(enterprise.with_role(role))

    def _update_function(self, row: _FunctionRow, function: DutyFunction) -> list[str]:
        role = self.state.enterprise.role(row.role.id)
        functions = list(role.functions)
        functions[row.index] = function
        return self._apply_role(replace(role, functions=tuple(functions)))

    def _selected_row(self) -> _FunctionRow | None:
        index = self._functions_view.currentIndex()
        if not index.isValid() or index.row() >= self._functions.rowCount():
            return None
        return self._functions.record(index.row())

    def _edit_operations(self, index: QModelIndex) -> None:
        if index.column() != FUNCTION_OPERATIONS_COLUMN:
            return
        row = self._functions.record(index.row())
        resource = self._resource_name(row.function.resource_id)
        dialog = OperationsDialog(
            f"Роль «{row.role.name}»: «{row.function.name}»",
            f"Операції над ресурсом {resource}, потрібні для виконання службової функції.",
            row.function.operations,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_operations()
        if selected != row.function.operations:
            self._report(self._update_function(row, replace(row.function, operations=selected)))

    def _add_function(self) -> None:
        enterprise = self.state.enterprise
        if not enterprise.roles or not enterprise.resources:
            return
        selected = self._selected_row()
        role = enterprise.role(selected.role.id) if selected is not None else enterprise.roles[0]
        function = DutyFunction(NEW_FUNCTION_NAME, enterprise.resources[0].id, frozenset({Operation.READ}))
        errors = self._apply_role(replace(role, functions=(*role.functions, function)))
        if errors:
            self._report(errors)
            return
        rows = self._functions.records
        position = next(
            (
                number
                for number, row in enumerate(rows)
                if row.role.id == role.id and row.index == len(role.functions)
            ),
            None,
        )
        if position is not None:
            self._functions_view.setCurrentIndex(self._functions.index(position, 1))
            self._functions_view.edit(self._functions.index(position, 1))
        show_status(self, f"Додано службову функцію ролі «{role.name}» — задайте назву, ресурс і операції")

    def _remove_function(self) -> None:
        selected = self._selected_row()
        if selected is None:
            QMessageBox.information(self, "Видалення функції", "Виділіть службову функцію в таблиці.")
            return
        answer = QMessageBox.question(
            self,
            "Видалення функції",
            f"Видалити службову функцію «{selected.function.name}» ролі «{selected.role.name}»?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        role = self.state.enterprise.role(selected.role.id)
        functions = tuple(function for number, function in enumerate(role.functions) if number != selected.index)
        self._report(self._apply_role(replace(role, functions=functions)))

    def build_model(self) -> None:
        """Перебудовує модель мінімальних привілеїв за поточними службовими функціями."""
        enterprise = self.state.enterprise
        optimized = build_min_privilege_model(enterprise)
        if optimized == self.state.optimized:
            show_status(self, "Модель мінімальних привілеїв уже відповідає службовим функціям")
            return
        errors = self.state.apply(enterprise, optimized)
        if errors:
            self._report(errors)
            return
        stats = self.result.optimized.role_stats
        show_status(
            self, f"Побудовано модель мінімальних привілеїв: {stats.allowed} операцій у матриці ролей"
        )

    def show_principles(self) -> None:
        """Вікно з принципами, закладеними в модель мінімальних привілеїв."""
        principles = self.result.enterprise.principles
        text = "\n\n".join(f"{number}. {item}" for number, item in enumerate(principles, start=1))
        QMessageBox.information(self, "Принципи моделі", text or "Принципи у файлі моделі не задано.")

    def _report(self, errors: list[str]) -> None:
        if errors:
            self._show_error("\n".join(errors))

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "Зміну не застосовано", message)
