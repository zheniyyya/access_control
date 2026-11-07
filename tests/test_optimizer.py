"""Тести побудови моделі мінімальних привілеїв."""

from __future__ import annotations

from dataclasses import replace

from app.domain.models import (
    ALL_OPERATIONS,
    AccessModel,
    DutyFunction,
    Enterprise,
    Operation,
    parse_operations,
)
from app.services.matrix import is_submatrix, role_matrix, user_matrix
from app.services.optimizer import (
    build_min_privilege_model,
    function_count,
    justify_model,
    uncovered_functions,
)

R, W, E, D = Operation.READ, Operation.WRITE, Operation.EDIT, Operation.DELETE

EXPECTED_OPTIMIZED = {
    "ADMIN": {"R1": "–", "R2": "–", "R3": "–", "R4": "Ч", "R5": "Ч", "R6": "ЧЗРВ"},
    "MANAGER": {"R1": "ЧЗРВ", "R2": "ЧЗР", "R3": "ЧЗРВ", "R4": "ЧЗРВ", "R5": "Ч", "R6": "ЧЗ"},
    "EMPLOYEE": {"R1": "ЧЗР", "R2": "–", "R3": "ЧЗР", "R4": "Ч", "R5": "–", "R6": "Ч"},
    "GUEST": {"R1": "–", "R2": "–", "R3": "–", "R4": "–", "R5": "–", "R6": "Ч"},
}


def test_optimized_role_permissions(optimized: AccessModel) -> None:
    for role_id, row in EXPECTED_OPTIMIZED.items():
        for resource_id, code in row.items():
            assert optimized.role_operations(role_id, resource_id) == parse_operations(code), (
                role_id,
                resource_id,
            )


def test_no_individual_grants(optimized: AccessModel) -> None:
    assert optimized.user_grants == {}
    assert optimized.grant_operation_count == 0


def test_optimized_is_subset_of_initial(
    enterprise: Enterprise, initial: AccessModel, optimized: AccessModel
) -> None:
    assert is_submatrix(role_matrix(enterprise, optimized), role_matrix(enterprise, initial))
    assert is_submatrix(user_matrix(enterprise, optimized), user_matrix(enterprise, initial))


def test_all_functions_covered(enterprise: Enterprise, optimized: AccessModel) -> None:
    assert function_count(enterprise) == 14
    assert uncovered_functions(enterprise, optimized) == []


def test_uncovered_function_detected(enterprise: Enterprise, optimized: AccessModel) -> None:
    reduced = optimized.with_role_operations("EMPLOYEE", "R1", {R})
    uncovered = uncovered_functions(enterprise, reduced)
    assert [(role.id, function.name) for role, function in uncovered] == [
        ("EMPLOYEE", "Обслуговування клієнтів")
    ]


def test_justification(enterprise: Enterprise, initial: AccessModel, optimized: AccessModel) -> None:
    rows = {(row.role_id, row.resource_id): row for row in justify_model(enterprise, initial, optimized)}
    assert len(rows) == 24

    admin_r1 = rows[("ADMIN", "R1")]
    assert admin_r1.removed == ALL_OPERATIONS
    assert admin_r1.optimized == frozenset()
    assert admin_r1.rule_codes == ("П4",)
    assert admin_r1.text.startswith("Доступ скасовано")

    manager_r2 = rows[("MANAGER", "R2")]
    assert manager_r2.removed == {D}
    assert manager_r2.rule_codes == ("П3",)
    assert manager_r2.functions[0].startswith("Підготовка й погодження фінансових документів")

    employee_r1 = rows[("EMPLOYEE", "R1")]
    assert employee_r1.optimized == {R, W, E}
    assert employee_r1.rule_codes == ("П6",)
    assert employee_r1.functions == ("Обслуговування клієнтів",)

    assert rows[("ADMIN", "R3")].rule_codes == ("П9",)
    assert rows[("ADMIN", "R5")].rule_codes == ("П2",)
    assert rows[("MANAGER", "R1")].removed == frozenset()
    assert rows[("GUEST", "R2")].text.startswith("Доступу немає")


def test_edited_functions_change_model(enterprise: Enterprise) -> None:
    guest = enterprise.role("GUEST")
    extended = replace(
        guest,
        functions=guest.functions + (DutyFunction("Перегляд проєктних матеріалів", "R3", frozenset({R})),),
    )
    model = build_min_privilege_model(enterprise.with_role(extended))
    assert model.role_operations("GUEST", "R3") == {R}
    assert model.role_operations("GUEST", "R6") == {R}
