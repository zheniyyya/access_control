"""Підготовка матриць доступу до відображення: заголовки, клітинки «ЧЗРВ», підказки."""

from __future__ import annotations

from app.domain.models import Operation, Resource, operations_code
from app.services.analysis import AnalysisResult
from app.services.comparison import ModelMetrics
from app.services.matrix import CellDiff
from app.ui.table_models import MatrixData, MatrixRow, access_cell, diff_cell


def resource_header(resource: Resource) -> str:
    """Компактний заголовок стовпця ресурсу: ідентифікатор, ознака критичності, K."""
    flag = " крит." if resource.critical else ""
    return f"{resource.id}{flag}\nK={resource.criticality}"


def resource_tooltip(resource: Resource) -> str:
    """Підказка до ресурсу."""
    text = (
        f"{resource.id} «{resource.name}»\n{resource.description}\n"
        f"Коефіцієнт критичності K = {resource.criticality}"
    )
    return text + ("\nКритичний ресурс" if resource.critical else "")


def _columns(result: AnalysisResult) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    resources = result.enterprise.resources
    return (
        tuple(resource.id for resource in resources),
        tuple(resource_header(resource) for resource in resources),
        tuple(resource_tooltip(resource) for resource in resources),
    )


def role_matrix_data(result: AnalysisResult, metrics: ModelMetrics, show_findings: bool) -> MatrixData:
    """Матриця ролей моделі metrics; show_findings — додати до підказок надлишкові операції."""
    enterprise = result.enterprise
    excess = (
        {(row.role_id, row.resource_id): row for row in result.role_excess} if show_findings else {}
    )
    rows: list[MatrixRow] = []
    for role in enterprise.roles:
        members = len(enterprise.users_of_role(role.id))
        cells = []
        for resource in enterprise.resources:
            operations = metrics.role_matrix[role.id][resource.id]
            lines = [
                f"Роль «{role.name}» → {resource.id} «{resource.name}»",
                f"Операції: {operations_code(operations)}",
                f"Користувачів із цією роллю: {members}",
            ]
            row = excess.get((role.id, resource.id))
            if row is not None:
                lines.append(
                    f"Надлишкові: {operations_code(row.excess)} — {row.severity.label.lower()} "
                    f"({', '.join(row.rule_codes)})"
                )
            cells.append(access_cell(operations, tooltip="\n".join(lines)))
        rows.append(
            MatrixRow(
                role.id,
                f"{role.name} ({members})",
                f"{role.description}\nКористувачів: {members}",
                (),
                tuple(cells),
            )
        )
    keys, headers, tooltips = _columns(result)
    return MatrixData((), keys, headers, tooltips, tuple(rows))


def user_matrix_data(result: AnalysisResult, metrics: ModelMetrics, show_findings: bool) -> MatrixData:
    """Матриця користувачів (ефективні права); літери індивідуальних дозволів виділено."""
    enterprise = result.enterprise
    model = metrics.model
    findings = (
        {(finding.user_id, finding.resource_id, finding.operation): finding for finding in result.findings}
        if show_findings
        else {}
    )
    rows: list[MatrixRow] = []
    for user in enterprise.users:
        role = enterprise.role(user.role_id)
        cells = []
        for resource in enterprise.resources:
            operations = metrics.user_matrix[user.id][resource.id]
            grant = model.grant(user.id, resource.id)
            grant_operations = model.grant_operations(user.id, resource.id)
            lines = [
                f"{user.id} {user.full_name} ({role.name}) → {resource.id} «{resource.name}»",
                f"Ефективні права: {operations_code(operations)}",
                f"• від ролі: {operations_code(model.role_operations(role.id, resource.id))}",
            ]
            if grant is not None:
                lines.append(
                    f"• індивідуальний дозвіл: {operations_code(grant_operations)} — "
                    f"{grant.reason or 'причину не вказано'}"
                )
            excess = [
                findings[(user.id, resource.id, operation)]
                for operation in Operation
                if (user.id, resource.id, operation) in findings
            ]
            if excess:
                lines.append(
                    "Надлишкові: "
                    + "; ".join(
                        f"{finding.operation.short} — {finding.severity.label.lower()} "
                        f"({', '.join(finding.rule_codes)})"
                        for finding in excess
                    )
                )
            cells.append(access_cell(operations, grant_operations, "\n".join(lines)))
        rows.append(
            MatrixRow(
                user.id,
                f"{user.id}  {user.full_name}",
                f"{user.full_name}\n{user.position}\nРоль: {role.name}",
                (role.name,),
                tuple(cells),
            )
        )
    keys, headers, tooltips = _columns(result)
    return MatrixData(("Роль",), keys, headers, tooltips, tuple(rows))


def _diff_tooltip(title: str, diff: CellDiff) -> str:
    """Підказка клітинки матриці змін."""
    lines = [
        title,
        f"Було: {operations_code(diff.kept | diff.removed)} → стало: {operations_code(diff.kept | diff.added)}",
        f"Збережено: {operations_code(diff.kept)}",
        f"Вилучено: {operations_code(diff.removed)}",
    ]
    if diff.added:
        lines.append(f"Додано: {operations_code(diff.added)}")
    return "\n".join(lines)


def role_changes_data(result: AnalysisResult) -> MatrixData:
    """Матриця змін ролей: початкова → оптимізована, з обґрунтуванням у підказках."""
    enterprise = result.enterprise
    reasons = {(row.role_id, row.resource_id): row.text for row in result.justification}
    rows: list[MatrixRow] = []
    for role in enterprise.roles:
        members = len(enterprise.users_of_role(role.id))
        cells = []
        for resource in enterprise.resources:
            diff = result.role_changes[role.id][resource.id]
            tooltip = _diff_tooltip(f"Роль «{role.name}» → {resource.id} «{resource.name}»", diff)
            reason = reasons.get((role.id, resource.id))
            cells.append(diff_cell(diff, f"{tooltip}\n{reason}" if reason else tooltip))
        rows.append(
            MatrixRow(role.id, f"{role.name} ({members})", f"{role.description}\nКористувачів: {members}", (), tuple(cells))
        )
    keys, headers, tooltips = _columns(result)
    return MatrixData((), keys, headers, tooltips, tuple(rows))


def user_changes_data(result: AnalysisResult) -> MatrixData:
    """Матриця змін користувачів (ефективні права): що вилучено, що збережено."""
    enterprise = result.enterprise
    rows: list[MatrixRow] = []
    for user in enterprise.users:
        role = enterprise.role(user.role_id)
        cells = tuple(
            diff_cell(
                result.user_changes[user.id][resource.id],
                _diff_tooltip(
                    f"{user.id} {user.full_name} ({role.name}) → {resource.id} «{resource.name}»",
                    result.user_changes[user.id][resource.id],
                ),
            )
            for resource in enterprise.resources
        )
        rows.append(
            MatrixRow(
                user.id,
                f"{user.id}  {user.full_name}",
                f"{user.full_name}\n{user.position}\nРоль: {role.name}",
                (role.name,),
                cells,
            )
        )
    keys, headers, tooltips = _columns(result)
    return MatrixData(("Роль",), keys, headers, tooltips, tuple(rows))
