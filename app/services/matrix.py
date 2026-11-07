"""Матриці доступу: права ролей, ефективні права користувачів і підрахунки.

Ефективні права користувача = права його ролі ∪ індивідуальні дозволи.
Кількість дозволених операцій — кількість трійок (суб'єкт, ресурс, операція),
що дозволені; заборонених — загальна кількість мінус дозволені.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from enum import Enum

from app.domain.models import (
    NO_OPERATIONS,
    AccessModel,
    Enterprise,
    Operation,
    OperationSet,
)

# Матриця доступу: суб'єкт (роль або користувач) → ресурс → операції.
Permissions = dict[str, dict[str, OperationSet]]


class CellLevel(Enum):
    """Рівень небезпеки клітинки — за найнебезпечнішою операцією в ній."""

    NONE = "Немає доступу"
    READ = "Лише читання"
    MODIFY = "Запис / редагування"
    DELETE = "Видалення"


class GrantSource(Enum):
    """Звідки користувач отримав операцію."""

    ROLE = "Роль"
    INDIVIDUAL = "Індивідуальний дозвіл"
    ROLE_AND_INDIVIDUAL = "Роль та індивідуальний дозвіл"


@dataclass(frozen=True)
class MatrixStats:
    """Кількість дозволених і заборонених операцій у матриці."""

    total: int
    allowed: int

    @property
    def denied(self) -> int:
        """Кількість заборонених операцій."""
        return self.total - self.allowed


@dataclass(frozen=True)
class CellDiff:
    """Зміна однієї клітинки між двома матрицями."""

    kept: OperationSet
    removed: OperationSet
    added: OperationSet

    @property
    def changed(self) -> bool:
        """Чи змінилася клітинка."""
        return bool(self.removed or self.added)


def cell_level(operations: Iterable[Operation]) -> CellLevel:
    """Колірний рівень клітинки: немає — сірий, лише Ч — зелений, З/Р — жовтий, В — червоний."""
    present = set(operations)
    if Operation.DELETE in present:
        return CellLevel.DELETE
    if Operation.WRITE in present or Operation.EDIT in present:
        return CellLevel.MODIFY
    if Operation.READ in present:
        return CellLevel.READ
    return CellLevel.NONE


def source_of(in_role: bool, in_grant: bool) -> GrantSource | None:
    """Джерело операції за ознаками «є в ролі» та «є в індивідуальному дозволі»."""
    if in_role and in_grant:
        return GrantSource.ROLE_AND_INDIVIDUAL
    if in_role:
        return GrantSource.ROLE
    if in_grant:
        return GrantSource.INDIVIDUAL
    return None


def role_matrix(enterprise: Enterprise, model: AccessModel) -> Permissions:
    """Матриця ролей (ролі × ресурси) з усіма клітинками, зокрема порожніми."""
    return {
        role.id: {
            resource.id: model.role_operations(role.id, resource.id)
            for resource in enterprise.resources
        }
        for role in enterprise.roles
    }


def effective_rights(
    enterprise: Enterprise, model: AccessModel, user_id: str
) -> dict[str, OperationSet]:
    """Ефективні права користувача на кожен ресурс: права ролі ∪ індивідуальні дозволи."""
    role_id = enterprise.user(user_id).role_id
    return {
        resource.id: model.role_operations(role_id, resource.id)
        | model.grant_operations(user_id, resource.id)
        for resource in enterprise.resources
    }


def user_matrix(enterprise: Enterprise, model: AccessModel) -> Permissions:
    """Матриця користувачів (користувачі × ресурси) з ефективними правами."""
    return {user.id: effective_rights(enterprise, model, user.id) for user in enterprise.users}


def operation_source(
    enterprise: Enterprise,
    model: AccessModel,
    user_id: str,
    resource_id: str,
    operation: Operation,
) -> GrantSource | None:
    """Джерело операції користувача (None — операцію не дозволено)."""
    role_id = enterprise.user(user_id).role_id
    return source_of(
        operation in model.role_operations(role_id, resource_id),
        operation in model.grant_operations(user_id, resource_id),
    )


def iter_rights(matrix: Mapping[str, Mapping[str, OperationSet]]) -> Iterator[tuple[str, str, Operation]]:
    """Перебирає всі дозволені трійки (суб'єкт, ресурс, операція)."""
    for subject_id, row in matrix.items():
        for resource_id, operations in row.items():
            for operation in Operation:
                if operation in operations:
                    yield subject_id, resource_id, operation


def matrix_stats(matrix: Mapping[str, Mapping[str, OperationSet]]) -> MatrixStats:
    """Загальна кількість, дозволені та заборонені операції матриці."""
    total = sum(len(row) for row in matrix.values()) * len(Operation)
    allowed = sum(len(operations) for row in matrix.values() for operations in row.values())
    return MatrixStats(total=total, allowed=allowed)


def allowed_by_subject(matrix: Mapping[str, Mapping[str, OperationSet]]) -> dict[str, int]:
    """Кількість дозволених операцій кожного суб'єкта (рядка матриці)."""
    return {
        subject_id: sum(len(operations) for operations in row.values())
        for subject_id, row in matrix.items()
    }


def allowed_by_operation(matrix: Mapping[str, Mapping[str, OperationSet]]) -> dict[Operation, int]:
    """Кількість дозволених операцій кожного типу."""
    counts = {operation: 0 for operation in Operation}
    for _subject_id, _resource_id, operation in iter_rights(matrix):
        counts[operation] += 1
    return counts


def allowed_by_resource(matrix: Mapping[str, Mapping[str, OperationSet]]) -> dict[str, int]:
    """Кількість дозволених операцій на кожному ресурсі (стовпці матриці)."""
    counts: dict[str, int] = {}
    for row in matrix.values():
        for resource_id, operations in row.items():
            counts[resource_id] = counts.get(resource_id, 0) + len(operations)
    return counts


def allowed_by_role_users(enterprise: Enterprise, users: Mapping[str, Mapping[str, OperationSet]]) -> dict[str, int]:
    """Кількість дозволених операцій усіх користувачів кожної ролі."""
    per_user = allowed_by_subject(users)
    return {
        role.id: sum(per_user.get(user.id, 0) for user in enterprise.users_of_role(role.id))
        for role in enterprise.roles
    }


def subjects_with_access(
    matrix: Mapping[str, Mapping[str, OperationSet]],
    resource_id: str,
    operations: Iterable[Operation] | None = None,
) -> list[str]:
    """Суб'єкти, що мають на ресурсі будь-яку операцію (або хоча б одну з operations)."""
    wanted = frozenset(operations) if operations is not None else None
    result: list[str] = []
    for subject_id, row in matrix.items():
        granted = row.get(resource_id, NO_OPERATIONS)
        relevant = granted if wanted is None else granted & wanted
        if relevant:
            result.append(subject_id)
    return result


def diff_matrices(
    before: Mapping[str, Mapping[str, OperationSet]],
    after: Mapping[str, Mapping[str, OperationSet]],
) -> dict[str, dict[str, CellDiff]]:
    """Матриця змін: збережені, вилучені та додані операції кожної клітинки."""
    result: dict[str, dict[str, CellDiff]] = {}
    subject_ids = list(before) + [subject_id for subject_id in after if subject_id not in before]
    for subject_id in subject_ids:
        old_row = before.get(subject_id, {})
        new_row = after.get(subject_id, {})
        resource_ids = list(old_row) + [resource_id for resource_id in new_row if resource_id not in old_row]
        row: dict[str, CellDiff] = {}
        for resource_id in resource_ids:
            old = old_row.get(resource_id, NO_OPERATIONS)
            new = new_row.get(resource_id, NO_OPERATIONS)
            row[resource_id] = CellDiff(kept=old & new, removed=old - new, added=new - old)
        result[subject_id] = row
    return result


def is_submatrix(
    smaller: Mapping[str, Mapping[str, OperationSet]],
    larger: Mapping[str, Mapping[str, OperationSet]],
) -> bool:
    """Чи кожне право першої матриці є і в другій (перша — підмножина другої)."""
    return all(
        operations <= larger.get(subject_id, {}).get(resource_id, NO_OPERATIONS)
        for subject_id, row in smaller.items()
        for resource_id, operations in row.items()
    )


def set_user_rights(
    enterprise: Enterprise,
    model: AccessModel,
    user_id: str,
    resource_id: str,
    operations: Iterable[Operation],
    reason: str = "",
) -> AccessModel:
    """Задає бажані ефективні права користувача на ресурсі (режим «що буде, якщо»).

    На рівні користувача змінюються лише індивідуальні дозволи: операції, яких
    немає в ролі, оформлюються індивідуальним дозволом, а права ролі зберігаються
    (їх змінюють у матриці ролей). Без нової причини зберігається наявна.
    """
    role_id = enterprise.user(user_id).role_id
    extra = frozenset(operations) - model.role_operations(role_id, resource_id)
    existing = model.grant(user_id, resource_id)
    if not reason and existing is not None:
        reason = existing.reason
    return model.with_grant(user_id, resource_id, extra, reason)
