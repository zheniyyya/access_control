"""Вкладка «Структурна схема»: Користувачі → Ролі → Ресурси для початкової чи оптимізованої моделі."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QWheelEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app import palette
from app.services.analysis import AnalysisResult
from app.ui.scheme import SchemeScene, export_png, export_svg
from app.ui.state import ModelState
from app.ui.tabs.base import ResultTab
from app.ui.widgets import show_status

ZOOM_STEP = 1.15
MIN_ZOOM = 0.2
MAX_ZOOM = 4.0
PNG_SCALE = 2.0


class SchemeView(QGraphicsView):
    """Перегляд схеми: масштаб коліщатком миші, прокрутка перетягуванням."""

    zoom_changed = Signal(int)  # поточний масштаб, %

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setBackgroundBrush(QColor(palette.SURFACE))
        self.setFrameShape(QFrame.Shape.NoFrame)

    def wheelEvent(self, event: QWheelEvent) -> None:
        steps = event.angleDelta().y() / 120.0
        if steps:
            self.zoom(ZOOM_STEP**steps)
        event.accept()

    def zoom(self, factor: float) -> None:
        """Змінює масштаб у factor разів у межах 20–400 %."""
        current = self.transform().m11()
        target = min(max(current * factor, MIN_ZOOM), MAX_ZOOM)
        if abs(target - current) > 1e-9:
            self.scale(target / current, target / current)
        self.zoom_changed.emit(round(self.transform().m11() * 100))

    def fit(self) -> None:
        """Вписує всю схему у вікно."""
        scene = self.scene()
        if scene is not None:
            self.fitInView(scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
            self.zoom_changed.emit(round(self.transform().m11() * 100))

    def actual_size(self) -> None:
        """Масштаб 100 %."""
        self.resetTransform()
        self.zoom_changed.emit(100)


class SchemeTab(ResultTab):
    """Структурна схема з перемикачем моделі, масштабуванням і експортом у PNG/SVG."""

    def __init__(self, state: ModelState, parent: QWidget | None = None) -> None:
        super().__init__(state, parent)
        self._view = SchemeView()
        self._scene: SchemeScene | None = None
        self._fitted = False
        self._initial = QRadioButton("Початкова модель")
        self._optimized = QRadioButton("Оптимізована модель")
        self._initial.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self._initial)
        group.addButton(self._optimized)
        self._initial.toggled.connect(self._on_model_switched)
        self._zoom_label = QLabel("100 %")
        self._zoom_label.setMinimumWidth(48)
        self._view.zoom_changed.connect(lambda percent: self._zoom_label.setText(f"{percent} %"))

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("Модель:"))
        toolbar.addWidget(self._initial)
        toolbar.addWidget(self._optimized)
        toolbar.addSpacing(24)
        for text, tooltip, handler in (
            ("−", "Зменшити", lambda: self._view.zoom(1 / ZOOM_STEP)),
            ("+", "Збільшити", lambda: self._view.zoom(ZOOM_STEP)),
            ("Вписати", "Показати всю схему", self._view.fit),
            ("100 %", "Справжній розмір", self._view.actual_size),
        ):
            button = QPushButton(text)
            button.setToolTip(tooltip)
            button.clicked.connect(handler)
            if len(text) == 1:
                button.setFixedWidth(32)
            toolbar.addWidget(button)
        toolbar.addWidget(self._zoom_label)
        help_button = QToolButton()
        help_button.setText("?")
        help_button.setToolTip(
            "Наведіть курсор на вузол — підсвітяться всі його зв'язки.\n"
            "Коліщатко миші — масштаб, перетягування — прокрутка."
        )
        toolbar.addWidget(help_button)
        toolbar.addStretch(1)
        png = QPushButton("PNG (2×)")
        png.setToolTip("Зберегти схему в PNG подвійної роздільності")
        png.clicked.connect(self._export_png)
        svg = QPushButton("SVG")
        svg.setToolTip("Зберегти схему у векторному форматі SVG")
        svg.clicked.connect(self._export_svg)
        toolbar.addWidget(QLabel("Експорт:"))
        toolbar.addWidget(png)
        toolbar.addWidget(svg)

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self._view, 1)

    @property
    def scene(self) -> SchemeScene | None:
        """Поточна сцена схеми."""
        return self._scene

    def refresh(self, result: AnalysisResult) -> None:
        model = result.optimized.model if self._optimized.isChecked() else result.initial.model
        scene = SchemeScene(result.enterprise, model)
        previous = self._scene
        self._view.setScene(scene)
        self._scene = scene
        if previous is not None:
            previous.deleteLater()
        if not self._fitted:
            self._fitted = True
            QTimer.singleShot(0, self._view.fit)

    def _on_model_switched(self, _checked: bool) -> None:
        self.refresh(self.result)

    def _default_path(self, suffix: str) -> str:
        which = "optimized" if self._optimized.isChecked() else "initial"
        documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        return str(Path(documents) / f"scheme_{which}.{suffix}")

    def _export_png(self) -> None:
        if self._scene is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Експорт схеми в PNG", self._default_path("png"), "Зображення PNG (*.png)"
        )
        if not path:
            return
        try:
            saved = export_png(self._scene, path, PNG_SCALE)
        except OSError as exc:
            QMessageBox.warning(self, "Помилка експорту", str(exc))
            return
        show_status(self, f"Схему збережено: {saved}")

    def _export_svg(self) -> None:
        if self._scene is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Експорт схеми в SVG", self._default_path("svg"), "Векторне зображення SVG (*.svg)"
        )
        if not path:
            return
        try:
            saved = export_svg(self._scene, path, f"Структурна схема — {self._scene.model_name}")
        except OSError as exc:
            QMessageBox.warning(self, "Помилка експорту", str(exc))
            return
        show_status(self, f"Схему збережено: {saved}")
