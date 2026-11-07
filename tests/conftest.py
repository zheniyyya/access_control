"""Спільні фікстури тестів: вихідні дані варіанту №7 і модель мінімальних привілеїв."""

from __future__ import annotations

import pytest

from app.domain.models import AccessModel, Enterprise
from app.domain.seed import load_variant7
from app.services.analysis import AnalysisResult, analyze
from app.services.optimizer import build_min_privilege_model


@pytest.fixture(scope="session")
def enterprise() -> Enterprise:
    """Вихідні дані варіанту №7 з data/variant7.json."""
    return load_variant7()


@pytest.fixture(scope="session")
def initial(enterprise: Enterprise) -> AccessModel:
    """Початкова модель доступу."""
    return enterprise.initial_model


@pytest.fixture(scope="session")
def optimized(enterprise: Enterprise) -> AccessModel:
    """Оптимізована модель (мінімальні привілеї)."""
    return build_min_privilege_model(enterprise)


@pytest.fixture(scope="session")
def result(enterprise: Enterprise, optimized: AccessModel) -> AnalysisResult:
    """Повний аналіз початкової моделі відносно оптимізованої."""
    return analyze(enterprise, optimized)
