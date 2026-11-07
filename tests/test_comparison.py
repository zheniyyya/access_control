"""Тести порівняльної таблиці, повного аналізу та автоматичних висновків."""

from __future__ import annotations

import pytest

from app.domain.models import Enterprise
from app.services.analysis import AnalysisResult, analyze
from app.services.comparison import ComparisonRow
from app.services.conclusions import conclusions_text
from app.services.formatting import (
    NBSP,
    count_phrase,
    fmt_number,
    fmt_percent,
    fmt_signed,
    join_and,
    round_half_up,
)
from app.services.optimizer import build_min_privilege_model


def _rows(result: AnalysisResult) -> dict[str, ComparisonRow]:
    return {row.key: row for row in result.comparison}


@pytest.mark.parametrize(
    ("key", "before", "after"),
    [
        ("roles.allowed", 67, 33),
        ("roles.denied", 29, 63),
        ("users.allowed", 316, 158),
        ("users.denied", 164, 322),
        ("grants.operations", 14, 0),
        ("roles.allowed.ADMIN", 24, 6),
        ("roles.allowed.GUEST", 5, 1),
        ("users.operation.READ", 113, 72),
        ("users.operation.DELETE", 56, 11),
        ("risk.R1", 498, 288),
        ("protection.R2", 62.0, 91.0),
        ("critical.risk", 726, 342),
        ("critical.protection", 39.5, 71.5),
        ("total.risk", 1538, 674),
        ("total.protection", 40.8, 74.1),
        ("access.R1", 20, 14),
        ("access.R2", 17, 3),
        ("delete.R1", 16, 3),
        ("delete.R2", 6, 0),
        ("violations.CRITICAL", 26, 0),
        ("violations.total", 75, 0),
    ],
)
def test_comparison_values(result: AnalysisResult, key: str, before: float, after: float) -> None:
    row = _rows(result)[key]
    assert (row.initial, row.optimized) == (before, after)


def test_comparison_changes(result: AnalysisResult) -> None:
    rows = _rows(result)
    allowed = rows["roles.allowed"]
    assert (allowed.change, allowed.change_percent, allowed.improved) == (-34, -50.7, True)
    assert allowed.change_text == "−34"
    assert allowed.change_percent_text == f"−50,7{NBSP}%"
    denied = rows["users.denied"]
    assert (denied.change, denied.change_percent, denied.improved) == (158, 96.3, True)
    protection = rows["total.protection"]
    assert protection.change == 33.3
    assert protection.initial_text == f"40,8{NBSP}%"
    assert protection.change_text.startswith("+33,3")
    assert rows["grants.operations"].change_percent == -100.0


def test_analysis_flags(result: AnalysisResult) -> None:
    assert result.is_subset
    assert result.uncovered == ()
    assert result.optimized.violations == ()
    assert result.risk_ranking[0].resource_id == "R1"
    assert len(result.findings) == 158
    assert len(result.grants) == 8
    assert sum(result.rule_counts.values()) >= len(result.findings)


def test_conclusions_contain_computed_numbers(result: AnalysisResult) -> None:
    text = conclusions_text(result.conclusions)
    fragments = [
        "дозволено 67 із 96 операцій",
        "зменшилася з 67 до 33 (−34; −50,7",
        "з 316 до 158",
        "158 надлишкових прав",
        "критичний — 26, високий — 46, середній — 3, низький — 83",
        f"з 17,0{NBSP}% до 52,0{NBSP}%",
        f"з 62,0{NBSP}% до 91,0{NBSP}%",
        "«Фінансова документація» (R2) зменшилася з 17 до 3",
        "усунених критичних знахідок — 26 із 26",
        "є ефективним",
        "11 користувачів ролі «Співробітник» зберігають права «ЧЗР»",
        "ABAC",
    ]
    for fragment in fragments:
        assert fragment in text, fragment


def test_conclusions_follow_what_if_changes(enterprise: Enterprise) -> None:
    # Забираємо в гостей читання бази клієнтів: доступ до R1 матимуть 17 користувачів
    # (U18 зберігає індивідуальний дозвіл «З»), і висновки мають це відобразити.
    model = enterprise.initial_model.with_role_operations("GUEST", "R1", set())
    edited = enterprise.with_initial_model(model)
    result = analyze(edited, build_min_privilege_model(edited))
    text = conclusions_text(result.conclusions)
    assert "«База даних клієнтів» (R1) — з 17 до 14" in text
    assert len(result.findings) == 154
    assert "158 надлишкових прав" not in text
    assert "154 надлишкові права" in text


def test_formatting_helpers() -> None:
    assert fmt_number(17) == "17"
    assert fmt_number(40.846, 1) == "40,8"
    assert fmt_number(-0.04, 1) == "0,0"
    assert fmt_percent(52) == f"52,0{NBSP}%"
    assert fmt_signed(35.0, 1) == "+35,0"
    assert fmt_signed(-34) == "−34"
    assert fmt_signed(0) == "0"
    assert round_half_up(2.675, 2) == 2.68
    assert count_phrase(1, "операція", "операції", "операцій") == "1 операція"
    assert count_phrase(3, "операція", "операції", "операцій") == "3 операції"
    assert count_phrase(11, "операція", "операції", "операцій") == "11 операцій"
    assert count_phrase(21, "операція", "операції", "операцій") == "21 операція"
    assert join_and(["A", "B", "C"]) == "A, B і C"
