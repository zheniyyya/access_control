"""Табличні дані для звітів: однакові таблиці для Excel і Word, без залежності від Qt.

Кожна функція перетворює AnalysisResult на Table — заголовки й рядки клітинок.
Клітинка зберігає значення (число або текст), його текстове подання, колір тла
(як у GUI) і, для матриць, операції з позначкою індивідуальних дозволів.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from app import palette
from app.domain.models import NO_OPERATIONS, Operation, OperationSet, operations_cell, operations_code
from app.services.analysis import AnalysisResult
from app.services.analyzer import ALL_RULES, Finding, Severity
from app.services.comparison import PERCENT_POINTS, ComparisonRow, ModelMetrics
from app.services.formatting import NBSP, fmt_number, fmt_percent, fmt_signed, fmt_signed_percent, percent
from app.services.matrix import cell_level
from app.services.risk import ProtectionLevel, rank_by_risk
from app.services.simulation import CompromiseImpact, simulate_compromise


class CellKind(Enum):
    """Тип значення клітинки — визначає числовий формат в Excel і текст у Word."""

    TEXT = "text"
    NUMBER = "number"
    PERCENT = "percent"  # 39,5 %
    SIGNED = "signed"  # +158 / −34
    POINTS = "points"  # +32,0 в. п.
    SIGNED_PERCENT = "signed_percent"  # −50,7 %


class Highlight(Enum):
    """Стовпці, для яких Excel додає умовне форматування кольорами."""

    MATRIX = "matrix"  # клітинки «ЧЗРВ»
    SEVERITY = "severity"  # рівень небезпеки
    PROTECTION = "protection"  # оцінка захищеності


@dataclass(frozen=True)
class TableCell:
    """Клітинка таблиці звіту."""

    value: str | int | float | None
    kind: CellKind = CellKind.TEXT
    fill: str | None = None  # колір тла «#rrggbb»
    bold: bool = False
    operations: OperationSet | None = None  # для клітинки матриці
    grant_operations: OperationSet = NO_OPERATIONS  # літери з індивідуального дозволу
    note: str = ""  # примітка (коментар Excel)
    digits: int = 0

    @property
    def text(self) -> str:
        """Текстове подання значення (як у застосунку)."""
        value = self.value
        if value is None:
            return "—"
        if isinstance(value, str):
            return value
        if self.kind is CellKind.PERCENT:
            return fmt_percent(value, self.digits)
        if self.kind is CellKind.SIGNED:
            return fmt_signed(value, self.digits)
        if self.kind is CellKind.POINTS:
            return f"{fmt_signed(value, self.digits)}{NBSP}{PERCENT_POINTS}"
        if self.kind is CellKind.SIGNED_PERCENT:
            return fmt_signed_percent(value, self.digits)
        return fmt_number(value, self.digits)


@dataclass(frozen=True)
class Table:
    """Таблиця звіту: заголовки, рядки клітинок, стовпці з умовним форматуванням."""

    title: str
    headers: tuple[str, ...]
    rows: tuple[tuple[TableCell, ...], ...]
    highlights: dict[int, Highlight] = field(default_factory=dict)


def _text(value: object, *, bold: bool = False, fill: str | None = None, note: str = "") -> TableCell:
    return TableCell(str(value), bold=bold, fill=fill, note=note)


def _number(value: int | float, kind: CellKind = CellKind.NUMBER, digits: int = 0, fill: str | None = None) -> TableCell:
    return TableCell(value, kind=kind, digits=digits, fill=fill)


def matrix_cell(operations: OperationSet, grant_operations: OperationSet = NO_OPERATIONS, note: str = "") -> TableCell:
    """Клітинка матриці: «Ч·РВ», колір — за найнебезпечнішою операцією."""
    return TableCell(
        operations_cell(operations),
        fill=palette.CELL_FILL[cell_level(operations)],
        operations=operations,
        grant_operations=grant_operations & operations,
        note=note,
    )


def severity_cell(severity: Severity | None) -> TableCell:
    """Клітинка рівня небезпеки з кольором рівня."""
    if severity is None:
        return _text("—")
    return _text(severity.label, fill=palette.SEVERITY_FILL[severity])


def protection_cell(level: ProtectionLevel) -> TableCell:
    """Клітинка оцінки захищеності з кольором рівня."""
    return _text(level.label, fill=palette.PROTECTION_FILL[level])


def users_table(result: AnalysisResult) -> Table:
    """Користувачі: ПІБ, посада, роль, індивідуальні дозволи поза роллю."""
    enterprise = result.enterprise
    model = enterprise.initial_model
    rows = []
    for user in enterprise.users:
        grants = "; ".join(
            f"{resource.id}: {operations_code(grant.operations)} ({grant.reason})"
            for resource in enterprise.resources
            if (grant := model.grant(user.id, resource.id)) is not None
        )
        rows.append(
            (
                _text(user.id, bold=True),
                _text(user.full_name),
                _text(user.position),
                _text(enterprise.role(user.role_id).name),
                _text(grants or "—"),
            )
        )
    return Table(
        f"Користувачі ({len(enterprise.users)})",
        ("ID", "ПІБ", "Посада", "Роль", "Індивідуальні дозволи поза роллю"),
        tuple(rows),
    )


def resources_table(result: AnalysisResult) -> Table:
    """Інформаційні ресурси з коефіцієнтом критичності."""
    rows = tuple(
        (
            _text(resource.id, bold=True),
            _text(resource.name),
            _text(resource.description),
            _number(resource.criticality),
            _text("так" if resource.critical else "ні", fill=palette.SEVERITY_FILL[Severity.CRITICAL] if resource.critical else None),
        )
        for resource in result.enterprise.resources
    )
    return Table(
        "Інформаційні ресурси",
        ("ID", "Ресурс", "Зміст", "K", "Критичний"),
        rows,
    )


def operations_table() -> Table:
    """Типи операцій і їхні ваги."""
    rows = tuple(
        (_text(operation.short, bold=True), _text(operation.label), _number(operation.weight), _text(operation.description))
        for operation in Operation
    )
    return Table("Типи операцій", ("Код", "Операція", "Вага", "Опис"), rows)


def _resource_headers(result: AnalysisResult) -> tuple[str, ...]:
    return tuple(resource.id for resource in result.enterprise.resources)


def role_matrix_table(result: AnalysisResult, metrics: ModelMetrics) -> Table:
    """Матриця ролей 4×6 моделі metrics."""
    enterprise = result.enterprise
    rows = []
    for role in enterprise.roles:
        cells = [matrix_cell(metrics.role_matrix[role.id][resource.id]) for resource in enterprise.resources]
        rows.append(
            (
                _text(role.name, bold=True),
                _number(len(enterprise.users_of_role(role.id))),
                *cells,
                _number(metrics.allowed_by_role[role.id]),
            )
        )
    info = 2
    stats = metrics.role_stats
    return Table(
        f"Матриця ролей — {metrics.model.name}: дозволено {stats.allowed} із {stats.total}, заборонено {stats.denied}",
        ("Роль", "Корист.", *_resource_headers(result), "Усього"),
        tuple(rows),
        highlights={info + position: Highlight.MATRIX for position in range(len(enterprise.resources))},
    )


def user_matrix_table(result: AnalysisResult, metrics: ModelMetrics) -> Table:
    """Матриця користувачів 20×6 (ефективні права), індивідуальні дозволи позначено."""
    enterprise = result.enterprise
    model = metrics.model
    rows = []
    for user in enterprise.users:
        role = enterprise.role(user.role_id)
        cells = []
        for resource in enterprise.resources:
            grant = model.grant(user.id, resource.id)
            note = (
                f"Індивідуальний дозвіл: {operations_code(grant.operations)} — {grant.reason or 'причину не вказано'}"
                if grant is not None
                else ""
            )
            cells.append(
                matrix_cell(metrics.user_matrix[user.id][resource.id], model.grant_operations(user.id, resource.id), note)
            )
        allowed = sum(len(operations) for operations in metrics.user_matrix[user.id].values())
        rows.append((_text(f"{user.id} {user.full_name}", bold=True), _text(role.name), *cells, _number(allowed)))
    stats = metrics.user_stats
    return Table(
        f"Матриця користувачів — {metrics.model.name}: дозволено {stats.allowed} із {stats.total}, "
        f"заборонено {stats.denied}",
        ("Користувач", "Роль", *_resource_headers(result), "Усього"),
        tuple(rows),
        highlights={2 + position: Highlight.MATRIX for position in range(len(enterprise.resources))},
    )


def grants_table(result: AnalysisResult) -> Table:
    """Індивідуальні дозволи поза роллю в початковій моделі."""
    enterprise = result.enterprise
    rows = tuple(
        (
            _text(f"{summary.user_id} {enterprise.user(summary.user_id).full_name}"),
            _text(enterprise.role(summary.role_id).name),
            _text(summary.resource_id),
            _text(operations_code(summary.operations)),
            severity_cell(summary.severity),
            _text(summary.reason),
        )
        for summary in result.grants
    )
    return Table(
        f"Індивідуальні дозволи поза роллю ({len(result.grants)}, операцій — {result.initial.individual_operations})",
        ("Користувач", "Роль", "Ресурс", "Операції", "Рівень", "Причина надання"),
        rows,
        highlights={4: Highlight.SEVERITY},
    )


def rules_table(result: AnalysisResult) -> Table:
    """Правила виявлення небезпечних прав і кількість їх спрацювань."""
    counts = result.rule_counts
    rows = tuple(
        (_text(rule.code, bold=True), _text(rule.title), severity_cell(rule.severity), _number(counts.get(rule.code, 0)))
        for rule in ALL_RULES
    )
    return Table(
        "Правила виявлення надлишкових і небезпечних прав",
        ("Код", "Правило", "Рівень", "Спрацювань"),
        rows,
        highlights={2: Highlight.SEVERITY},
    )


def severity_summary_table(result: AnalysisResult) -> Table:
    """Знахідки, зведені за рівнями небезпеки, з розподілом за ресурсами."""
    enterprise = result.enterprise
    by_resource = result.findings_by_resource
    counts = result.severity_counts
    rows = [
        (
            severity_cell(severity),
            *(_number(by_resource[resource.id][severity]) for resource in enterprise.resources),
            _number(counts[severity]),
        )
        for severity in Severity
    ]
    rows.append(
        (
            _text("Усього", bold=True),
            *(_number(sum(by_resource[resource.id].values())) for resource in enterprise.resources),
            _number(len(result.findings)),
        )
    )
    return Table(
        f"Надлишкові права за рівнями небезпеки (усього {len(result.findings)})",
        ("Рівень", *_resource_headers(result), "Усього"),
        tuple(rows),
        highlights={0: Highlight.SEVERITY},
    )


def role_excess_table(result: AnalysisResult) -> Table:
    """Надлишкові клітинки матриці ролей."""
    enterprise = result.enterprise
    rows = tuple(
        (
            _text(enterprise.role(row.role_id).name),
            _text(row.resource_id),
            _text(f"{operations_code(row.granted)}{NBSP}→{NBSP}{operations_code(row.required)}"),
            _text(operations_code(row.excess), bold=True),
            _text(", ".join(row.rule_codes)),
            severity_cell(row.severity),
            _number(row.user_count),
        )
        for row in result.role_excess
    )
    excess = sum(len(row.excess) for row in result.role_excess)
    return Table(
        f"Надлишкові права на рівні матриці ролей ({excess} операцій у {len(result.role_excess)} клітинках)",
        ("Роль", "Ресурс", "Надано → еталон", "Надлишок", "Правила", "Рівень", "Корист."),
        rows,
        highlights={5: Highlight.SEVERITY},
    )


def _finding_order(finding: Finding) -> tuple[int, str, str, int]:
    return (-finding.severity.rank, finding.user_id, finding.resource_id, finding.operation.weight)


def findings_table(result: AnalysisResult, compact: bool = False) -> Table:
    """Повна таблиця знахідок (надлишкових прав), найнебезпечніші — першими.

    compact — без ролі, рекомендації та причини надання (для звіту Word: рекомендації
    подано окремою таблицею, роль — у таблиці користувачів).
    """
    enterprise = result.enterprise
    rows = []
    for number, finding in enumerate(sorted(result.findings, key=_finding_order), start=1):
        user = enterprise.user(finding.user_id)
        cells = [_number(number), _text(f"{user.id} {user.full_name}")]
        if not compact:
            cells.append(_text(enterprise.role(finding.role_id).name))
        cells += [
            _text(finding.resource_id),
            _text(finding.operation.short),
            _text(finding.source.value),
            _text(", ".join(finding.rule_codes)),
            severity_cell(finding.severity),
        ]
        if not compact:
            cells += [_text(finding.recommendation), _text(finding.grant_reason or "—")]
        rows.append(tuple(cells))
    headers = ["№", "Користувач", *(() if compact else ("Роль",)), "Ресурс", "Операція", "Джерело", "Правила", "Рівень"]
    if not compact:
        headers += ["Рекомендація", "Причина надання"]
    return Table(
        f"Надлишкові та небезпечні права ({len(result.findings)})",
        tuple(headers),
        tuple(rows),
        highlights={headers.index("Рівень"): Highlight.SEVERITY},
    )


def recommendations_table(result: AnalysisResult) -> Table:
    """Рекомендації щодо усунення надлишкових прав (без повторів) і кількість знахідок."""
    counts: dict[str, int] = {}
    severity: dict[str, Severity] = {}
    for finding in sorted(result.findings, key=_finding_order):
        counts[finding.recommendation] = counts.get(finding.recommendation, 0) + 1
        severity.setdefault(finding.recommendation, finding.severity)
    rows = tuple(
        (_text(text), severity_cell(severity[text]), _number(count)) for text, count in counts.items()
    )
    return Table(
        "Рекомендації щодо усунення надлишкових прав",
        ("Рекомендація", "Рівень", "Знахідок"),
        rows,
        highlights={1: Highlight.SEVERITY},
    )


def functions_table(result: AnalysisResult) -> Table:
    """Службові функції ролей — основа моделі мінімальних привілеїв."""
    enterprise = result.enterprise
    rows = tuple(
        (
            _text(role.name, bold=True),
            _text(function.name),
            _text(function.resource_id),
            TableCell(operations_code(function.operations), fill=palette.CELL_FILL[cell_level(function.operations)]),
        )
        for role in enterprise.roles
        for function in role.functions
    )
    return Table(
        "Службові функції ролей",
        ("Роль", "Службова функція", "Ресурс", "Операції"),
        rows,
    )


def justification_table(result: AnalysisResult) -> Table:
    """Обґрунтування клітинок оптимізованої матриці ролей (лише змінені клітинки)."""
    enterprise = result.enterprise
    rows = tuple(
        (
            _text(enterprise.role(row.role_id).name),
            _text(row.resource_id),
            _text(operations_code(row.initial)),
            _text(operations_code(row.optimized), bold=True),
            _text(row.text),
        )
        for row in result.justification
        if row.removed or row.added
    )
    return Table(
        "Обґрунтування змін матриці ролей",
        ("Роль", "Ресурс", "Було", "Стало", "Обґрунтування"),
        rows,
    )


def _comparison_cells(row: ComparisonRow) -> tuple[TableCell, ...]:
    improved = row.improved
    fill = None if improved is None else palette.PROTECTION_FILL[ProtectionLevel.HIGH if improved else ProtectionLevel.LOW]
    value_kind = CellKind.PERCENT if row.is_percent else CellKind.NUMBER
    change_kind = CellKind.POINTS if row.is_percent else CellKind.SIGNED
    return (
        _text(row.label),
        _number(row.initial, value_kind, row.digits),
        _number(row.optimized, value_kind, row.digits),
        _number(row.change, change_kind, row.digits, fill=fill),
        TableCell(row.change_percent, kind=CellKind.SIGNED_PERCENT, digits=1, fill=fill),
    )


def comparison_table(result: AnalysisResult) -> Table:
    """Порівняльна таблиця з заголовками груп показників."""
    rows: list[tuple[TableCell, ...]] = []
    section = ""
    for row in result.comparison:
        if row.section != section:
            section = row.section
            rows.append((TableCell(section, bold=True, fill=palette.PAGE), *(TableCell("", fill=palette.PAGE) for _ in range(4))))
        rows.append(_comparison_cells(row))
    return Table(
        "Порівняльні показники початкової та оптимізованої моделей",
        ("Показник", "Початкова", "Оптимізована", "Зміна", "Зміна, %"),
        tuple(rows),
    )


def is_section_row(row: Sequence[TableCell]) -> bool:
    """Чи є рядок заголовком групи показників (порівняльна таблиця)."""
    return bool(row) and row[0].bold and all(cell.value == "" for cell in row[1:])


def risks_table(result: AnalysisResult, detailed: bool = True) -> Table:
    """Ризик і захищеність ресурсів обох моделей; detailed — з охопленням користувачами та знахідками."""
    by_resource = result.findings_by_resource
    places = {risk.resource_id: place for place, risk in enumerate(rank_by_risk(result.initial.risks), start=1)}
    rows: list[tuple[TableCell, ...]] = []
    for before, after in zip(result.initial.risks, result.optimized.risks):
        cells: list[TableCell] = [
            _text(f"{before.resource_id} {before.resource_name}", bold=True),
            _number(before.criticality),
            _number(before.max_risk),
            _number(before.risk),
            _number(before.protection, CellKind.PERCENT, 1),
            protection_cell(before.level),
        ]
        if detailed:
            cells += [_number(before.users_any), _number(before.users_modify), _number(before.users_delete)]
        cells += [
            _number(after.risk),
            _number(after.protection, CellKind.PERCENT, 1),
            protection_cell(after.level),
        ]
        if detailed:
            cells += [_number(after.users_any), _number(after.users_modify), _number(after.users_delete)]
            cells += [_number(by_resource[before.resource_id][severity]) for severity in Severity]
            cells.append(_number(places[before.resource_id]))
        rows.append(tuple(cells))
    for old, new in ((result.initial.critical, result.optimized.critical), (result.initial.overall, result.optimized.overall)):
        cells = [
            _text(old.title, bold=True, fill=palette.PAGE),
            _text("—", fill=palette.PAGE),
            _number(old.max_risk, fill=palette.PAGE),
            _number(old.risk, fill=palette.PAGE),
            _number(old.protection, CellKind.PERCENT, 1, fill=palette.PAGE),
            protection_cell(old.level),
        ]
        if detailed:
            cells += [_text("", fill=palette.PAGE)] * 3
        cells += [
            _number(new.risk, fill=palette.PAGE),
            _number(new.protection, CellKind.PERCENT, 1, fill=palette.PAGE),
            protection_cell(new.level),
        ]
        if detailed:
            cells += [_text("", fill=palette.PAGE)] * (3 + len(Severity) + 1)
        rows.append(tuple(cells))
    if detailed:
        headers = (
            "Ресурс", "K", "Max",
            "Ризик (поч.)", "Z (поч.)", "Оцінка (поч.)", "З доступом (поч.)", "З модифікацією (поч.)",
            "З видаленням (поч.)",
            "Ризик (опт.)", "Z (опт.)", "Оцінка (опт.)", "З доступом (опт.)", "З модифікацією (опт.)",
            "З видаленням (опт.)",
            *(f"Знахідки: {severity.label.lower()}" for severity in Severity),
            "Місце в рейтингу",
        )
        highlights = {5: Highlight.PROTECTION, 11: Highlight.PROTECTION}
    else:
        headers = ("Ресурс", "K", "Max", "Ризик (поч.)", "Z (поч.)", "Оцінка", "Ризик (опт.)", "Z (опт.)", "Оцінка")
        highlights = {5: Highlight.PROTECTION, 8: Highlight.PROTECTION}
    return Table("Ризик і захищеність інформаційних ресурсів", headers, tuple(rows), highlights)


def compromise_table(result: AnalysisResult) -> Table:
    """«Радіус ураження» компрометації кожного облікового запису: «початкова → оптимізована»."""
    enterprise = result.enterprise
    initial, optimized = result.initial.model, result.optimized.model

    def critical_changes(impact: CompromiseImpact) -> str:
        """Критичні ресурси, які зловмисник може змінити або видалити."""
        return f",{NBSP}".join(dict.fromkeys(impact.critical_modifiable + impact.critical_deletable)) or "—"

    def shift(before: object, after: object) -> TableCell:
        return _text(f"{before}{NBSP}→{NBSP}{after}")

    rows = []
    for user in enterprise.users:
        before = simulate_compromise(enterprise, initial, user.id)
        after = simulate_compromise(enterprise, optimized, user.id)
        change = percent(after.risk - before.risk, before.risk) if before.risk else None
        rows.append(
            (
                _text(f"{user.id} {user.full_name}"),
                _text(enterprise.role(user.role_id).name),
                shift(before.operation_count, after.operation_count),
                shift(before.risk, after.risk),
                TableCell(change, kind=CellKind.SIGNED_PERCENT, digits=1),
                shift(critical_changes(before), critical_changes(after)),
            )
        )
    return Table(
        "Сценарій компрометації облікових записів (початкова → оптимізована модель)",
        ("Користувач", "Роль", "Доступних операцій", "Ризик облікового запису", "Зміна ризику",
         "Критичні ресурси, які можна змінити чи видалити"),
        tuple(rows),
    )
