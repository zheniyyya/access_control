"""Виявлення надлишкових і небезпечних прав доступу.

Знахідка — трійка (користувач, ресурс, операція), яка є в ефективних правах
досліджуваної моделі, але відсутня в еталонній моделі мінімальних привілеїв.
Для кожної знахідки визначаються джерело права, правила П1–П9, що спрацювали,
рівень небезпеки (максимум серед правил) і рекомендація.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from enum import Enum

from app.domain.models import (
    MODIFYING_OPERATIONS,
    AccessModel,
    Enterprise,
    IndividualGrant,
    Operation,
    OperationSet,
    Resource,
    Role,
    RuleBindings,
    User,
    ordered,
)
from app.services.matrix import GrantSource, effective_rights, source_of


class Severity(Enum):
    """Рівень небезпеки; rank — для порівняння (більше — небезпечніше)."""

    label: str
    rank: int

    CRITICAL = ("Критичний", 4)
    HIGH = ("Високий", 3)
    MEDIUM = ("Середній", 2)
    LOW = ("Низький", 1)

    def __init__(self, label: str, rank: int) -> None:
        self.label = label
        self.rank = rank


@dataclass(frozen=True)
class RightContext:
    """Право, яке оцінюють правила: роль, ресурс, операція та джерело надання."""

    role: Role
    resource: Resource
    operation: Operation
    source: GrantSource
    bindings: RuleBindings

    @property
    def is_admin(self) -> bool:
        """Право належить адміністратору."""
        return self.role.id == self.bindings.admin_role_id

    @property
    def is_employee(self) -> bool:
        """Право належить співробітнику."""
        return self.role.id == self.bindings.employee_role_id

    @property
    def is_guest(self) -> bool:
        """Право належить гостю."""
        return self.role.id == self.bindings.guest_role_id

    @property
    def on_critical(self) -> bool:
        """Право стосується критичного ресурсу."""
        return self.resource.critical

    @property
    def on_finance(self) -> bool:
        """Право стосується фінансової документації."""
        return self.resource.id == self.bindings.finance_resource_id

    @property
    def on_audit_log(self) -> bool:
        """Право стосується журналу аудиту."""
        return self.resource.id == self.bindings.audit_log_resource_id

    @property
    def modifies(self) -> bool:
        """Операція змінює дані (З, Р або В)."""
        return self.operation in MODIFYING_OPERATIONS

    @property
    def deletes(self) -> bool:
        """Операція — видалення."""
        return self.operation is Operation.DELETE


@dataclass(frozen=True)
class Rule:
    """Правило виявлення небезпечного права."""

    code: str
    title: str
    severity: Severity
    rationale: str  # обґрунтування, що потрапляє в рекомендацію
    applies: Callable[[RightContext], bool]


DANGER_RULES: tuple[Rule, ...] = (
    Rule(
        code="П1",
        title="Гість має будь-яку операцію на критичному ресурсі",
        severity=Severity.CRITICAL,
        rationale="гість має доступ лише до загальнодоступної інформації",
        applies=lambda c: c.is_guest and c.on_critical,
    ),
    Rule(
        code="П2",
        title="Будь-хто має З, Р або В на журналі аудиту (R5)",
        severity=Severity.CRITICAL,
        rationale="журнал аудиту можна лише читати — цілісність журналу",
        applies=lambda c: c.on_audit_log and c.modifies,
    ),
    Rule(
        code="П3",
        title="Будь-хто має В на фінансовій документації (R2)",
        severity=Severity.CRITICAL,
        rationale="фінансові документи не видаляються вручну — обов'язкові строки зберігання",
        applies=lambda c: c.on_finance and c.deletes,
    ),
    Rule(
        code="П4",
        title="Адміністратор має будь-яку операцію на критичному ресурсі",
        severity=Severity.HIGH,
        rationale="адміністратор не має доступу до вмісту критичних бізнес-даних — розподіл обов'язків",
        applies=lambda c: c.is_admin and c.on_critical,
    ),
    Rule(
        code="П5",
        title="Співробітник має будь-яку операцію на R2",
        severity=Severity.HIGH,
        rationale="фінансова документація не потрібна співробітнику для службових функцій",
        applies=lambda c: c.is_employee and c.on_finance,
    ),
    Rule(
        code="П6",
        title="Співробітник або гість має В на критичному ресурсі",
        severity=Severity.HIGH,
        rationale="видалення критичних даних не входить до функцій співробітників і гостей",
        applies=lambda c: (c.is_employee or c.is_guest) and c.on_critical and c.deletes,
    ),
    Rule(
        code="П7",
        title="Гість має З, Р або В на будь-якому ресурсі",
        severity=Severity.HIGH,
        rationale="гість не може змінювати дані підприємства",
        applies=lambda c: c.is_guest and c.modifies,
    ),
    Rule(
        code="П8",
        title="Операцію надано індивідуальним дозволом, а не роллю",
        severity=Severity.MEDIUM,
        rationale="індивідуальні дозволи поза роллю скасовуються — чиста RBAC-модель",
        applies=lambda c: c.source is GrantSource.INDIVIDUAL,
    ),
)

BASELINE_RULE = Rule(
    code="П9",
    title="Операція відсутня в еталонній моделі (базове правило, спрацьовує завжди)",
    severity=Severity.LOW,
    rationale="операція не потрібна для службових функцій ролі — принцип мінімальних привілеїв",
    applies=lambda c: True,
)

ALL_RULES: tuple[Rule, ...] = DANGER_RULES + (BASELINE_RULE,)


@dataclass(frozen=True)
class Finding:
    """Надлишкове або небезпечне право — трійка (користувач, ресурс, операція)."""

    user_id: str
    role_id: str
    resource_id: str
    operation: Operation
    source: GrantSource
    rule_codes: tuple[str, ...]
    severity: Severity
    recommendation: str
    grant_reason: str = ""  # причина надання, якщо право отримано індивідуальним дозволом


@dataclass(frozen=True)
class RoleExcess:
    """Надлишкова клітинка матриці ролей (агреговане подання на рівні ролей)."""

    role_id: str
    resource_id: str
    granted: OperationSet  # операції ролі в досліджуваній моделі
    required: OperationSet  # операції ролі в еталонній моделі
    excess: OperationSet  # надлишкові операції: granted − required
    rule_codes: tuple[str, ...]
    severity: Severity
    user_count: int  # скільки користувачів успадковують надлишок


@dataclass(frozen=True)
class GrantSummary:
    """Індивідуальний дозвіл поза роллю та його оцінка."""

    user_id: str
    role_id: str
    resource_id: str
    operations: OperationSet
    excess: OperationSet  # операції дозволу, відсутні в еталоні
    reason: str
    severity: Severity | None  # найвищий рівень серед знахідок дозволу


def matching_rules(context: RightContext, rules: Iterable[Rule] = ALL_RULES) -> list[Rule]:
    """Правила, що спрацювали для права (у порядку П1 … П9)."""
    return [rule for rule in rules if rule.applies(context)]


def strongest_rule(rules: Sequence[Rule]) -> Rule:
    """Правило з найвищим рівнем небезпеки; за рівності — перше за порядком."""
    return max(rules, key=lambda rule: rule.severity.rank)


def max_severity(severities: Iterable[Severity]) -> Severity | None:
    """Найвищий рівень небезпеки (None — порожній перелік)."""
    return max(severities, key=lambda severity: severity.rank, default=None)


def rule_by_code(code: str) -> Rule:
    """Правило за кодом («П1» … «П9»)."""
    for rule in ALL_RULES:
        if rule.code == code:
            return rule
    raise KeyError(f"Правило «{code}» не існує")


def _recommendation(context: RightContext, rule: Rule) -> str:
    """Рекомендація: дія за джерелом права + обґрунтування найсуворішого правила."""
    role = f"«{context.role.name}»"
    actions = {
        GrantSource.ROLE: f"Вилучити операцію з прав ролі {role}",
        GrantSource.INDIVIDUAL: "Відкликати індивідуальний дозвіл",
        GrantSource.ROLE_AND_INDIVIDUAL: (
            f"Відкликати індивідуальний дозвіл і вилучити операцію з прав ролі {role}"
        ),
    }
    return f"{actions[context.source]}: {rule.rationale}"


def _granted_rights(
    enterprise: Enterprise, model: AccessModel, user: User
) -> Iterator[tuple[Resource, Operation, GrantSource, IndividualGrant | None]]:
    """Перебирає всі операції користувача разом із джерелом надання."""
    for resource in enterprise.resources:
        role_operations = model.role_operations(user.role_id, resource.id)
        grant = model.grant(user.id, resource.id)
        grant_operations = grant.operations if grant is not None else frozenset()
        for operation in Operation:
            source = source_of(operation in role_operations, operation in grant_operations)
            if source is not None:
                yield resource, operation, source, grant


def _finding(
    user: User,
    context: RightContext,
    rules: Sequence[Rule],
    grant: IndividualGrant | None,
) -> Finding:
    """Створює знахідку з переліку правил, що спрацювали."""
    main_rule = strongest_rule(rules)
    grant_reason = ""
    if grant is not None and context.source is not GrantSource.ROLE:
        grant_reason = grant.reason
    return Finding(
        user_id=user.id,
        role_id=context.role.id,
        resource_id=context.resource.id,
        operation=context.operation,
        source=context.source,
        rule_codes=tuple(rule.code for rule in rules),
        severity=main_rule.severity,
        recommendation=_recommendation(context, main_rule),
        grant_reason=grant_reason,
    )


def find_excess_rights(
    enterprise: Enterprise, model: AccessModel, reference: AccessModel
) -> list[Finding]:
    """Знахідки: права моделі, відсутні в еталонній моделі мінімальних привілеїв."""
    findings: list[Finding] = []
    for user in enterprise.users:
        role = enterprise.role(user.role_id)
        reference_rights = effective_rights(enterprise, reference, user.id)
        for resource, operation, source, grant in _granted_rights(enterprise, model, user):
            if operation in reference_rights[resource.id]:
                continue
            context = RightContext(role, resource, operation, source, enterprise.bindings)
            findings.append(_finding(user, context, matching_rules(context, ALL_RULES), grant))
    return findings


def audit_rules(enterprise: Enterprise, model: AccessModel) -> list[Finding]:
    """Перевіряє всі права моделі правилами П1–П8 (без порівняння з еталоном)."""
    findings: list[Finding] = []
    for user in enterprise.users:
        role = enterprise.role(user.role_id)
        for resource, operation, source, grant in _granted_rights(enterprise, model, user):
            context = RightContext(role, resource, operation, source, enterprise.bindings)
            rules = matching_rules(context, DANGER_RULES)
            if rules:
                findings.append(_finding(user, context, rules, grant))
    return findings


def role_excess(
    enterprise: Enterprise, model: AccessModel, reference: AccessModel
) -> list[RoleExcess]:
    """Надлишкові клітинки матриці ролей: операції ролі, яких немає в еталоні."""
    rows: list[RoleExcess] = []
    for role in enterprise.roles:
        user_count = len(enterprise.users_of_role(role.id))
        for resource in enterprise.resources:
            granted = model.role_operations(role.id, resource.id)
            required = reference.role_operations(role.id, resource.id)
            excess = granted - required
            if not excess:
                continue
            matched: set[str] = set()
            for operation in ordered(excess):
                context = RightContext(
                    role, resource, operation, GrantSource.ROLE, enterprise.bindings
                )
                matched.update(rule.code for rule in matching_rules(context, ALL_RULES))
            rules = [rule for rule in ALL_RULES if rule.code in matched]
            rows.append(
                RoleExcess(
                    role_id=role.id,
                    resource_id=resource.id,
                    granted=granted,
                    required=required,
                    excess=excess,
                    rule_codes=tuple(rule.code for rule in rules),
                    severity=strongest_rule(rules).severity,
                    user_count=user_count,
                )
            )
    return rows


def grant_summaries(
    enterprise: Enterprise, model: AccessModel, findings: Sequence[Finding]
) -> list[GrantSummary]:
    """Перелік індивідуальних дозволів з надлишковими операціями та рівнем небезпеки."""
    summaries: list[GrantSummary] = []
    for user in enterprise.users:
        for resource in enterprise.resources:
            grant = model.grant(user.id, resource.id)
            if grant is None:
                continue
            related = [
                finding
                for finding in findings
                if finding.user_id == user.id
                and finding.resource_id == resource.id
                and finding.source is not GrantSource.ROLE
            ]
            summaries.append(
                GrantSummary(
                    user_id=user.id,
                    role_id=user.role_id,
                    resource_id=resource.id,
                    operations=grant.operations,
                    excess=frozenset(finding.operation for finding in related),
                    reason=grant.reason,
                    severity=max_severity(finding.severity for finding in related),
                )
            )
    return summaries


def count_by_severity(findings: Iterable[Finding]) -> dict[Severity, int]:
    """Кількість знахідок кожного рівня небезпеки (від критичного до низького)."""
    counts = {severity: 0 for severity in Severity}
    for finding in findings:
        counts[finding.severity] += 1
    return counts


def count_by_resource(
    enterprise: Enterprise, findings: Iterable[Finding]
) -> dict[str, dict[Severity, int]]:
    """Кількість знахідок за рівнями небезпеки для кожного ресурсу."""
    counts = {
        resource.id: {severity: 0 for severity in Severity} for resource in enterprise.resources
    }
    for finding in findings:
        counts[finding.resource_id][finding.severity] += 1
    return counts


def count_by_rule(findings: Iterable[Finding]) -> dict[str, int]:
    """Скільки разів спрацювало кожне правило П1–П9."""
    counts = {rule.code: 0 for rule in ALL_RULES}
    for finding in findings:
        for code in finding.rule_codes:
            counts[code] += 1
    return counts


def filter_findings(
    findings: Iterable[Finding],
    severity: Severity | None = None,
    resource_id: str | None = None,
    role_id: str | None = None,
) -> list[Finding]:
    """Фільтр знахідок за рівнем, ресурсом і роллю (None — без обмеження)."""
    return [
        finding
        for finding in findings
        if (severity is None or finding.severity is severity)
        and (resource_id is None or finding.resource_id == resource_id)
        and (role_id is None or finding.role_id == role_id)
    ]


def find_finding(
    findings: Iterable[Finding], user_id: str, resource_id: str, operation: Operation
) -> Finding | None:
    """Знахідка для конкретної трійки (користувач, ресурс, операція), якщо вона є."""
    for finding in findings:
        if (
            finding.user_id == user_id
            and finding.resource_id == resource_id
            and finding.operation is operation
        ):
            return finding
    return None
