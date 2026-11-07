"""Тести матриць доступу (контрольні значення розділу 7 технічного завдання)."""

from __future__ import annotations

import pytest

from app.domain.models import (
    AccessModel,
    Enterprise,
    Operation,
    operations_cell,
    operations_code,
    parse_operations,
)
from app.services.matrix import (
    CellLevel,
    GrantSource,
    allowed_by_operation,
    allowed_by_resource,
    allowed_by_role_users,
    allowed_by_subject,
    cell_level,
    diff_matrices,
    effective_rights,
    is_submatrix,
    matrix_stats,
    operation_source,
    role_matrix,
    set_user_rights,
    subjects_with_access,
    user_matrix,
)

R, W, E, D = Operation.READ, Operation.WRITE, Operation.EDIT, Operation.DELETE


@pytest.mark.parametrize(
    ("model_fixture", "allowed", "denied"),
    [("initial", 67, 29), ("optimized", 33, 63)],
)
def test_role_matrix_counts(
    request: pytest.FixtureRequest, enterprise: Enterprise, model_fixture: str, allowed: int, denied: int
) -> None:
    model: AccessModel = request.getfixturevalue(model_fixture)
    stats = matrix_stats(role_matrix(enterprise, model))
    assert (stats.total, stats.allowed, stats.denied) == (96, allowed, denied)


@pytest.mark.parametrize(
    ("model_fixture", "allowed", "denied"),
    [("initial", 316, 164), ("optimized", 158, 322)],
)
def test_user_matrix_counts(
    request: pytest.FixtureRequest, enterprise: Enterprise, model_fixture: str, allowed: int, denied: int
) -> None:
    model: AccessModel = request.getfixturevalue(model_fixture)
    stats = matrix_stats(user_matrix(enterprise, model))
    assert (stats.total, stats.allowed, stats.denied) == (480, allowed, denied)


@pytest.mark.parametrize(
    ("model_fixture", "expected"),
    [
        ("initial", {"ADMIN": 24, "MANAGER": 23, "EMPLOYEE": 15, "GUEST": 5}),
        ("optimized", {"ADMIN": 6, "MANAGER": 18, "EMPLOYEE": 8, "GUEST": 1}),
    ],
)
def test_allowed_by_role(
    request: pytest.FixtureRequest, enterprise: Enterprise, model_fixture: str, expected: dict[str, int]
) -> None:
    model: AccessModel = request.getfixturevalue(model_fixture)
    assert allowed_by_subject(role_matrix(enterprise, model)) == expected


@pytest.mark.parametrize(
    ("model_fixture", "expected"),
    [
        ("initial", {R: 113, W: 79, E: 68, D: 56}),
        ("optimized", {R: 72, W: 39, E: 36, D: 11}),
    ],
)
def test_allowed_by_operation(
    request: pytest.FixtureRequest,
    enterprise: Enterprise,
    model_fixture: str,
    expected: dict[Operation, int],
) -> None:
    model: AccessModel = request.getfixturevalue(model_fixture)
    assert allowed_by_operation(user_matrix(enterprise, model)) == expected


def test_allowed_by_role_users_and_resource(
    enterprise: Enterprise, initial: AccessModel, optimized: AccessModel
) -> None:
    before, after = user_matrix(enterprise, initial), user_matrix(enterprise, optimized)
    assert allowed_by_role_users(enterprise, before) == {
        "ADMIN": 48, "MANAGER": 69, "EMPLOYEE": 175, "GUEST": 24,
    }
    assert allowed_by_role_users(enterprise, after) == {
        "ADMIN": 12, "MANAGER": 54, "EMPLOYEE": 88, "GUEST": 4,
    }
    assert allowed_by_resource(before) == {
        "R1": 69, "R2": 37, "R3": 70, "R4": 58, "R5": 30, "R6": 52,
    }
    assert allowed_by_resource(after) == {
        "R1": 45, "R2": 9, "R3": 45, "R4": 25, "R5": 5, "R6": 29,
    }


@pytest.mark.parametrize(
    ("model_fixture", "access", "delete"),
    [("initial", (20, 17), (16, 6)), ("optimized", (14, 3), (3, 0))],
)
def test_users_with_access_to_critical_resources(
    request: pytest.FixtureRequest,
    enterprise: Enterprise,
    model_fixture: str,
    access: tuple[int, int],
    delete: tuple[int, int],
) -> None:
    users = user_matrix(enterprise, request.getfixturevalue(model_fixture))
    assert (
        len(subjects_with_access(users, "R1")),
        len(subjects_with_access(users, "R2")),
    ) == access
    assert (
        len(subjects_with_access(users, "R1", {D})),
        len(subjects_with_access(users, "R2", {D})),
    ) == delete


