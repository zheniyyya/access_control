"""Експорт, що потребує Qt: зображення структурних схем і збереження всіх рисунків у теку.

Звіти Excel і Word будують модулі app.export (без Qt); GUI лише передає їм
PNG структурних схем, намальованих тим самим кодом, що й вкладка «Структурна схема».
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice

from app.domain.models import AccessModel, Enterprise
from app.export.charts import CHARTS, save_figure
from app.export.word_report import SCHEME_INITIAL, SCHEME_OPTIMIZED
from app.services.analysis import AnalysisResult
from app.ui.scheme import SchemeScene, export_png, export_svg, render_image

SCHEME_SCALE = 2.0
SCHEME_FILES = {SCHEME_INITIAL: "scheme_initial", SCHEME_OPTIMIZED: "scheme_optimized"}


def _scheme_models(result: AnalysisResult) -> dict[str, AccessModel]:
    return {SCHEME_INITIAL: result.initial.model, SCHEME_OPTIMIZED: result.optimized.model}


def scheme_png(enterprise: Enterprise, model: AccessModel, scale: float = SCHEME_SCALE) -> bytes:
    """PNG структурної схеми моделі (удвічі більша роздільність) у пам'яті."""
    scene = SchemeScene(enterprise, model)
    try:
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        if not render_image(scene, scale).save(buffer, "PNG"):
            raise OSError("Не вдалося сформувати зображення структурної схеми.")
        buffer.close()
        return bytes(data.data())
    finally:
        scene.deleteLater()


def scheme_images(result: AnalysisResult) -> dict[str, bytes]:
    """PNG структурних схем початкової та оптимізованої моделей для звіту Word."""
    return {key: scheme_png(result.enterprise, model) for key, model in _scheme_models(result).items()}


def save_all_figures(result: AnalysisResult, folder: str | Path) -> list[Path]:
    """Зберігає в теку всі діаграми (PNG) і структурні схеми (PNG 2× та SVG); повертає шляхи."""
    target = Path(folder)
    target.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for spec in CHARTS:
        path = target / f"{spec.file_stem}.png"
        save_figure(spec.build(result), path)
        saved.append(path)
    for key, model in _scheme_models(result).items():
        scene = SchemeScene(result.enterprise, model)
        try:
            saved.append(export_png(scene, target / f"{SCHEME_FILES[key]}.png", SCHEME_SCALE))
            saved.append(export_svg(scene, target / f"{SCHEME_FILES[key]}.svg", f"Структурна схема — {model.name}"))
        finally:
            scene.deleteLater()
    return saved
