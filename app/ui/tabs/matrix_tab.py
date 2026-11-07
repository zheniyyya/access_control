"""Вкладка «Початкова матриця»: матриці ролей і користувачів, легенда, режим «що буде, якщо».

Клацання по клітинці відкриває діалог із чотирма прапорцями; після змін
усі показники застосунку перераховуються миттєво (скасування — Ctrl+Z).
"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtWidgets import QDialog, QMessageBox, QSplitter, QVBoxLayout, QWidget

from app import palette
from app.domain.models import (
    ALL_OPERATIONS,
    NO_OPERATIONS,
    Operation,
    OperationSet,
    Resource,
    Role,
    operations_code,
)
from app.services.analysis import AnalysisResult
from app.services.analyzer import ALL_RULES, GrantSummary, RightContext, matching_rules, strongest_rule
from app.services.comparison import ModelMetrics
from app.services.matrix import GrantSource
from app.ui.dialogs import OperationsDialog
from app.ui.matrix_data import role_matrix_data, user_matrix_data
from app.ui.state import ModelState
from app.ui.table_models import CENTER, Column, MatrixTableModel, RecordTableModel, access_cell
from app.ui.tabs.base import ResultTab
from app.ui.widgets import (
    LegendBar,
    fit_matrix_columns,
    fit_table_height,
    make_matrix_view,
    make_table,
    section,
)

DEFAULT_GRANT_REASON = "Режим «що буде, якщо»"
_R, _W, _E = Operation.READ, Operation.WRITE, Operation.EDIT


def _stats_text(metrics: ModelMetrics, users: bool) -> str:
    """«дозволено 67 із 96» для заголовка рамки."""
    stats = metrics.user_stats if users else metrics.role_stats
    return f"дозволено {stats.allowed} із {stats.total}"


class MatrixTab(ResultTab):
    """Початкова матриця доступу ролей (4×6) і користувачів (20×6) з редагуванням."""

    def __init__(self, state: ModelState, parent: QWidget | None = None) -> None:
        super().__init__(state, parent)
        self._roles = MatrixTableModel(self)
        self._users = MatrixTableModel(self)
        self._grants: RecordTableModel[GrantSummary] = RecordTableModel(self._grant_columns(), parent=self)
        self._role_view = make_matrix_view(self._roles)
        self._user_view = make_matrix_view(self._users)
        self._role_view.clicked.connect(self._edit_role_cell)
        self._user_view.clicked.connect(self._edit_user_cell)

        self._role_box = section("Матриця ролей", self._role_view)
        self._grants_box = section("Індивідуальні дозволи поза роллю", make_table(self._grants, stretch_column=4))
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self._role_box)
        left_layout.addWidget(self._grants_box, 1)
        self._user_box = section("Матриця користувачів", self._user_view)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(self._user_box)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 6)
        splitter.setSizes([560, 700])  # матриця користувачів — без горизонтальної прокрутки

        legend = LegendBar(
            [
                (access_cell(NO_OPERATIONS), "немає доступу"),
                (access_cell(frozenset({_R})), "лише читання"),
                (access_cell(frozenset({_R, _W, _E})), "запис / редагування"),
                (access_cell(ALL_OPERATIONS), "є видалення"),
                (access_cell(frozenset({_R, _W}), frozenset({_W})), "індивідуальний дозвіл"),
            ]
        )
        layout = QVBoxLayout(self)
        layout.addWidget(legend)
        layout.addWidget(splitter, 1)

    def refresh(self, result: AnalysisResult) -> None:
        self._roles.set_matrix(role_matrix_data(result, result.initial, show_findings=True))
        self._users.set_matrix(user_matrix_data(result, result.initial, show_findings=True))
        fit_matrix_columns(self._role_view, self._roles)
        fit_matrix_columns(self._user_view, self._users, info_width=96)
        fit_table_height(self._role_view, len(result.enterprise.roles))
        self._grants.set_rows(result.grants)
        self._role_box.setTitle(f"Матриця ролей · {_stats_text(result.initial, users=False)}")
        self._user_box.setTitle(f"Матриця користувачів · {_stats_text(result.initial, users=True)}")
        self._grants_box.setTitle(f"Індивідуальні дозволи поза роллю ({len(result.grants)})")

    def _grant_columns(self) -> list[Column[GrantSummary]]:
        def user_label(summary: GrantSummary) -> str:
            user = self.result.enterprise.user(summary.user_id)
            return f"{user.id} {user.full_name}"

        return [
            Column("Користувач", user_label, width=160),
            Column("Ресурс", lambda summary: summary.resource_id, align=CENTER, width=60),
            Column("Операції", lambda summary: operations_code(summary.operations), align=CENTER, width=76),
            Column(
                "Рівень",
                lambda summary: summary.severity.label if summary.severity else "—",
                fill=lambda summary: palette.SEVERITY_FILL[summary.severity] if summary.severity else None,
                width=84,
            ),
            Column("Причина надання", lambda summary: summary.reason, tooltip=lambda summary: summary.reason),
        ]

    def _role_hints(self, role: Role, resource: Resource, required: OperationSet) -> dict[Operation, str]:
        hints: dict[Operation, str] = {}
        for operation in Operation:
            if operation in required:
                hints[operation] = "потрібна для службових функцій ролі"
                continue
            context = RightContext(role, resource, operation, GrantSource.ROLE, self.result.enterprise.bindings)
            rules = matching_rules(context, ALL_RULES)
            severity = strongest_rule(rules).severity.label.lower()
            hints[operation] = f"зайва для ролі: {severity} ({', '.join(rule.code for rule in rules)})"
        return hints

    def _user_hints(self, role: Role, resource: Resource, required: OperationSet) -> dict[Operation, str]:
        hints: dict[Operation, str] = {}
        for operation in Operation:
            if operation in required:
                hints[operation] = "потрібна для службових функцій"
                continue
            context = RightContext(
                role, resource, operation, GrantSource.INDIVIDUAL, self.result.enterprise.bindings
            )
            rules = matching_rules(context, ALL_RULES)
            severity = strongest_rule(rules).severity.label.lower()
            hints[operation] = f"як індивідуальний дозвіл: {severity} ({', '.join(rule.code for rule in rules)})"
        return hints

    def _edit_role_cell(self, index: QModelIndex) -> None:
        key = self._roles.cell_key(index)
        if key is None:
            return
        role_id, resource_id = key
        enterprise = self.result.enterprise
        role, resource = enterprise.role(role_id), enterprise.resource(resource_id)
        current = self.result.initial.role_matrix[role_id][resource_id]
        required = self.result.optimized.role_matrix[role_id][resource_id]
        members = len(enterprise.users_of_role(role_id))
        dialog = OperationsDialog(
            f"Роль «{role.name}» → {resource.id} «{resource.name}»",
            f"Кількість користувачів із цією роллю — {members}; зміна вплине на всіх. "
            f"Еталон (службові функції): «{operations_code(required)}».",
            current,
            hints=self._role_hints(role, resource, required),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_operations()
        if selected != current:
            self._report(self.state.set_role_operations(role_id, resource_id, selected))

    def _edit_user_cell(self, index: QModelIndex) -> None:
        key = self._users.cell_key(index)
        if key is None:
            return
        user_id, resource_id = key
        enterprise = self.result.enterprise
        user, resource = enterprise.user(user_id), enterprise.resource(resource_id)
        role = enterprise.role(user.role_id)
        model = enterprise.initial_model
        role_operations = model.role_operations(role.id, resource_id)
        grant = model.grant(user_id, resource_id)
        current = self.result.initial.user_matrix[user_id][resource_id]
        required = self.result.optimized.user_matrix[user_id][resource_id]
        members = len(enterprise.users_of_role(role.id))
        dialog = OperationsDialog(
            f"{user.id} {user.full_name} ({role.name}) → {resource.id} «{resource.name}»",
            "Ефективні права = права ролі ∪ індивідуальний дозвіл. Операції ролі тут не "
            f"знімаються — їх змінюють у матриці ролей (користувачів із роллю «{role.name}» — {members}).",
            current,
            locked=role_operations,
            locked_hint=f"надано роллю «{role.name}»",
            hints=self._user_hints(role, resource, required),
            reason=grant.reason if grant is not None else DEFAULT_GRANT_REASON,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        selected = dialog.selected_operations()
        if selected != current:
            self._report(
                self.state.set_user_rights(
                    user_id, resource_id, selected, dialog.reason() or DEFAULT_GRANT_REASON
                )
            )

    def _report(self, errors: list[str]) -> None:
        if errors:
            QMessageBox.warning(self, "Зміну не застосовано", "\n".join(errors))
