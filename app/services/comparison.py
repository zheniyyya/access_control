"""Порівняльні показники двох моделей доступу (початкової та оптимізованої)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from app.domain.models import AccessModel, Enterprise, Operation
from app.services.analyzer import Finding, Severity, audit_rules, count_by_severity
from app.services.formatting import (
    NBSP,
    count_phrase,
    fmt_number,
    fmt_signed,
    fmt_signed_percent,
    percent,
    round_half_up,
)
from app.services.matrix import (
    MatrixStats,
    Permissions,
    allowed_by_operation,
    allowed_by_resource,
    allowed_by_role_users,
    allowed_by_subject,
    matrix_stats,
    role_matrix,
    user_matrix,
)
from app.services.risk import (
    AggregateRisk,
    ResourceRisk,
    critical_risk,
    overall_risk,
    resource_risks,
)

PERCENT_POINTS = f"в.{NBSP}п."


@dataclass(frozen=True)
class ModelMetrics:
    """Усі кількісні показники однієї моделі доступу."""

    model: AccessModel
    role_matrix: Permissions
    user_matrix: Permissions
    role_stats: MatrixStats
    user_stats: MatrixStats
    allowed_by_role: dict[str, int]  # матриця ролей
    allowed_by_role_users: dict[str, int]  # усі користувачі кожної ролі
    allowed_by_operation: dict[Operation, int]  # матриця користувачів
    allowed_by_resource: dict[str, int]  # матриця користувачів
    risks: tuple[ResourceRisk, ...]
    critical: AggregateRisk
    overall: AggregateRisk
    violations: tuple[Finding, ...]  # порушення правил П1–П8

    @property
    def individual_operations(self) -> int:
        """Кількість операцій, наданих індивідуальними дозволами."""
        return self.model.grant_operation_count

    def risk_of(self, resource_id: str) -> ResourceRisk:
        """Ризик конкретного ресурсу."""
        for item in self.risks:
            if item.resource_id == resource_id:
                return item
        raise KeyError(f"Ресурс «{resource_id}» не знайдено")


def model_metrics(enterprise: Enterprise, model: AccessModel) -> ModelMetrics:
    """Обчислює всі показники моделі доступу."""
    roles = role_matrix(enterprise, model)
    users = user_matrix(enterprise, model)
    risks = tuple(resource_risks(enterprise, model))
    return ModelMetrics(
        model=model,
        role_matrix=roles,
        user_matrix=users,
        role_stats=matrix_stats(roles),
        user_stats=matrix_stats(users),
        allowed_by_role=allowed_by_subject(roles),
        allowed_by_role_users=allowed_by_role_users(enterprise, users),
        allowed_by_operation=allowed_by_operation(users),
        allowed_by_resource=allowed_by_resource(users),
        risks=risks,
        critical=critical_risk(enterprise, risks),
        overall=overall_risk(risks),
        violations=tuple(audit_rules(enterprise, model)),
    )


class Trend(Enum):
    """Яка зміна показника означає підвищення захищеності."""

    LOWER_IS_BETTER = "менше — краще"
    HIGHER_IS_BETTER = "більше — краще"


@dataclass(frozen=True)
class ComparisonRow:
    """Рядок порівняльної таблиці: «Початкова», «Оптимізована», «Зміна», «Зміна, %»."""

    key: str  # стабільний ідентифікатор показника (для тестів і експорту)
    section: str
    label: str
    initial: float
    optimized: float
    digits: int = 0
    is_percent: bool = False
    trend: Trend = Trend.LOWER_IS_BETTER

    @property
    def change(self) -> float:
        """Абсолютна зміна (для відсоткових показників — у відсоткових пунктах)."""
        return round_half_up(self.optimized - self.initial, self.digits)

    @property
    def change_percent(self) -> float | None:
        """Відносна зміна, %; None — якщо початкове значення дорівнює нулю."""
        if self.initial == 0:
            return None
        return percent(self.change, self.initial)

    @property
    def improved(self) -> bool | None:
        """True — захищеність підвищилася, False — знизилася, None — без змін."""
        if self.change == 0:
            return None
        return (self.change < 0) == (self.trend is Trend.LOWER_IS_BETTER)

    def _format(self, value: float) -> str:
        text = fmt_number(value, self.digits)
        return f"{text}{NBSP}%" if self.is_percent else text

    @property
    def initial_text(self) -> str:
        """Початкове значення для відображення."""
        return self._format(self.initial)

    @property
    def optimized_text(self) -> str:
        """Оптимізоване значення для відображення."""
        return self._format(self.optimized)

    @property
    def change_text(self) -> str:
        """Зміна для відображення: «−34» або «+35,0 в. п.»."""
        text = fmt_signed(self.change, self.digits)
        return f"{text}{NBSP}{PERCENT_POINTS}" if self.is_percent else text

    @property
    def change_percent_text(self) -> str:
        """Відносна зміна для відображення: «−50,7 %»."""
        return fmt_signed_percent(self.change_percent)


def compare(
    enterprise: Enterprise, before: ModelMetrics, after: ModelMetrics
) -> list[ComparisonRow]:
    """Порівняльна таблиця двох моделей за всіма групами показників."""
    rows: list[ComparisonRow] = []
    lower, higher = Trend.LOWER_IS_BETTER, Trend.HIGHER_IS_BETTER

    def section_adder(section: str) -> Callable[..., None]:
        def add(
            key: str,
            label: str,
            initial: float,
            optimized: float,
            *,
            trend: Trend = lower,
            digits: int = 0,
            is_percent: bool = False,
        ) -> None:
            rows.append(
                ComparisonRow(key, section, label, initial, optimized, digits, is_percent, trend)
            )

        return add

    add = section_adder("Загальні показники")
    total_roles, total_users = before.role_stats.total, before.user_stats.total
    add("roles.allowed", f"Дозволені операції — матриця ролей (з {total_roles})",
        before.role_stats.allowed, after.role_stats.allowed)
    add("roles.denied", f"Заборонені операції — матриця ролей (з {total_roles})",
        before.role_stats.denied, after.role_stats.denied, trend=higher)
    add("users.allowed", f"Дозволені операції — матриця користувачів (з {total_users})",
        before.user_stats.allowed, after.user_stats.allowed)
    add("users.denied", f"Заборонені операції — матриця користувачів (з {total_users})",
        before.user_stats.denied, after.user_stats.denied, trend=higher)
    add("grants.operations", "Операції за індивідуальними дозволами",
        before.individual_operations, after.individual_operations)

    add = section_adder("Дозволені операції за ролями (матриця ролей)")
    for role in enterprise.roles:
        add(f"roles.allowed.{role.id}", role.name,
            before.allowed_by_role[role.id], after.allowed_by_role[role.id])

    add = section_adder("Дозволені операції за ролями (усі користувачі ролі)")
    for role in enterprise.roles:
        members = len(enterprise.users_of_role(role.id))
        people = count_phrase(members, "користувач", "користувачі", "користувачів")
        add(f"users.allowed.{role.id}", f"{role.name} ({people})",
            before.allowed_by_role_users[role.id], after.allowed_by_role_users[role.id])

    add = section_adder("Дозволені операції за типами (матриця користувачів)")
    for operation in Operation:
        add(f"users.operation.{operation.name}", f"{operation.label} ({operation.short})",
            before.allowed_by_operation[operation], after.allowed_by_operation[operation])

    add = section_adder("Дозволені операції за ресурсами (матриця користувачів)")
    for resource in enterprise.resources:
        add(f"users.resource.{resource.id}", f"{resource.id} — {resource.name}",
            before.allowed_by_resource[resource.id], after.allowed_by_resource[resource.id])

    add = section_adder("Ризик і захищеність ресурсів")
    for resource in enterprise.resources:
        old, new = before.risk_of(resource.id), after.risk_of(resource.id)
        add(f"risk.{resource.id}", f"{resource.id}: індекс ризику (max {old.max_risk})",
            old.risk, new.risk)
        add(f"protection.{resource.id}", f"{resource.id}: рівень захищеності",
            old.protection, new.protection, trend=higher, digits=1, is_percent=True)

    add = section_adder(before.critical.title)
    add("critical.risk", f"Сумарний індекс ризику (max {before.critical.max_risk})",
        before.critical.risk, after.critical.risk)
    add("critical.protection", "Рівень захищеності",
        before.critical.protection, after.critical.protection,
        trend=higher, digits=1, is_percent=True)
    for resource in enterprise.critical_resources():
        old, new = before.risk_of(resource.id), after.risk_of(resource.id)
        add(f"access.{resource.id}", f"Користувачів з доступом до {resource.id}",
            old.users_any, new.users_any)
        add(f"modify.{resource.id}", f"Користувачів з модифікуючим доступом (З/Р/В) до {resource.id}",
            old.users_modify, new.users_modify)
        add(f"delete.{resource.id}", f"Користувачів з правом видалення на {resource.id}",
            old.users_delete, new.users_delete)

    add = section_adder(before.overall.title)
    add("total.risk", f"Сумарний індекс ризику (max {before.overall.max_risk})",
        before.overall.risk, after.overall.risk)
    add("total.protection", "Рівень захищеності",
        before.overall.protection, after.overall.protection,
        trend=higher, digits=1, is_percent=True)

    add = section_adder("Порушення правил П1–П8")
    old_counts = count_by_severity(before.violations)
    new_counts = count_by_severity(after.violations)
    for severity in (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM):
        add(f"violations.{severity.name}", f"{severity.label} рівень",
            old_counts[severity], new_counts[severity])
    add("violations.total", "Усього порушень", len(before.violations), len(after.violations))
    return rows
