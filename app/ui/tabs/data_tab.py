"""Вкладка «Вихідні дані»: користувачі, ресурси, ролі та операції з редагуванням."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QSplitter, QVBoxLayout, QWidget

from app.domain.models import (
    MAX_CRITICALITY,
    MIN_CRITICALITY,
    Operation,
    Resource,
    Role,
    User,
    operations_code,
)
from app.services.analysis import AnalysisResult
from app.ui.state import ModelState
from app.ui.table_models import CENTER, Column, RecordTableModel
from app.ui.tabs.base import ResultTab
from app.ui.widgets import ChoiceDelegate, SpinDelegate, fit_table_height, make_table, section

USER_ROLE_COLUMN = 3
RESOURCE_K_COLUMN = 3


class DataTab(ResultTab):
    """Таблиці вихідних даних; зміни перевіряються й одразу перераховують усі показники."""

    def __init__(self, state: ModelState, parent: QWidget | None = None) -> None:
        super().__init__(state, parent)
        self._users: RecordTableModel[User] = RecordTableModel(self._user_columns(), parent=self)
        self._resources: RecordTableModel[Resource] = RecordTableModel(self._resource_columns(), parent=self)
        self._roles: RecordTableModel[Role] = RecordTableModel(self._role_columns(), parent=self)
        self._operations: RecordTableModel[Operation] = RecordTableModel(self._operation_columns(), parent=self)
        for model in (self._users, self._resources, self._roles):
            model.edit_failed.connect(self._show_error)

        users_view = make_table(self._users, stretch_column=2)
        users_view.setItemDelegateForColumn(USER_ROLE_COLUMN, ChoiceDelegate(self._role_choices, users_view))
        self._resources_view = make_table(self._resources, stretch_column=2)
        self._resources_view.setItemDelegateForColumn(
            RESOURCE_K_COLUMN, SpinDelegate(MIN_CRITICALITY, MAX_CRITICALITY, self._resources_view)
        )
        self._roles_view = make_table(self._roles, stretch_column=2)
        self._operations_view = make_table(self._operations, stretch_column=3)

        self._users_box = section("Користувачі", users_view)
        self._resources_box = section("Інформаційні ресурси", self._resources_view)
        self._roles_box = section("Ролі", self._roles_view)
        operations_box = section("Типи операцій", self._operations_view)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self._resources_box)
        right_layout.addWidget(self._roles_box)
        right_layout.addWidget(operations_box)
        right_layout.addStretch(1)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._users_box)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 6)
        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)

    def refresh(self, result: AnalysisResult) -> None:
        enterprise = result.enterprise
        self._users.set_rows(enterprise.users)
        self._resources.set_rows(enterprise.resources)
        self._roles.set_rows(enterprise.roles)
        self._operations.set_rows(list(Operation))
        fit_table_height(self._resources_view, len(enterprise.resources))
        fit_table_height(self._roles_view, len(enterprise.roles))
        fit_table_height(self._operations_view, len(Operation))
        self._users_box.setTitle(f"Користувачі ({len(enterprise.users)})")
        self._resources_box.setTitle(f"Інформаційні ресурси ({len(enterprise.resources)})")
        self._roles_box.setTitle(f"Ролі ({len(enterprise.roles)})")

    def _user_columns(self) -> list[Column[User]]:
        return [
            Column("ID", lambda user: user.id, bold=True, width=50),
            Column(
                "ПІБ",
                lambda user: user.full_name,
                width=158,
                edit_value=lambda user: user.full_name,
                on_edit=lambda user, value: self._update_user(replace(user, full_name=str(value).strip())),
            ),
            Column(
                "Посада",
                lambda user: user.position,
                tooltip=lambda user: user.position,
                edit_value=lambda user: user.position,
                on_edit=lambda user, value: self._update_user(replace(user, position=str(value).strip())),
            ),
            Column(
                "Роль",
                lambda user: self._role_name(user.role_id),
                width=112,
                edit_value=lambda user: user.role_id,
                on_edit=lambda user, value: self._update_user(replace(user, role_id=str(value))),
            ),
            Column(
                "Поза роллю",
                self._grants_text,
                tooltip=self._grants_tooltip,
                width=112,
                header_tooltip="Індивідуальні дозволи поза роллю (ресурс: операції)",
            ),
        ]

    def _resource_columns(self) -> list[Column[Resource]]:
        return [
            Column("ID", lambda resource: resource.id, bold=True, width=40),
            Column(
                "Назва",
                lambda resource: resource.name,
                width=196,
                edit_value=lambda resource: resource.name,
                on_edit=lambda resource, value: self._update_resource(replace(resource, name=str(value).strip())),
            ),
            Column(
                "Зміст",
                lambda resource: resource.description,
                tooltip=lambda resource: resource.description,
                edit_value=lambda resource: resource.description,
                on_edit=lambda resource, value: self._update_resource(
                    replace(resource, description=str(value).strip())
                ),
            ),
            Column(
                "K",
                lambda resource: str(resource.criticality),
                align=CENTER,
                width=36,
                edit_value=lambda resource: resource.criticality,
                on_edit=lambda resource, value: self._update_resource(replace(resource, criticality=int(value))),
                header_tooltip="Коефіцієнт критичності (1–3)",
            ),
            Column(
                "Критичний",
                lambda resource: "так" if resource.critical else "ні",
                width=92,
                checked=lambda resource: resource.critical,
                on_edit=lambda resource, value: self._update_resource(replace(resource, critical=bool(value))),
            ),
        ]

    def _role_columns(self) -> list[Column[Role]]:
        return [
            Column("ID", lambda role: role.id, bold=True, width=84),
            Column(
                "Назва",
                lambda role: role.name,
                width=112,
                edit_value=lambda role: role.name,
                on_edit=lambda role, value: self._update_role(replace(role, name=str(value).strip())),
            ),
            Column(
                "Опис",
                lambda role: role.description,
                tooltip=lambda role: role.description,
                edit_value=lambda role: role.description,
                on_edit=lambda role, value: self._update_role(replace(role, description=str(value).strip())),
            ),
            Column(
                "Корист.",
                lambda role: str(len(self.result.enterprise.users_of_role(role.id))),
                align=CENTER,
                width=62,
                header_tooltip="Кількість користувачів із роллю",
            ),
            Column(
                "Функцій",
                lambda role: str(len(role.functions)),
                align=CENTER,
                width=68,
                header_tooltip="Кількість службових функцій ролі (основа оптимізації)",
            ),
            Column(
                "Операцій",
                lambda role: str(self.result.initial.allowed_by_role.get(role.id, 0)),
                align=CENTER,
                width=76,
                header_tooltip="Дозволено операцій у початковій матриці ролей",
            ),
        ]

    @staticmethod
    def _operation_columns() -> list[Column[Operation]]:
        return [
            Column("Код", lambda operation: operation.short, bold=True, align=CENTER, width=48),
            Column("Назва", lambda operation: operation.label, width=120),
            Column("Вага", lambda operation: str(operation.weight), align=CENTER, width=56),
            Column("Опис", lambda operation: operation.description, tooltip=lambda operation: operation.description),
        ]

    def _role_name(self, role_id: str) -> str:
        enterprise = self.result.enterprise
        return enterprise.role(role_id).name if role_id in enterprise.role_ids else role_id

    def _role_choices(self) -> list[tuple[str, str]]:
        return [(role.name, role.id) for role in self.state.enterprise.roles]

    def _grants_text(self, user: User) -> str:
        model = self.result.enterprise.initial_model
        parts = [
            f"{resource.id}: {operations_code(grant.operations)}"
            for resource in self.result.enterprise.resources
            if (grant := model.grant(user.id, resource.id)) is not None
        ]
        return "; ".join(parts) or "—"

    def _grants_tooltip(self, user: User) -> str:
        model = self.result.enterprise.initial_model
        lines = [
            f"{resource.id} «{resource.name}»: {operations_code(grant.operations)} — {grant.reason}"
            for resource in self.result.enterprise.resources
            if (grant := model.grant(user.id, resource.id)) is not None
        ]
        return "\n".join(lines) or "Індивідуальних дозволів немає"

    def _update_user(self, user: User) -> list[str]:
        enterprise = self.state.enterprise
        if enterprise.user(user.id) == user:
            return []
        return self.state.apply(enterprise.with_user(user))

    def _update_resource(self, resource: Resource) -> list[str]:
        enterprise = self.state.enterprise
        if enterprise.resource(resource.id) == resource:
            return []
        return self.state.apply(enterprise.with_resource(resource))

    def _update_role(self, role: Role) -> list[str]:
        enterprise = self.state.enterprise
        if enterprise.role(role.id) == role:
            return []
        return self.state.apply(enterprise.with_role(role))

    def _show_error(self, message: str) -> None:
        QMessageBox.warning(self, "Некоректні дані", message)
