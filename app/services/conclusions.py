"""Автоматичне формування висновків з фактично обчислених показників.

Текст не захардкожено: кожне речення будується з чисел, отриманих сервісами
matrix, analyzer, risk і comparison. Після змін у моделі («що буде, якщо»)
висновки перераховуються разом з усіма показниками.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from app.domain.models import (
    MODIFYING_OPERATIONS,
    Enterprise,
    Operation,
    OperationSet,
    Role,
    operations_code,
    operations_labels,
)
from app.services.analyzer import Finding, RoleExcess, Severity, count_by_severity
from app.services.comparison import PERCENT_POINTS, ModelMetrics
from app.services.formatting import (
    NBSP,
    count_phrase,
    fmt_percent,
    fmt_signed,
    fmt_signed_percent,
    join_and,
    percent,
    plural,
    round_half_up,
)
from app.services.matrix import GrantSource, diff_matrices
from app.services.optimizer import function_count, uncovered_functions
from app.services.risk import HIGH_PROTECTION, ProtectionLevel, ResourceRisk, rank_by_risk


@dataclass(frozen=True)
class Conclusion:
    """Пункт висновків: заголовок і текст."""

    title: str
    text: str


@dataclass(frozen=True)
class _RoleGroup:
    """Користувачі однієї ролі з модифікуючим доступом до ресурсу."""

    role: Role
    count: int
    operations: OperationSet  # найпоширеніший набір операцій у групі
    functions: tuple[str, ...]  # службові функції ролі на цьому ресурсі


def conclusions_text(conclusions: Sequence[Conclusion]) -> str:
    """Висновки одним текстом з нумерацією пунктів (для копіювання та звіту)."""
    return "\n\n".join(
        f"{index}. {item.title}. {item.text}" for index, item in enumerate(conclusions, start=1)
    )


def _shift(before: int, after: int) -> str:
    """Зміна у вигляді «−34; −50,7 %» (відносна — лише для ненульової бази)."""
    delta = fmt_signed(after - before)
    if before == 0:
        return delta
    return f"{delta}; {fmt_signed_percent(percent(after - before, before))}"


def _points(before: float, after: float) -> str:
    """Зміна відсоткового показника у відсоткових пунктах: «+35,0 в. п.»."""
    return f"{fmt_signed(after - before, 1)}{NBSP}{PERCENT_POINTS}"


def _movement(before: int, after: int, fall: str, rise: str, same: str) -> str:
    """«зменшилася з 67 до 33 (−34; −50,7 %)» або «не змінилася (67)»."""
    if before == after:
        return f"{same} ({before})"
    verb = fall if after < before else rise
    return f"{verb} з {before} до {after} ({_shift(before, after)})"


def _protection_movement(before: float, after: float, fall: str, rise: str, same: str) -> str:
    """«зріс з 17,0 % до 52,0 % (+35,0 в. п.)» або «не змінився (17,0 %)»."""
    if round_half_up(after - before, 1) == 0:
        return f"{same} ({fmt_percent(before)})"
    verb = fall if after < before else rise
    return f"{verb} з {fmt_percent(before)} до {fmt_percent(after)} ({_points(before, after)})"


def _severity_list(counts: dict[Severity, int], severities: Sequence[Severity]) -> str:
    """«критичний — 26, високий — 46, …»."""
    return ", ".join(f"{severity.label.lower()} — {counts[severity]}" for severity in severities)


def _structure(enterprise: Enterprise) -> Conclusion:
    critical = enterprise.critical_resources()
    weights = ", ".join(f"{operation.short} = {operation.weight}" for operation in Operation)
    if critical:
        names = join_and([f"«{resource.name}» ({resource.id})" for resource in critical])
        critical_text = f", з них критичних — {len(critical)}: {names}"
    else:
        critical_text = ", критичних серед них немає"
    text = (
        f"Побудовано модель системи розмежування доступу: користувачів — {len(enterprise.users)}, "
        f"ролей — {len(enterprise.roles)}, інформаційних ресурсів — "
        f"{len(enterprise.resources)}{critical_text}. "
        f"Типи доступу: {operations_labels(Operation)} (ваги: {weights}). "
        "Ефективні права користувача визначаються правами його ролі (RBAC) "
        "та індивідуальними дозволами поза роллю."
    )
    return Conclusion("Структура системи доступу", text)


def _initial_model(before: ModelMetrics) -> Conclusion:
    roles, users = before.role_stats, before.user_stats
    text = (
        f"У початковій матриці ролей дозволено {roles.allowed} із {roles.total} операцій "
        f"({fmt_percent(percent(roles.allowed, roles.total))}), заборонено — {roles.denied}. "
        f"З урахуванням індивідуальних дозволів користувачам дозволено {users.allowed} "
        f"із {users.total} операцій ({fmt_percent(percent(users.allowed, users.total))}), "
        f"заборонено — {users.denied}."
    )
    if before.individual_operations:
        operations = count_phrase(before.individual_operations, "операцію", "операції", "операцій")
        text += (
            " Кількість користувачів з індивідуальними дозволами поза роллю — "
            f"{before.model.grant_user_count}; ними надано {operations}."
        )
    return Conclusion("Початкова модель доступу", text)


def _excess(
    before: ModelMetrics, findings: Sequence[Finding], role_rows: Sequence[RoleExcess]
) -> Conclusion:
    if findings:
        role_operations = sum(len(row.excess) for row in role_rows)
        individual = [finding for finding in findings if finding.source is GrantSource.INDIVIDUAL]
        rights = count_phrase(len(findings), "надлишкове право", "надлишкові права", "надлишкових прав")
        text = (
            f"Порівняння з еталонною моделлю мінімальних привілеїв виявило {rights} користувачів "
            "(трійок «користувач – ресурс – операція»). На рівні матриці ролей надлишковими є "
            f"{count_phrase(role_operations, 'операція', 'операції', 'операцій')} у "
            f"{count_phrase(len(role_rows), 'клітинці', 'клітинках', 'клітинках')}"
        )
        if individual:
            extra = count_phrase(
                len(individual), "надлишкову операцію", "надлишкові операції", "надлишкових операцій"
            )
            users = len({finding.user_id for finding in individual})
            text += f"; ще {extra} надано індивідуальними дозволами (користувачів — {users})"
        severities = _severity_list(count_by_severity(findings), list(Severity))
        text += f". За рівнем небезпеки: {severities}."
    else:
        text = "Порівняння з еталонною моделлю мінімальних привілеїв не виявило надлишкових прав."
    ranking = rank_by_risk(before.risks)
    top = ranking[0]
    text += (
        " Найбільший ризик несанкціонованого доступу має ресурс "
        f"«{top.resource_name}» ({top.resource_id}): індекс ризику {top.risk} із {top.max_risk}, "
        f"захищеність {fmt_percent(top.protection)} (рівень — {top.level.label.lower()})"
    )
    others = ", ".join(f"{item.resource_id} ({item.risk})" for item in ranking[1:3])
    text += f"; далі в рейтингу — {others}." if others else "."
    return Conclusion("Надлишкові права та ресурси з найбільшим ризиком", text)


def _optimization(enterprise: Enterprise, before: ModelMetrics, after: ModelMetrics) -> Conclusion:
    roles_before, roles_after = before.role_stats, after.role_stats
    users_before, users_after = before.user_stats, after.user_stats
    text = (
        "Оптимізовану модель побудовано за принципом мінімальних привілеїв: права кожної ролі — "
        "об'єднання операцій, необхідних для її службових функцій "
        f"(усього функцій — {function_count(enterprise)}), індивідуальні дозволи поза роллю "
        "скасовано. Кількість дозволених операцій у матриці ролей "
        f"{_movement(roles_before.allowed, roles_after.allowed, 'зменшилася', 'зросла', 'не змінилася')}, "
        f"на рівні користувачів — з {users_before.allowed} до {users_after.allowed} "
        f"({_shift(users_before.allowed, users_after.allowed)}). "
        "Кількість заборонених операцій відповідно змінилася "
        f"з {roles_before.denied} до {roles_after.denied} ({_shift(roles_before.denied, roles_after.denied)}) "
        f"та з {users_before.denied} до {users_after.denied} "
        f"({_shift(users_before.denied, users_after.denied)})."
    )
    added = sum(
        len(cell.added)
        for row in diff_matrices(before.user_matrix, after.user_matrix).values()
        for cell in row.values()
    )
    if added:
        new_rights = count_phrase(added, "нову операцію", "нові операції", "нових операцій")
        text += f" Оптимізована модель надає {new_rights}, яких не було в початковій моделі."
    else:
        text += " Оптимізована модель є підмножиною початкової — жодного нового права не надано."
    uncovered = uncovered_functions(enterprise, after.model)
    if uncovered:
        names = join_and([f"«{function.name}» ({role.name})" for role, function in uncovered])
        text += f" Не забезпечено правами службові функції: {names}."
    else:
        text += " Усі службові функції ролей забезпечено необхідними операціями."
    return Conclusion("Оптимізована модель і зміна кількості операцій", text)


def _critical_resources(
    enterprise: Enterprise, before: ModelMetrics, after: ModelMetrics
) -> Conclusion:
    sentences: list[str] = []
    for resource in enterprise.critical_resources():
        old, new = before.risk_of(resource.id), after.risk_of(resource.id)
        risk_change = _movement(old.risk, new.risk, "знизився", "зріс", "не змінився")
        protection_change = _protection_movement(
            old.protection, new.protection, "знизився", "зріс", "не змінився"
        )
        sentences.append(
            f"Для ресурсу «{resource.name}» ({resource.id}) індекс ризику {risk_change}, "
            f"рівень захищеності {protection_change}; оцінка: "
            f"{old.level.label.lower()} → {new.level.label.lower()}."
        )
    if not sentences:
        sentences.append("Критичних ресурсів у моделі не визначено.")
    else:
        critical_change = _protection_movement(
            before.critical.protection, after.critical.protection,
            "знизилася", "зросла", "не змінилася",
        )
        sentences.append(f"Сумарна захищеність критичних ресурсів {critical_change}.")
    overall_change = _protection_movement(
        before.overall.protection, after.overall.protection, "знизилася", "зросла", "не змінилася"
    )
    sentences.append(f"Захищеність усіх ресурсів {overall_change}.")
    return Conclusion("Вплив на захищеність критичних ресурсів", " ".join(sentences))


def _critical_access(enterprise: Enterprise, before: ModelMetrics, after: ModelMetrics) -> Conclusion:
    finance_id = enterprise.bindings.finance_resource_id
    resources = sorted(
        enterprise.critical_resources(), key=lambda resource: resource.id != finance_id
    )
    parts: list[str] = []
    for index, resource in enumerate(resources):
        old, new = before.risk_of(resource.id), after.risk_of(resource.id)
        name = f"«{resource.name}» ({resource.id})"
        if index == 0:
            access = _movement(old.users_any, new.users_any, "зменшилася", "зросла", "не змінилася")
            lead = f"Кількість користувачів з доступом до ресурсу {name} {access}"
        else:
            lead = f"до ресурсу {name} — з {old.users_any} до {new.users_any}"
        parts.append(
            f"{lead}, з правом зміни (З/Р/В) — з {old.users_modify} до {new.users_modify}, "
            f"з правом видалення — з {old.users_delete} до {new.users_delete}"
        )
    text = "; ".join(parts) + "." if parts else "Критичних ресурсів у моделі не визначено."
    return Conclusion("Доступ до критичних даних", text)


def _violations(before: ModelMetrics, after: ModelMetrics, findings: Sequence[Finding]) -> Conclusion:
    danger_levels = (Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM)
    critical = [finding for finding in findings if finding.severity is Severity.CRITICAL]
    eliminated = sum(
        1
        for finding in critical
        if finding.operation not in after.user_matrix[finding.user_id][finding.resource_id]
    )
    found = count_phrase(len(before.violations), "порушення", "порушення", "порушень")
    text = f"Перевірка початкової моделі правилами П1–П8 виявила {found}"
    if before.violations:
        text += f" ({_severity_list(count_by_severity(before.violations), danger_levels)})"
    text += f". Кількість усунених критичних знахідок — {eliminated} із {len(critical)}."
    if after.violations:
        remaining = _severity_list(count_by_severity(after.violations), danger_levels)
        text += (
            " В оптимізованій моделі залишаються порушення: "
            f"{len(after.violations)} ({remaining})."
        )
    else:
        text += " В оптимізованій моделі порушень правил П1–П8 не виявлено."
    return Conclusion("Усунення небезпечних прав", text)


def _effectiveness(enterprise: Enterprise, before: ModelMetrics, after: ModelMetrics) -> Conclusion:
    improved = after.overall.protection > before.overall.protection
    clean = not after.violations
    covered = not uncovered_functions(enterprise, after.model)
    if improved and clean and covered:
        verdict = "Застосування принципу мінімальних привілеїв є ефективним"
    elif improved:
        verdict = "Застосування принципу мінімальних привілеїв є частково ефективним"
    else:
        verdict = (
            "У поточній конфігурації застосування принципу мінімальних привілеїв "
            "не підвищило захищеності"
        )
    users_change = _movement(
        before.user_stats.allowed, after.user_stats.allowed, "зменшилася", "зросла", "не змінилася"
    )
    risk_change = _movement(
        before.overall.risk, after.overall.risk, "знизився", "зріс", "не змінився"
    )
    protection_change = _protection_movement(
        before.overall.protection, after.overall.protection, "знизився", "зріс", "не змінився"
    )
    text = (
        f"{verdict}: кількість дозволених операцій користувачів {users_change}, "
        f"сумарний індекс ризику всіх ресурсів {risk_change}, рівень захищеності всіх ресурсів "
        f"{protection_change}, критичних — з {fmt_percent(before.critical.protection)} "
        f"до {fmt_percent(after.critical.protection)}."
    )
    if covered and improved:
        text += (
            " Кожна роль зберегла всі операції, потрібні для її службових функцій, "
            "тобто захищеність підвищено без втрати функціональності."
        )
    elif covered:
        text += " Кожна роль зберегла всі операції, потрібні для її службових функцій."
    if clean:
        text += " Порушень правил безпеки П1–П8 у новій моделі немає."
    return Conclusion("Ефективність принципу мінімальних привілеїв", text)


def _largest_modifying_group(
    enterprise: Enterprise, metrics: ModelMetrics, resource_id: str
) -> _RoleGroup | None:
    """Роль з найбільшою кількістю користувачів, що можуть змінювати ресурс."""
    best: _RoleGroup | None = None
    for role in enterprise.roles:
        cells = [
            metrics.user_matrix[user.id][resource_id]
            for user in enterprise.users_of_role(role.id)
            if metrics.user_matrix[user.id][resource_id] & MODIFYING_OPERATIONS
        ]
        if cells and (best is None or len(cells) > best.count):
            best = _RoleGroup(
                role=role,
                count=len(cells),
                operations=Counter(cells).most_common(1)[0][0],
                functions=tuple(function.name for function in role.functions_for(resource_id)),
            )
    return best


def _deleters_by_role(
    enterprise: Enterprise, metrics: ModelMetrics, resource_id: str
) -> list[tuple[Role, int]]:
    """Кількість користувачів кожної ролі з правом видалення на ресурсі."""
    groups: list[tuple[Role, int]] = []
    for role in enterprise.roles:
        count = sum(
            1
            for user in enterprise.users_of_role(role.id)
            if Operation.DELETE in metrics.user_matrix[user.id][resource_id]
        )
        if count:
            groups.append((role, count))
    return groups


def _residual_risks(enterprise: Enterprise, after: ModelMetrics) -> Conclusion:
    sentences: list[str] = []
    critical_ids = {resource.id for resource in enterprise.critical_resources()}
    exposed = [item for item in after.risks if item.resource_id in critical_ids and item.risk > 0]
    worst: ResourceRisk | None = max(
        exposed, key=lambda item: (item.risk, -item.protection), default=None
    )
    if worst is not None:
        sentences.append(
            "Найвищий залишковий ризик серед критичних ресурсів має ресурс "
            f"«{worst.resource_name}» ({worst.resource_id}): індекс ризику {worst.risk} "
            f"із {worst.max_risk}, захищеність {fmt_percent(worst.protection)} "
            f"(рівень — {worst.level.label.lower()})."
        )
        group = _largest_modifying_group(enterprise, after, worst.resource_id)
        if group is not None:
            people = count_phrase(group.count, "користувач", "користувачі", "користувачів")
            verb = plural(group.count, "зберігає", "зберігають", "зберігають")
            purpose = ""
            if group.functions:
                noun = plural(
                    len(group.functions), "службової функції", "службових функцій", "службових функцій"
                )
                names = join_and([f"«{name}»" for name in group.functions])
                purpose = f", оскільки вони потрібні для {noun} {names}"
            sentences.append(
                f"{people} ролі «{group.role.name}» {verb} права "
                f"«{operations_code(group.operations)}» на цьому ресурсі{purpose}; подальше "
                "зниження ризику можливе лише атрибутивним розмежуванням доступу (ABAC), "
                "наприклад за правилом «лише власні записи» (для клієнтської бази — "
                "«тільки свої клієнти»)."
            )
    for item in exposed:
        deleters = _deleters_by_role(enterprise, after, item.resource_id)
        if deleters:
            groups = join_and(
                [
                    f"{count_phrase(count, 'користувач', 'користувачі', 'користувачів')} "
                    f"ролі «{role.name}»"
                    for role, count in deleters
                ]
            )
            sentences.append(
                f"Право видалення на ресурсі «{item.resource_name}» ({item.resource_id}) мають: {groups} — "
                "доцільно запровадити підтвердження видалення другою особою та регулярне "
                "резервне копіювання."
            )
    weak = [
        item
        for item in after.risks
        if item.level is not ProtectionLevel.HIGH
        and (worst is None or item.resource_id != worst.resource_id)
    ]
    if weak:
        items = join_and(
            [
                f"{item.resource_id} «{item.resource_name}» ({fmt_percent(item.protection)})"
                for item in weak
            ]
        )
        sentences.append(
            f"Рівень захищеності нижче {fmt_percent(HIGH_PROTECTION, 0)} мають також: {items}; "
            "для них доцільні періодичний перегляд прав доступу та контроль подій у журналі аудиту."
        )
    if not sentences:
        sentences.append(
            "Суттєвих залишкових ризиків не виявлено: усі ресурси мають високий рівень захищеності."
        )
    return Conclusion("Залишкові ризики", " ".join(sentences))


def build_conclusions(
    enterprise: Enterprise,
    before: ModelMetrics,
    after: ModelMetrics,
    findings: Sequence[Finding],
    role_rows: Sequence[RoleExcess],
) -> list[Conclusion]:
    """Формує висновки з показників початкової (before) та оптимізованої (after) моделей."""
    return [
        _structure(enterprise),
        _initial_model(before),
        _excess(before, findings, role_rows),
        _optimization(enterprise, before, after),
        _critical_resources(enterprise, before, after),
        _critical_access(enterprise, before, after),
        _violations(before, after, findings),
        _effectiveness(enterprise, before, after),
        _residual_risks(enterprise, after),
    ]
