"""Індекс ризику та рівень захищеності інформаційних ресурсів.

Ризик(r) = K(r) × Σ по всіх користувачах Σ ваг дозволених операцій на r;
Max(r)   = N × 10 × K(r), де N — кількість користувачів (20), 10 — сума ваг Ч+З+Р+В;
Z(r)     = (1 − Ризик(r) / Max(r)) × 100 %, округлення до 0,1.
Оцінка: Z ≥ 80 % — високий рівень, 50–80 % — середній, < 50 % — низький.
Агреговані показники: сума ризиків / сума максимумів.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from enum import Enum

from app.domain.models import (
    MODIFYING_OPERATIONS,
    TOTAL_WEIGHT,
    AccessModel,
    Enterprise,
    Operation,
    Resource,
    operations_weight,
)
from app.services.formatting import percent
from app.services.matrix import user_matrix

HIGH_PROTECTION = 80.0
MEDIUM_PROTECTION = 50.0


class ProtectionLevel(Enum):
    """Оцінка рівня захищеності; rank — для порівняння (більше — краще)."""

    label: str
    rank: int

    HIGH = ("Високий", 3)
    MEDIUM = ("Середній", 2)
    LOW = ("Низький", 1)

    def __init__(self, label: str, rank: int) -> None:
        self.label = label
        self.rank = rank


@dataclass(frozen=True)
class ResourceRisk:
    """Ризик і захищеність одного ресурсу та охоплення його користувачами."""

    resource_id: str
    resource_name: str
    criticality: int
    critical: bool
    weight_sum: int  # Σ ваг дозволених операцій усіх користувачів
    risk: int
    max_risk: int
    protection: float  # Z, %
    level: ProtectionLevel
    users_any: int  # користувачі з будь-яким доступом
    users_modify: int  # користувачі з модифікуючим доступом (З/Р/В)
    users_delete: int  # користувачі з правом видалення


@dataclass(frozen=True)
class AggregateRisk:
    """Агрегований ризик групи ресурсів (сума ризиків / сума максимумів)."""

    title: str
    resource_ids: tuple[str, ...]
    risk: int
    max_risk: int
    protection: float
    level: ProtectionLevel


def protection_level(protection: float) -> ProtectionLevel:
    """Оцінка за рівнем захищеності: ≥ 80 — високий, ≥ 50 — середній, інакше — низький."""
    if protection >= HIGH_PROTECTION:
        return ProtectionLevel.HIGH
    if protection >= MEDIUM_PROTECTION:
        return ProtectionLevel.MEDIUM
    return ProtectionLevel.LOW


def max_risk(enterprise: Enterprise, resource: Resource) -> int:
    """Максимальний ризик ресурсу — якби кожен користувач мав усі операції."""
    return len(enterprise.users) * TOTAL_WEIGHT * resource.criticality


def protection_percent(risk: int, maximum: int) -> float:
    """Рівень захищеності Z = (1 − ризик / максимум) × 100 %, округлений до 0,1."""
    if maximum <= 0:
        return 100.0
    return percent(maximum - risk, maximum)


def resource_risks(enterprise: Enterprise, model: AccessModel) -> list[ResourceRisk]:
    """Ризик, захищеність і охоплення користувачами для кожного ресурсу моделі."""
    users = user_matrix(enterprise, model)
    risks: list[ResourceRisk] = []
    for resource in enterprise.resources:
        cells = [row[resource.id] for row in users.values()]
        weight_sum = sum(operations_weight(cell) for cell in cells)
        risk = resource.criticality * weight_sum
        maximum = max_risk(enterprise, resource)
        protection = protection_percent(risk, maximum)
        risks.append(
            ResourceRisk(
                resource_id=resource.id,
                resource_name=resource.name,
                criticality=resource.criticality,
                critical=resource.critical,
                weight_sum=weight_sum,
                risk=risk,
                max_risk=maximum,
                protection=protection,
                level=protection_level(protection),
                users_any=sum(1 for cell in cells if cell),
                users_modify=sum(1 for cell in cells if cell & MODIFYING_OPERATIONS),
                users_delete=sum(1 for cell in cells if Operation.DELETE in cell),
            )
        )
    return risks


def aggregate_risk(
    risks: Iterable[ResourceRisk],
    title: str,
    resource_ids: Collection[str] | None = None,
) -> AggregateRisk:
    """Агрегований ризик ресурсів (усіх або лише вказаних)."""
    selected = [
        item for item in risks if resource_ids is None or item.resource_id in resource_ids
    ]
    total = sum(item.risk for item in selected)
    maximum = sum(item.max_risk for item in selected)
    protection = protection_percent(total, maximum)
    return AggregateRisk(
        title=title,
        resource_ids=tuple(item.resource_id for item in selected),
        risk=total,
        max_risk=maximum,
        protection=protection,
        level=protection_level(protection),
    )


def critical_risk(enterprise: Enterprise, risks: Iterable[ResourceRisk]) -> AggregateRisk:
    """Агрегований ризик критичних ресурсів (для варіанту 7 — R1 + R2)."""
    ids = [resource.id for resource in enterprise.critical_resources()]
    title = f"Критичні ресурси ({' + '.join(ids)})" if ids else "Критичні ресурси"
    return aggregate_risk(risks, title, ids)


def overall_risk(risks: Iterable[ResourceRisk]) -> AggregateRisk:
    """Агрегований ризик усіх ресурсів."""
    return aggregate_risk(risks, "Усі ресурси")


def rank_by_risk(risks: Iterable[ResourceRisk]) -> list[ResourceRisk]:
    """Рейтинг ресурсів за спаданням індексу ризику."""
    return sorted(risks, key=lambda item: (-item.risk, item.protection, item.resource_id))
