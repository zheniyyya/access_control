"""Діаграми matplotlib: ті самі фігури для GUI (FigureCanvasQTAgg) і для експорту в PNG.

Використовується об'єктний API (matplotlib.figure.Figure) без pyplot, тобто без
глобального стану. Шрифт — DejaVu Sans (постачається з matplotlib, має кирилицю);
кольори — з app.palette, однакові в застосунку та у звітах.
"""

from __future__ import annotations

import textwrap
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from matplotlib.artist import Artist
from matplotlib.axes import Axes
from matplotlib.colors import to_rgb
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from app import palette
from app.domain.models import Operation, operations_cell
from app.services.analysis import AnalysisResult
from app.services.comparison import ModelMetrics
from app.services.formatting import fmt_percent
from app.services.matrix import CellLevel, cell_level
from app.services.risk import HIGH_PROTECTION, MEDIUM_PROTECTION, ProtectionLevel

FONT_FAMILY = "DejaVu Sans"
MONO_FAMILY = "DejaVu Sans Mono"
EXPORT_DPI = 200
BAR_WIDTH = 0.32
THRESHOLD_STYLE = (0, (4, 3))


def new_figure(width: float = 8.0, height: float = 4.8) -> Figure:
    """Порожня фігура в стилі застосунку (розміри — у дюймах)."""
    return Figure(figsize=(width, height), dpi=100, facecolor=palette.SURFACE, layout="constrained")


def style_axes(axes: Axes, grid_axis: Literal["both", "x", "y"] = "y") -> None:
    """Стримане оформлення осей: тонкі світлі лінії сітки, без верхньої та правої рамки."""
    axes.set_facecolor(palette.SURFACE)
    for side in ("top", "right"):
        axes.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        axes.spines[side].set_color(palette.AXIS)
        axes.spines[side].set_linewidth(0.8)
    axes.tick_params(
        length=0, labelsize=9, labelcolor=palette.INK_SECONDARY, labelfontfamily=FONT_FAMILY
    )
    axes.grid(axis=grid_axis, color=palette.GRIDLINE, linewidth=0.8)
    axes.set_axisbelow(True)


def set_titles(figure: Figure, axes: Axes, title: str, subtitle: str = "") -> None:
    """Заголовок фігури (жирний, ліворуч) і підзаголовок над областю побудови."""
    figure.suptitle(
        title, x=0.01, ha="left", fontsize=12, fontweight="bold",
        color=palette.INK, fontfamily=FONT_FAMILY,
    )
    if subtitle:
        axes.set_title(
            subtitle, loc="left", fontsize=9, color=palette.INK_SECONDARY, fontfamily=FONT_FAMILY
        )


def axis_label(axes: Axes, text: str, axis: str = "y") -> None:
    """Підпис осі приглушеним кольором."""
    setter = axes.set_ylabel if axis == "y" else axes.set_xlabel
    setter(text, fontsize=9, color=palette.INK_SECONDARY, fontfamily=FONT_FAMILY)


def wrap_label(text: str, width: int = 11) -> str:
    """Переносить довгий підпис на кілька рядків, не розриваючи слів."""
    return "\n".join(textwrap.wrap(text, width, break_long_words=False)) or text


def legend_below(figure: Figure, handles: Sequence[Artist], columns: int = 2) -> None:
    """Легенда під областю побудови — не перекриває стовпчики."""
    figure.legend(
        handles=handles, loc="outside lower center", ncols=columns, frameon=False,
        prop={"family": FONT_FAMILY, "size": 8.5}, labelcolor=palette.INK_SECONDARY,
    )


def risk_figure(result: AnalysisResult) -> Figure:
    """Стовпчикова діаграма індексу ризику ресурсів початкової моделі.

    Сіра «доріжка» — максимально можливий ризик ресурсу, колір стовпчика —
    рівень захищеності (з підписом), над стовпчиком — індекс ризику та Z.
    """
    risks = result.initial.risks
    figure = new_figure()
    axes = figure.add_subplot()
    style_axes(axes)
    positions = list(range(len(risks)))
    axes.bar(positions, [item.max_risk for item in risks], BAR_WIDTH, color=palette.TRACK, zorder=1)
    axes.bar(
        positions,
        [item.risk for item in risks],
        BAR_WIDTH,
        color=[palette.PROTECTION_STROKE[item.level] for item in risks],
        zorder=2,
    )
    for position, item in zip(positions, risks):
        axes.annotate(
            f"{item.risk}\nZ = {fmt_percent(item.protection)}",
            xy=(position, item.risk),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8.5,
            color=palette.INK,
            fontfamily=FONT_FAMILY,
            zorder=3,
        )
    axes.set_xticks(
        positions,
        [f"{item.resource_id} · K={item.criticality}\n{wrap_label(item.resource_name)}" for item in risks],
    )
    axes.tick_params(axis="x", labelsize=8.5)
    top = max((item.max_risk for item in risks), default=1)
    axes.set_ylim(0, top * 1.14)
    axis_label(axes, "Індекс ризику")
    low, medium = fmt_percent(MEDIUM_PROTECTION, 0), fmt_percent(HIGH_PROTECTION, 0)
    legend_below(
        figure,
        [
            Patch(color=palette.PROTECTION_STROKE[ProtectionLevel.LOW], label=f"низька захищеність (Z < {low})"),
            Patch(color=palette.PROTECTION_STROKE[ProtectionLevel.MEDIUM], label=f"середня ({low} ≤ Z < {medium})"),
            Patch(color=palette.PROTECTION_STROKE[ProtectionLevel.HIGH], label=f"висока (Z ≥ {medium})"),
            Patch(color=palette.TRACK, label="максимально можливий ризик"),
        ],
    )
    set_titles(
        figure,
        axes,
        "Індекс ризику інформаційних ресурсів",
        f"{result.initial.model.name} · Ризик = K × Σ ваг дозволених операцій користувачів",
    )
    return figure


