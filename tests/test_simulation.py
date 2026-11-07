"""Тести моделювання: перевірка запиту доступу та компрометація облікового запису."""

from __future__ import annotations

from app.domain.models import AccessModel, Enterprise, Operation
from app.services.matrix import GrantSource
from app.services.simulation import ALLOWED, DENIED, check_access, simulate_compromise

R, W, E, D = Operation.READ, Operation.WRITE, Operation.EDIT, Operation.DELETE


def test_access_via_role(enterprise: Enterprise, initial: AccessModel) -> None:
    decision = check_access(enterprise, initial, "U06", "R1", D)
    assert decision.allowed
    assert decision.source is GrantSource.ROLE
    assert decision.verdict == ALLOWED
    assert "роль «Співробітник»" in decision.explanation


def test_access_via_individual_grant(enterprise: Enterprise, initial: AccessModel) -> None:
    decision = check_access(enterprise, initial, "U20", "R2", R)
    assert decision.source is GrantSource.INDIVIDUAL
    assert "індивідуальний дозвіл" in decision.explanation
    assert "для навчання" in decision.explanation


def test_access_denied(enterprise: Enterprise, initial: AccessModel, optimized: AccessModel) -> None:
    assert check_access(enterprise, initial, "U17", "R2", R).verdict == DENIED
    after = check_access(enterprise, optimized, "U20", "R2", R)
    assert not after.allowed
    assert after.verdict == DENIED
    assert "не має доступу до R2" in after.explanation
    partial = check_access(enterprise, optimized, "U06", "R1", D)
    assert not partial.allowed
    assert "лише «ЧЗР»" in partial.explanation


def test_compromise_of_reassigned_analyst(
    enterprise: Enterprise, initial: AccessModel, optimized: AccessModel
) -> None:
    before = simulate_compromise(enterprise, initial, "U12")
    after = simulate_compromise(enterprise, optimized, "U12")
    assert (before.risk, before.max_risk) == (105, 130)
    assert after.risk == 33
    assert before.critical_deletable == ("R1", "R2")
    assert after.critical_deletable == ()
    assert after.critical_modifiable == ("R1",)
    assert after.readable == ("R1", "R3", "R4", "R6")
    assert before.operation_count == 19
    assert after.operation_count == 8


def test_compromise_of_admin_and_guest(
    enterprise: Enterprise, initial: AccessModel, optimized: AccessModel
) -> None:
    admin_before = simulate_compromise(enterprise, initial, "U01")
    admin_after = simulate_compromise(enterprise, optimized, "U01")
    assert (admin_before.risk, admin_after.risk) == (130, 14)
    assert admin_after.critical_readable == ()
    guest_before = simulate_compromise(enterprise, initial, "U20")
    guest_after = simulate_compromise(enterprise, optimized, "U20")
    assert (guest_before.risk, guest_after.risk) == (13, 1)
    assert guest_before.critical_readable == ("R1", "R2")
    assert guest_after.accessible == ("R6",)
