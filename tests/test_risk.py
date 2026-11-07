"""Тести індексу ризику та рівня захищеності."""

from __future__ import annotations

import pytest

from app.domain.models import AccessModel, Enterprise
from app.services.risk import (
    ProtectionLevel,
    ResourceRisk,
    critical_risk,
    overall_risk,
    protection_level,
    protection_percent,
    rank_by_risk,
    resource_risks,
)

# Ресурс: (ризик, максимум, захищеність %).
INITIAL = {
    "R1": (498, 600, 17.0),
    "R2": (228, 600, 62.0),
    "R3": (338, 400, 15.5),
    "R4": (248, 400, 38.0),
    "R5": (124, 400, 69.0),
    "R6": (102, 200, 49.0),
}
OPTIMIZED = {
    "R1": (288, 600, 52.0),
    "R2": (54, 600, 91.0),
    "R3": (192, 400, 52.0),
    "R4": (86, 400, 78.5),
    "R5": (10, 400, 97.5),
    "R6": (44, 200, 78.0),
}


def _by_id(risks: list[ResourceRisk]) -> dict[str, ResourceRisk]:
    return {item.resource_id: item for item in risks}


@pytest.mark.parametrize(("model_fixture", "expected"), [("initial", INITIAL), ("optimized", OPTIMIZED)])
def test_resource_risk_and_protection(
    request: pytest.FixtureRequest,
    enterprise: Enterprise,
    model_fixture: str,
    expected: dict[str, tuple[int, int, float]],
) -> None:
    risks = _by_id(resource_risks(enterprise, request.getfixturevalue(model_fixture)))
    for resource_id, (risk, maximum, protection) in expected.items():
        item = risks[resource_id]
        assert (item.risk, item.max_risk, item.protection) == (risk, maximum, protection), resource_id


@pytest.mark.parametrize(
    ("model_fixture", "critical", "overall"),
    [
        ("initial", (726, 1200, 39.5), (1538, 2600, 40.8)),
        ("optimized", (342, 1200, 71.5), (674, 2600, 74.1)),
    ],
)
def test_aggregates(
    request: pytest.FixtureRequest,
    enterprise: Enterprise,
    model_fixture: str,
    critical: tuple[int, int, float],
    overall: tuple[int, int, float],
) -> None:
    risks = resource_risks(enterprise, request.getfixturevalue(model_fixture))
    critical_total = critical_risk(enterprise, risks)
    overall_total = overall_risk(risks)
    assert critical_total.resource_ids == ("R1", "R2")
    assert (critical_total.risk, critical_total.max_risk, critical_total.protection) == critical
    assert (overall_total.risk, overall_total.max_risk, overall_total.protection) == overall


def test_protection_levels(enterprise: Enterprise, initial: AccessModel, optimized: AccessModel) -> None:
    before = _by_id(resource_risks(enterprise, initial))
    after = _by_id(resource_risks(enterprise, optimized))
    assert before["R1"].level is ProtectionLevel.LOW
    assert before["R2"].level is ProtectionLevel.MEDIUM
    assert before["R6"].level is ProtectionLevel.LOW
    assert after["R1"].level is ProtectionLevel.MEDIUM
    assert after["R2"].level is ProtectionLevel.HIGH
    assert after["R5"].level is ProtectionLevel.HIGH
    assert critical_risk(enterprise, after.values()).level is ProtectionLevel.MEDIUM


def test_protection_level_thresholds() -> None:
    assert protection_level(80.0) is ProtectionLevel.HIGH
    assert protection_level(79.9) is ProtectionLevel.MEDIUM
    assert protection_level(50.0) is ProtectionLevel.MEDIUM
    assert protection_level(49.9) is ProtectionLevel.LOW


def test_protection_rounding_half_up() -> None:
    assert protection_percent(339, 400) == 15.3  # 15,25 → 15,3
    assert protection_percent(1538, 2600) == 40.8  # 40,846… → 40,8
    assert protection_percent(674, 2600) == 74.1  # 74,077… → 74,1
    assert protection_percent(0, 0) == 100.0


def test_ranking(enterprise: Enterprise, initial: AccessModel, optimized: AccessModel) -> None:
    before = [item.resource_id for item in rank_by_risk(resource_risks(enterprise, initial))]
    after = [item.resource_id for item in rank_by_risk(resource_risks(enterprise, optimized))]
    assert before[0] == "R1"
    assert before == ["R1", "R3", "R4", "R2", "R5", "R6"]
    assert after == ["R1", "R3", "R4", "R2", "R6", "R5"]


@pytest.mark.parametrize(
    ("model_fixture", "expected"),
    [
        (
            "initial",
            {"R1": (20, 17, 16), "R2": (17, 7, 6), "R3": (20, 17, 16),
             "R4": (20, 16, 6), "R5": (16, 6, 6), "R6": (20, 20, 6)},
        ),
        (
            "optimized",
            {"R1": (14, 14, 3), "R2": (3, 3, 0), "R3": (14, 14, 3),
             "R4": (16, 3, 3), "R5": (5, 0, 0), "R6": (20, 5, 2)},
        ),
    ],
)
def test_user_counts_per_resource(
    request: pytest.FixtureRequest,
    enterprise: Enterprise,
    model_fixture: str,
    expected: dict[str, tuple[int, int, int]],
) -> None:
    risks = _by_id(resource_risks(enterprise, request.getfixturevalue(model_fixture)))
    for resource_id, counts in expected.items():
        item = risks[resource_id]
        assert (item.users_any, item.users_modify, item.users_delete) == counts, resource_id