def _bar_labels(axes: Axes, positions: list[float], values: list[float], texts: list[str]) -> None:
    """Підписи значень над стовпчиками (колір тексту — «чорнило», не колір серії)."""
    for position, value, text in zip(positions, values, texts):
        axes.annotate(
            text,
            xy=(position, value),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8,
            color=palette.INK,
            fontfamily=FONT_FAMILY,
            zorder=3,
        )


def _paired_positions(count: int) -> tuple[list[int], list[float], list[float]]:
    """Позиції груп і двох стовпчиків у кожній (з проміжком між ними)."""
    positions = list(range(count))
    offset = BAR_WIDTH / 2 + 0.02
    return positions, [x - offset for x in positions], [x + offset for x in positions]


def _before_after_handles(result: AnalysisResult) -> list[Patch]:
    """Легенда «Початкова / Оптимізована» (короткі підписи — вміщуються й у вузькому полотні)."""
    return [
        Patch(color=palette.BEFORE, label="Початкова модель"),
        Patch(color=palette.AFTER, label="Оптимізована модель"),
    ]


def role_operations_figure(result: AnalysisResult) -> Figure:
    """Дозволені операції за ролями (матриця ролей) до та після оптимізації.

    Сіра «доріжка» — максимально можлива кількість операцій ролі
    (кількість ресурсів × 4).
    """
    enterprise = result.enterprise
    roles = enterprise.roles
    maximum = len(enterprise.resources) * len(Operation)
    before = [result.initial.allowed_by_role[role.id] for role in roles]
    after = [result.optimized.allowed_by_role[role.id] for role in roles]
    figure = new_figure()
    axes = figure.add_subplot()
    style_axes(axes)
    positions, left, right = _paired_positions(len(roles))
    axes.bar(positions, [maximum] * len(roles), BAR_WIDTH * 2 + 0.16, color=palette.TRACK, zorder=1)
    axes.bar(left, before, BAR_WIDTH, color=palette.BEFORE, zorder=2)
    axes.bar(right, after, BAR_WIDTH, color=palette.AFTER, zorder=2)
    _bar_labels(axes, left, before, [str(value) for value in before])
    _bar_labels(axes, right, after, [str(value) for value in after])
    axes.set_xticks(
        positions,
        [f"{role.name}\n({len(enterprise.users_of_role(role.id))} корист.)" for role in roles],
    )
    axes.set_ylim(0, max(maximum, 1) * 1.12)
    axis_label(axes, "Дозволених операцій")
    legend_below(
        figure,
        _before_after_handles(result) + [Patch(color=palette.TRACK, label=f"максимум ({maximum})")],
        columns=3,
    )
    stats_before, stats_after = result.initial.role_stats, result.optimized.role_stats
    set_titles(
        figure,
        axes,
        "Дозволені операції за ролями",
        f"Матриця ролей · разом {stats_before.allowed} → {stats_after.allowed} із {stats_before.total}",
    )
    return figure


def protection_figure(result: AnalysisResult) -> Figure:
    """Рівень захищеності ресурсів Z до та після оптимізації з порогами оцінок."""
    before_risks, after_risks = result.initial.risks, result.optimized.risks
    figure = new_figure()
    axes = figure.add_subplot()
    style_axes(axes)
    positions, left, right = _paired_positions(len(before_risks))
    before = [item.protection for item in before_risks]
    after = [item.protection for item in after_risks]
    for threshold in (MEDIUM_PROTECTION, HIGH_PROTECTION):
        axes.axhline(threshold, color=palette.INK_MUTED, linewidth=0.9, linestyle=THRESHOLD_STYLE, zorder=1)
    axes.bar(left, before, BAR_WIDTH, color=palette.BEFORE, zorder=2)
    axes.bar(right, after, BAR_WIDTH, color=palette.AFTER, zorder=2)
    _bar_labels(axes, left, before, [fmt_percent(value) for value in before])
    _bar_labels(axes, right, after, [fmt_percent(value) for value in after])
    axes.set_xticks(
        positions,
        [f"{item.resource_id} · K={item.criticality}\n{wrap_label(item.resource_name)}" for item in before_risks],
    )
    axes.tick_params(axis="x", labelsize=8.5)
    axes.set_ylim(0, 112)
    axes.set_yticks([0, 20, 40, 60, 80, 100], [fmt_percent(value, 0) for value in (0, 20, 40, 60, 80, 100)])
    axis_label(axes, "Рівень захищеності Z")
    thresholds = Line2D(
        [], [], color=palette.INK_MUTED, linewidth=0.9, linestyle=THRESHOLD_STYLE,
        label=f"пороги оцінки: середній — {fmt_percent(MEDIUM_PROTECTION, 0)}, "
        f"високий — {fmt_percent(HIGH_PROTECTION, 0)}",
    )
    legend_below(figure, [*_before_after_handles(result), thresholds], columns=2)
    set_titles(
        figure,
        axes,
        "Рівень захищеності ресурсів",
        f"Усі ресурси: {fmt_percent(result.initial.overall.protection)} → "
        f"{fmt_percent(result.optimized.overall.protection)} · критичні: "
        f"{fmt_percent(result.initial.critical.protection)} → "
        f"{fmt_percent(result.optimized.critical.protection)}",
    )
    return figure


