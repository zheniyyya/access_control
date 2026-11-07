"""Моделювання: перевірка запиту доступу та сценарій компрометації облікового запису."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import (
    TOTAL_WEIGHT,
    AccessModel,
    Enterprise,
    Operation,
    OperationSet,
    operations_code,
    operations_weight,
)
from app.services.formatting import percent
from app.services.matrix import GrantSource, effective_rights, operation_source

ALLOWED = "ДОЗВОЛЕНО"
DENIED = "ЗАБОРОНЕНО"

# Операції, що змінюють дані, але не видаляють їх («змінити» у сценарії компрометації).
CHANGING_OPERATIONS: OperationSet = frozenset({Operation.WRITE, Operation.EDIT})


@dataclass(frozen=True)
class AccessDecision:
    """Результат перевірки запиту доступу в одній моделі."""

    model_name: str
    user_id: str
    resource_id: str
    operation: Operation
    source: GrantSource | None
    explanation: str

    @property
    def allowed(self) -> bool:
        """Чи дозволено запит."""
        return self.source is not None

    @property
    def verdict(self) -> str:
        """«ДОЗВОЛЕНО» або «ЗАБОРОНЕНО»."""
        return ALLOWED if self.allowed else DENIED


@dataclass(frozen=True)
class CompromiseImpact:
    """«Радіус ураження» у разі компрометації облікового запису користувача."""

    model_name: str
    user_id: str
    rights: dict[str, OperationSet]  # ресурс → операції, доступні зловмиснику
    readable: tuple[str, ...]  # ресурси, які можна прочитати
    modifiable: tuple[str, ...]  # ресурси, які можна змінити (З або Р)
    deletable: tuple[str, ...]  # ресурси, з яких можна видаляти
    critical_readable: tuple[str, ...]
    critical_modifiable: tuple[str, ...]
    critical_deletable: tuple[str, ...]
    operation_count: int
    risk: int  # Σ K(r) × Σ ваг доступних операцій
    max_risk: int  # ризик облікового запису з усіма операціями на всіх ресурсах

    @property
    def accessible(self) -> tuple[str, ...]:
        """Ресурси з будь-яким доступом."""
        return tuple(resource_id for resource_id, operations in self.rights.items() if operations)

    @property
    def risk_share(self) -> float:
        """Частка ризику від максимально можливого для одного облікового запису, %."""
        return percent(self.risk, self.max_risk) if self.max_risk else 0.0


def check_access(
    enterprise: Enterprise,
    model: AccessModel,
    user_id: str,
    resource_id: str,
    operation: Operation,
) -> AccessDecision:
    """Перевіряє запит «користувач — ресурс — операція» та пояснює рішення."""
    user = enterprise.user(user_id)
    role = enterprise.role(user.role_id)
    resource = enterprise.resource(resource_id)
    role_operations = model.role_operations(role.id, resource.id)
    grant = model.grant(user.id, resource.id)
    reason = grant.reason if grant is not None and grant.reason else "не вказано"
    source = operation_source(enterprise, model, user.id, resource.id, operation)
    requested = f"«{operation.label}» ({operation.short})"
    if source is None:
        if role_operations:
            role_part = f"роль «{role.name}» має на {resource.id} лише «{operations_code(role_operations)}»"
        else:
            role_part = f"роль «{role.name}» не має доступу до {resource.id}"
        explanation = (
            f"Немає права на операцію {requested}: {role_part}, "
            "індивідуального дозволу на цю операцію немає."
        )
    elif source is GrantSource.ROLE:
        explanation = (
            f"Операцію {requested} надано через роль «{role.name}»: "
            f"права ролі на {resource.id} — «{operations_code(role_operations)}»."
        )
    elif source is GrantSource.INDIVIDUAL:
        explanation = (
            f"Операцію {requested} надано через індивідуальний дозвіл поза роллю "
            f"«{role.name}» (причина: {reason})."
        )
    else:
        explanation = (
            f"Операцію {requested} надано і роллю «{role.name}», "
            f"і індивідуальним дозволом (причина: {reason})."
        )
    return AccessDecision(
        model_name=model.name,
        user_id=user.id,
        resource_id=resource.id,
        operation=operation,
        source=source,
        explanation=explanation,
    )


def simulate_compromise(
    enterprise: Enterprise, model: AccessModel, user_id: str
) -> CompromiseImpact:
    """Що зможе зробити зловмисник, заволодівши обліковим записом користувача."""
    rights = effective_rights(enterprise, model, user_id)
    critical_ids = {resource.id for resource in enterprise.critical_resources()}
    readable = tuple(rid for rid, ops in rights.items() if Operation.READ in ops)
    modifiable = tuple(rid for rid, ops in rights.items() if ops & CHANGING_OPERATIONS)
    deletable = tuple(rid for rid, ops in rights.items() if Operation.DELETE in ops)
    risk = sum(
        enterprise.resource(resource_id).criticality * operations_weight(operations)
        for resource_id, operations in rights.items()
    )
    max_risk = TOTAL_WEIGHT * sum(resource.criticality for resource in enterprise.resources)
    return CompromiseImpact(
        model_name=model.name,
        user_id=user_id,
        rights=rights,
        readable=readable,
        modifiable=modifiable,
        deletable=deletable,
        critical_readable=tuple(rid for rid in readable if rid in critical_ids),
        critical_modifiable=tuple(rid for rid in modifiable if rid in critical_ids),
        critical_deletable=tuple(rid for rid in deletable if rid in critical_ids),
        operation_count=sum(len(operations) for operations in rights.values()),
        risk=risk,
        max_risk=max_risk,
    )