def test_effective_rights_are_role_union_grants(enterprise: Enterprise, initial: AccessModel) -> None:
    u12 = effective_rights(enterprise, initial, "U12")
    assert u12["R2"] == {R, W, E, D}  # Ч від ролі + ЗРВ індивідуально
    assert u12["R4"] == {R, W, E, D}  # ЧЗР від ролі + В індивідуально
    assert effective_rights(enterprise, initial, "U20")["R2"] == {R}
    assert effective_rights(enterprise, initial, "U17")["R2"] == frozenset()
    assert effective_rights(enterprise, initial, "U18")["R3"] == {R, W, E}


def test_operation_source(enterprise: Enterprise, initial: AccessModel) -> None:
    assert operation_source(enterprise, initial, "U12", "R2", R) is GrantSource.ROLE
    assert operation_source(enterprise, initial, "U12", "R2", D) is GrantSource.INDIVIDUAL
    assert operation_source(enterprise, initial, "U17", "R2", R) is None
    with_both = initial.with_grant("U06", "R1", {R}, "Перевірка")
    assert operation_source(enterprise, with_both, "U06", "R1", R) is GrantSource.ROLE_AND_INDIVIDUAL


def test_cell_level_colors() -> None:
    assert cell_level(frozenset()) is CellLevel.NONE
    assert cell_level({R}) is CellLevel.READ
    assert cell_level({R, W}) is CellLevel.MODIFY
    assert cell_level({E}) is CellLevel.MODIFY
    assert cell_level({R, D}) is CellLevel.DELETE


def test_operation_codes() -> None:
    assert parse_operations("Ч–РВ") == {R, E, D}
    assert parse_operations("–") == frozenset()
    assert parse_operations("") == frozenset()
    assert parse_operations("чзрв") == {R, W, E, D}
    assert operations_code({D, R}) == "ЧВ"
    assert operations_code(frozenset()) == "–"
    assert operations_cell({R, E, D}) == "Ч·РВ"
    assert operations_cell(frozenset()) == "····"
    with pytest.raises(ValueError, match="невідомий код операції"):
        parse_operations("ЧP")  # латинська «P» замість кириличної «Р»


def test_role_change_matrix(enterprise: Enterprise, initial: AccessModel, optimized: AccessModel) -> None:
    diff = diff_matrices(role_matrix(enterprise, initial), role_matrix(enterprise, optimized))
    cells = [cell for row in diff.values() for cell in row.values()]
    assert sum(len(cell.kept) for cell in cells) == 33
    assert sum(len(cell.removed) for cell in cells) == 34
    assert sum(len(cell.added) for cell in cells) == 0
    assert sum(1 for cell in cells if cell.changed) == 18
    assert diff["MANAGER"]["R2"].removed == {D}
    assert diff["MANAGER"]["R2"].kept == {R, W, E}


def test_optimized_is_subset(enterprise: Enterprise, initial: AccessModel, optimized: AccessModel) -> None:
    assert is_submatrix(user_matrix(enterprise, optimized), user_matrix(enterprise, initial))
    assert is_submatrix(role_matrix(enterprise, optimized), role_matrix(enterprise, initial))
    assert not is_submatrix(user_matrix(enterprise, initial), user_matrix(enterprise, optimized))


def test_what_if_role_edit_recalculates(enterprise: Enterprise, initial: AccessModel) -> None:
    edited = initial.with_role_operations("EMPLOYEE", "R1", {R, W, E})
    assert matrix_stats(role_matrix(enterprise, edited)).allowed == 66
    assert matrix_stats(user_matrix(enterprise, edited)).allowed == 316 - 11
    # Вихідна модель незмінна: редагування створює нову модель.
    assert initial.role_operations("EMPLOYEE", "R1") == {R, W, E, D}


def test_set_user_rights_changes_only_grants(enterprise: Enterprise, initial: AccessModel) -> None:
    granted = set_user_rights(enterprise, initial, "U06", "R2", {R, D}, "Перевірка")
    assert granted.grant_operations("U06", "R2") == {D}  # Ч уже є в ролі
    assert granted.grant("U06", "R2").reason == "Перевірка"

    revoked = set_user_rights(enterprise, initial, "U12", "R2", {R})
    assert revoked.grant("U12", "R2") is None
    assert effective_rights(enterprise, revoked, "U12")["R2"] == {R}

    kept = set_user_rights(enterprise, initial, "U07", "R2", {R, W})
    assert kept.grant("U07", "R2").operations == {W}
    assert kept.grant("U07", "R2").reason.startswith("Тимчасовий доступ")

    # Права ролі на рівні користувача не знімаються — їх змінюють у матриці ролей.
    unchanged = set_user_rights(enterprise, initial, "U06", "R1", frozenset())
    assert effective_rights(enterprise, unchanged, "U06")["R1"] == {R, W, E, D}
