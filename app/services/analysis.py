"""Повний аналіз моделей: збирає результати всіх сервісів в одну структуру.

GUI після кожної зміни викликає analyze() і лише відображає результат;
експорт у Excel і Word використовує той самий результат, тому числа
у застосунку та у звітах завжди однакові.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import AccessModel, DutyFunction, Enterprise, Role
from app.services.analyzer import (
    Finding,
    GrantSummary,
    RoleExcess,
    Severity,
    count_by_resource,
    count_by_rule,
    count_by_severity,
    find_excess_rights,
    grant_summaries,
    role_excess,
)
from app.services.comparison import ComparisonRow, ModelMetrics, compare, model_metrics
from app.services.conclusions import Conclusion, build_conclusions
from app.services.matrix import CellDiff, diff_matrices, is_submatrix
from app.services.optimizer import CellJustification, justify_model, uncovered_functions
from app.services.risk import ResourceRisk, rank_by_risk


@dataclass(frozen=True)
class AnalysisResult:
    """Результати аналізу початкової моделі відносно моделі мінімальних привілеїв."""

    enterprise: Enterprise
    initial: ModelMetrics
    optimized: ModelMetrics
    findings: tuple[Finding, ...]  # надлишкові права користувачів
    role_excess: tuple[RoleExcess, ...]  # надлишкові клітинки матриці ролей
    grants: tuple[GrantSummary, ...]  # індивідуальні дозволи початкової моделі
    justification: tuple[CellJustification, ...]  # обґрунтування оптимізованої матриці
    role_changes: dict[str, dict[str, CellDiff]]  # матриця змін ролей
    user_changes: dict[str, dict[str, CellDiff]]  # матриця змін користувачів
    comparison: tuple[ComparisonRow, ...]
    conclusions: tuple[Conclusion, ...]
    uncovered: tuple[tuple[Role, DutyFunction], ...]  # функції без потрібних прав
    is_subset: bool  # оптимізована модель — підмножина початкової

    @property
    def severity_counts(self) -> dict[Severity, int]:
        """Кількість знахідок за рівнями небезпеки."""
        return count_by_severity(self.findings)

    @property
    def findings_by_resource(self) -> dict[str, dict[Severity, int]]:
        """Кількість знахідок за рівнями для кожного ресурсу."""
        return count_by_resource(self.enterprise, self.findings)

    @property
    def rule_counts(self) -> dict[str, int]:
        """Скільки разів спрацювало кожне правило."""
        return count_by_rule(self.findings)

    @property
    def risk_ranking(self) -> list[ResourceRisk]:
        """Рейтинг ресурсів початкової моделі за індексом ризику."""
        return rank_by_risk(self.initial.risks)


def analyze(enterprise: Enterprise, optimized: AccessModel) -> AnalysisResult:
    """Виконує повний аналіз: матриці, знахідки, ризики, порівняння, висновки."""
    initial_model = enterprise.initial_model
    before = model_metrics(enterprise, initial_model)
    after = model_metrics(enterprise, optimized)
    findings = tuple(find_excess_rights(enterprise, initial_model, optimized))
    role_rows = tuple(role_excess(enterprise, initial_model, optimized))
    return AnalysisResult(
        enterprise=enterprise,
        initial=before,
        optimized=after,
        findings=findings,
        role_excess=role_rows,
        grants=tuple(grant_summaries(enterprise, initial_model, findings)),
        justification=tuple(justify_model(enterprise, initial_model, optimized)),
        role_changes=diff_matrices(before.role_matrix, after.role_matrix),
        user_changes=diff_matrices(before.user_matrix, after.user_matrix),
        comparison=tuple(compare(enterprise, before, after)),
        conclusions=tuple(build_conclusions(enterprise, before, after, findings, role_rows)),
        uncovered=tuple(uncovered_functions(enterprise, optimized)),
        is_subset=is_submatrix(after.user_matrix, before.user_matrix),
    )
