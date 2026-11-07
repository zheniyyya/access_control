"""Тести діаграм matplotlib: побудова без Qt і збереження в PNG."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.export.charts import (
    CHARTS,
    heatmaps_figure,
    protection_figure,
    role_operations_figure,
    save_figure,
)
from app.services.analysis import AnalysisResult
from app.services.formatting import fmt_percent


def _texts(figure) -> list[str]:  # type: ignore[no-untyped-def]
    return [text.get_text() for axes in figure.axes for text in axes.texts]


@pytest.mark.parametrize("spec", CHARTS, ids=lambda spec: spec.file_stem)
def test_chart_saves_png(spec, result: AnalysisResult, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / f"{spec.file_stem}.png"
    save_figure(spec.build(result), path, dpi=80)
    assert path.stat().st_size > 10_000
    assert spec.caption


def test_role_operations_labels(result: AnalysisResult) -> None:
    texts = _texts(role_operations_figure(result))
    # Початкова / оптимізована: 24/6, 23/18, 15/8, 5/1.
    for value in ("24", "6", "23", "18", "15", "8", "5", "1"):
        assert value in texts


def test_protection_labels(result: AnalysisResult) -> None:
    texts = _texts(protection_figure(result))
    for value in (17.0, 52.0, 62.0, 91.0, 69.0, 97.5):
        assert fmt_percent(value) in texts


def test_heatmaps_cells(result: AnalysisResult) -> None:
    figure = heatmaps_figure(result)
    left, right = figure.axes[:2]
    users, resources = len(result.enterprise.users), len(result.enterprise.resources)
    assert len(left.texts) == len(right.texts) == users * resources
    assert "316" in left.get_title(loc="left") and "158" in right.get_title(loc="left")
