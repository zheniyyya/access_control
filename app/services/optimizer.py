"""Побудова моделі мінімальних привілеїв зі службових функцій ролей.

Мінімальні права ролі на ресурсі = об'єднання операцій, необхідних для її
службових функцій. Індивідуальні дозволи в оптимізованій моделі не допускаються.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import (
    AccessModel,
    DutyFunction,
    Enterprise,
    OperationSet,
    Resource,
    Role,
    operations_code,
    ordered,
)
from app.services.analyzer import BASELINE_RULE, DANGER_RULES, RightContext, matching_rules
from app.services.formatting import plural
from app.services.matrix import GrantSource

OPTIMIZED_MODEL_NAME = "Оптимізована модель (мінімальні привілеї)"


@dataclass(frozen=True)
class CellJustification:
    """Обґрунтування клітинки оптимізованої матриці ролей."""

    role_id: str
    resource_id: str
    initial: OperationSet
    optimized: OperationSet
    removed: OperationSet
    added: OperationSet
    functions: tuple[str, ...]  # службові функції ролі, що потребують ресурсу
    rule_codes: tuple[str, ...]  # правила, яким відповідає вилучення операцій
    text: str


def build_min_privilege_model(
    enterprise: Enterprise, name: str = OPTIMIZED_MODEL_NAME
) -> AccessModel:
    """Будує модель мінімальних привілеїв: права ролей — лише для службових функцій."""
    permissions = {
        role.id: {
            resource.id: role.required_operations(resource.id)
            for resource in enterprise.resources
        }
        for role in enterprise.roles
    }
    return AccessModel(name=name, role_permissions=permissions, user_grants={})


def function_count(enterprise: Enterprise) -> int:
    """Загальна кількість службових функцій усіх ролей."""
    return sum(len(role.functions) for role in enterprise.roles)


def uncovered_functions(
    enterprise: Enterprise, model: AccessModel
) -> list[tuple[Role, DutyFunction]]:
    """Службові функції, яким модель не надає всіх потрібних операцій."""
    return [
        (role, function)
        for role in enterprise.roles
        for function in role.functions
        if not function.operations <= model.role_operations(role.id, function.resource_id)
    ]


def _removal_rules(
    enterprise: Enterprise, role: Role, resource: Resource, removed: OperationSet
) -> tuple[str, ...]:
    """Правила П1–П8, яким відповідають вилучені операції; інакше — базове П9."""
    matched: set[str] = set()
    for operation in ordered(removed):
        context = RightContext(role, resource, operation, GrantSource.ROLE, enterprise.bindings)
        matched.update(rule.code for rule in matching_rules(context, DANGER_RULES))
    codes = tuple(rule.code for rule in DANGER_RULES if rule.code in matched)
    if removed and not codes:
        return (BASELINE_RULE.code,)
    return codes


def _justification_text(
    after: OperationSet,
    removed: OperationSet,
    added: OperationSet,
    functions: tuple[str, ...],
    codes: tuple[str, ...],
) -> str:
    """Текст обґрунтування клітинки: що залишено, для чого, що вилучено і чому."""
    parts: list[str] = []
    if after and functions:
        noun = plural(len(functions), "службової функції", "службових функцій", "службових функцій")
        names = ", ".join(f"«{name}»" for name in functions)
        parts.append(f"Залишено «{operations_code(after)}» для {noun} {names}")
    elif after:
        parts.append(f"Залишено «{operations_code(after)}» (службових функцій для ресурсу не визначено)")
    elif removed:
        parts.append("Доступ скасовано: службові функції ролі не потребують цього ресурсу")
    else:
        parts.append("Доступу немає, і він не потрібен для службових функцій")
    if removed:
        parts.append(f"вилучено «{operations_code(removed)}» ({', '.join(codes)})")
    if added:
        parts.append(f"додано «{operations_code(added)}» для службових функцій")
    return "; ".join(parts) + "."


def justify_model(
    enterprise: Enterprise, initial: AccessModel, optimized: AccessModel
) -> list[CellJustification]:
    """Обґрунтування кожної клітинки оптимізованої матриці ролей."""
    rows: list[CellJustification] = []
    for role in enterprise.roles:
        for resource in enterprise.resources:
            before = initial.role_operations(role.id, resource.id)
            after = optimized.role_operations(role.id, resource.id)
            removed = before - after
            added = after - before
            functions = tuple(function.name for function in role.functions_for(resource.id))
            codes = _removal_rules(enterprise, role, resource, removed)
            rows.append(
                CellJustification(
                    role_id=role.id,
                    resource_id=resource.id,
                    initial=before,
                    optimized=after,
                    removed=removed,
                    added=added,
                    functions=functions,
                    rule_codes=codes,
                    text=_justification_text(after, removed, added, functions, codes),
                )
            )
    return rows
