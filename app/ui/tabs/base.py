"""Базова вкладка: отримує результат аналізу й оновлюється, лише коли видима."""

from __future__ import annotations

from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import QWidget

from app.services.analysis import AnalysisResult
from app.ui.state import ModelState


class ResultTab(QWidget):
    """Вкладка, що відображає AnalysisResult.

    Після кожної зміни моделі стан надсилає новий результат; видима вкладка
    оновлюється одразу, прихована — при наступному показі (без зайвих перерахунків).
    Нащадки реалізують метод refresh().
    """

    def __init__(self, state: ModelState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._result = state.result
        self._stale = True
        state.changed.connect(self._on_changed)

    @property
    def state(self) -> ModelState:
        """Стан застосунку (для змін моделі)."""
        return self._state

    @property
    def result(self) -> AnalysisResult:
        """Останній отриманий результат аналізу."""
        return self._result

    def refresh(self, result: AnalysisResult) -> None:
        """Оновлює вміст вкладки за результатом аналізу (реалізують нащадки)."""
        raise NotImplementedError

    def ensure_current(self) -> None:
        """Оновлює вкладку, якщо вона ще не показує останній результат."""
        if self._stale:
            self._stale = False
            self.refresh(self._result)

    def _on_changed(self, result: AnalysisResult) -> None:
        self._result = result
        self._stale = True
        if self.isVisible():
            self.ensure_current()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.ensure_current()
