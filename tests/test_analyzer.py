"""Тести виявлення надлишкових і небезпечних прав (правила П1–П9)."""

from __future__ import annotations

import pytest

from app.domain.models import AccessModel, Enterprise, Operation
from app.services.analyzer import (
    Finding,
    Severity,
    audit_rules,
    count_by_resource,
    count_by_severity,
    filter_findings,
    find_excess_rights,
    find_finding,
    grant_summaries,
    role_excess,
    rule_by_code,
)
from app.services.matrix import GrantSource

R, W, E, D = Operation.READ, Operation.WRITE, Operation.EDIT, Operation.DELETE
CRITICAL, HIGH, MEDIUM, LOW = Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW


@pytest.fixture(scope="module")
def findings(enterprise: Enterprise, initial: AccessModel, optimized: AccessModel) -> list[Finding]:
    return find_excess_rights(enterprise, initial, optimized)


def test_total_findings(findings: list[Finding]) -> None:
    assert len(findings) == 158


def test_severity_counts(findings: list[Finding]) -> None:
    assert count_by_severity(findings) == {CRITICAL: 26, HIGH: 46, MEDIUM: 3, LOW: 83}


def test_role_level_excess(enterprise: Enterprise, initial: AccessModel, optimized: AccessModel) -> None:
    rows = role_excess(enterprise, initial, optimized)
    assert sum(len(row.excess) for row in rows) == 34
    assert len(rows) == 18
    by_cell = {(row.role_id, row.resource_id): row for row in rows}
    assert by_cell[("ADMIN", "R2")].severity is CRITICAL
    assert by_cell[("ADMIN", "R1")].severity is HIGH
    assert by_cell[("GUEST", "R1")].rule_codes == ("П1", "П9")
    assert by_cell[("EMPLOYEE", "R5")].severity is LOW
    assert by_cell[("ADMIN", "R1")].user_count == 2


def test_individual_excess(findings: list[Finding]) -> None:
    individual = [finding for finding in findings if finding.source is GrantSource.INDIVIDUAL]
    assert len(individual) == 14
    assert {finding.user_id for finding in individual} == {"U07", "U10", "U12", "U15", "U18", "U20"}
    assert all(finding.grant_reason for finding in individual)


def test_grant_summaries(enterprise: Enterprise, initial: AccessModel, findings: list[Finding]) -> None:
    summaries = grant_summaries(enterprise, initial, findings)
    assert len(summaries) == 8
    assert sum(len(summary.excess) for summary in summaries) == 14
    u12_r2 = next(s for s in summaries if (s.user_id, s.resource_id) == ("U12", "R2"))
    assert u12_r2.severity is CRITICAL
    u15_r6 = next(s for s in summaries if (s.user_id, s.resource_id) == ("U15", "R6"))
    assert u15_r6.severity is MEDIUM


@pytest.mark.parametrize(
    ("user_id", "resource_id", "operation", "severity"),
    [
        ("U20", "R2", R, CRITICAL),
        ("U12", "R2", D, CRITICAL),
        ("U01", "R5", E, CRITICAL),
        ("U03", "R5", D, CRITICAL),
        ("U07", "R2", W, HIGH),
        ("U15", "R6", D, MEDIUM),
    ],
)
def test_mandatory_findings(
    findings: list[Finding], user_id: str, resource_id: str, operation: Operation, severity: Severity
) -> None:
    finding = find_finding(findings, user_id, resource_id, operation)
    assert finding is not None
    assert finding.severity is severity


def test_rules_of_mandatory_findings(findings: list[Finding]) -> None:
    assert find_finding(findings, "U20", "R2", R).rule_codes == ("П1", "П8", "П9")
    assert find_finding(findings, "U12", "R2", D).rule_codes == ("П3", "П5", "П6", "П8", "П9")
    assert find_finding(findings, "U01", "R5", E).rule_codes == ("П2", "П9")
    assert find_finding(findings, "U07", "R2", W).rule_codes == ("П5", "П8", "П9")
    assert find_finding(findings, "U15", "R6", D).rule_codes == ("П8", "П9")


def test_baseline_rule_always_fires(findings: list[Finding]) -> None:
    assert all("П9" in finding.rule_codes for finding in findings)


def test_severity_is_maximum_of_rules(findings: list[Finding]) -> None:
    for finding in findings:
        strongest = max(rule_by_code(code).severity.rank for code in finding.rule_codes)
        assert finding.severity.rank == strongest


def test_not_excess_rights_are_not_findings(findings: list[Finding]) -> None:
    assert find_finding(findings, "U06", "R1", W) is None  # ЧЗР на R1 потрібні співробітнику
    assert find_finding(findings, "U03", "R2", E) is None  # керівник погоджує фінансові документи


def test_recommendation_depends_on_source(findings: list[Finding]) -> None:
    assert find_finding(findings, "U12", "R2", D).recommendation.startswith(
        "Відкликати індивідуальний дозвіл"
    )
    assert find_finding(findings, "U06", "R1", D).recommendation.startswith(
        "Вилучити операцію з прав ролі «Співробітник»"
    )


def test_findings_by_resource(enterprise: Enterprise, findings: list[Finding]) -> None:
    counts = count_by_resource(enterprise, findings)
    expected = {
        "R1": (5, 19, 0, 0),
        "R2": (7, 21, 0, 0),
        "R3": (0, 2, 0, 23),
        "R4": (0, 0, 1, 32),
        "R5": (14, 0, 0, 11),
        "R6": (0, 4, 2, 17),
    }
    for resource_id, (critical, high, medium, low) in expected.items():
        assert counts[resource_id] == {CRITICAL: critical, HIGH: high, MEDIUM: medium, LOW: low}


def test_filter_findings(findings: list[Finding]) -> None:
    assert len(filter_findings(findings, severity=CRITICAL)) == 26
    assert len(filter_findings(findings, resource_id="R5")) == 25
    assert len(filter_findings(findings, role_id="GUEST")) == 20
    assert len(filter_findings(findings, severity=CRITICAL, role_id="GUEST")) == 6


def test_optimized_model_has_no_rule_violations(enterprise: Enterprise, optimized: AccessModel) -> None:
    assert audit_rules(enterprise, optimized) == []
    assert find_excess_rights(enterprise, optimized, optimized) == []


def test_initial_model_rule_violations(enterprise: Enterprise, initial: AccessModel) -> None:
    violations = audit_rules(enterprise, initial)
    assert len(violations) == 75
    assert count_by_severity(violations) == {CRITICAL: 26, HIGH: 46, MEDIUM: 3, LOW: 0}
    assert all("П9" not in violation.rule_codes for violation in violations)