def _heatmap(axes: Axes, result: AnalysisResult, metrics: ModelMetrics, title: str, show_users: bool) -> None:
    """Теплова карта матриці користувачів: колір — рівень клітинки, текст — «ЧЗРВ»."""
    enterprise = result.enterprise
    users, resources = enterprise.users, enterprise.resources
    image = [
        [to_rgb(palette.CELL_FILL[cell_level(metrics.user_matrix[user.id][resource.id])]) for resource in resources]
        for user in users
    ]
    axes.imshow(image, aspect="auto", interpolation="nearest")
    for row, user in enumerate(users):
        for column, resource in enumerate(resources):
            operations = metrics.user_matrix[user.id][resource.id]
            axes.text(
                column, row, operations_cell(operations), ha="center", va="center",
                fontsize=7.5, fontfamily=MONO_FAMILY, fontweight="bold",
                color=palette.INK if operations else palette.INK_MUTED,
            )
    # Проміжки кольору поверхні між клітинками.
    for row in range(len(users) + 1):
        axes.axhline(row - 0.5, color=palette.SURFACE, linewidth=1.5)
    for column in range(len(resources) + 1):
        axes.axvline(column - 0.5, color=palette.SURFACE, linewidth=1.5)
    for side in axes.spines.values():
        side.set_visible(False)
    axes.tick_params(length=0, labelsize=8, labelcolor=palette.INK_SECONDARY, labelfontfamily=FONT_FAMILY)
    axes.set_xticks(
        range(len(resources)),
        [f"{resource.id}*" if resource.critical else resource.id for resource in resources],
    )
    axes.xaxis.tick_top()
    if show_users:
        axes.set_yticks(
            range(len(users)), [f"{user.id} · {enterprise.role(user.role_id).name}" for user in users]
        )
    stats = metrics.user_stats
    axes.set_title(
        f"{title}: {stats.allowed} із {stats.total}",
        loc="left", fontsize=9.5, color=palette.INK, fontfamily=FONT_FAMILY, pad=8,
    )


def heatmaps_figure(result: AnalysisResult) -> Figure:
    """Теплові карти матриць користувачів початкової та оптимізованої моделей."""
    figure = new_figure(10.5, 7.8)
    left, right = figure.subplots(1, 2, sharey=True)
    _heatmap(left, result, result.initial, "Початкова", show_users=True)
    _heatmap(right, result, result.optimized, "Оптимізована", show_users=False)
    right.tick_params(axis="y", labelleft=False)
    critical = ", ".join(resource.id for resource in result.enterprise.critical_resources())
    legend_below(
        figure,
        [
            *(
                Patch(facecolor=palette.CELL_FILL[level], edgecolor=palette.CELL_STROKE[level], label=level.value.lower())
                for level in CellLevel
            ),
            Patch(facecolor="none", edgecolor="none", label=f"* — критичні ресурси ({critical})"),
        ],
        columns=3,
    )
    figure.suptitle(
        "Теплові карти матриць доступу користувачів",
        x=0.01, ha="left", fontsize=12, fontweight="bold", color=palette.INK, fontfamily=FONT_FAMILY,
    )
    return figure


@dataclass(frozen=True)
class ChartSpec:
    """Діаграма для GUI та експорту: ім'я файлу, підпис рисунка, побудова фігури."""

    file_stem: str
    caption: str
    build: Callable[[AnalysisResult], Figure]


CHARTS: tuple[ChartSpec, ...] = (
    ChartSpec("risk_index", "Індекс ризику інформаційних ресурсів (початкова модель)", risk_figure),
    ChartSpec("role_operations", "Дозволені операції за ролями до та після оптимізації", role_operations_figure),
    ChartSpec("protection", "Рівень захищеності ресурсів до та після оптимізації", protection_figure),
    ChartSpec("heatmaps", "Теплові карти матриць доступу користувачів", heatmaps_figure),
)


def save_figure(figure: Figure, path: str | Path, dpi: int = EXPORT_DPI) -> None:
    """Зберігає фігуру у файл (формат — за розширенням) з тлом поверхні застосунку."""
    figure.savefig(path, dpi=dpi, facecolor=figure.get_facecolor())
