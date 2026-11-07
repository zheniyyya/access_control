"""Стан застосунку: поточна модель, оптимізована модель, результат аналізу та історія змін.

Усі зміни (редагування довідників, клітинок матриць, відкриття файлу) проходять
через ModelState: він перевіряє узгодженість, перераховує аналіз чистими
функціями сервісів і сповіщає вкладки сигналом changed. Стан належить головному
вікну — глобальних змінних немає.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from app.domain.models import AccessModel, Enterprise, Operation
from app.services.analysis import AnalysisResult, analyze
from app.services.matrix import set_user_rights as with_user_rights
from app.services.optimizer import build_min_privilege_model

HISTORY_LIMIT = 100


@dataclass(frozen=True)
class _Snapshot:
    """Знімок для скасування: модель підприємства й оптимізована модель."""

    enterprise: Enterprise
    optimized: AccessModel


class ModelState(QObject):
    """Поточна модель і результат її аналізу; підтримує «Скасувати / Повторити»."""

    changed = Signal(object)  # AnalysisResult — після кожної зміни моделі
    meta_changed = Signal()  # файл, ознака незбережених змін, доступність історії

    def __init__(
        self, enterprise: Enterprise, file_path: Path | None = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._enterprise = enterprise
        self._optimized = build_min_privilege_model(enterprise)
        self._result = analyze(enterprise, self._optimized)
        self._file_path = file_path
        self._dirty = False
        self._undo: list[_Snapshot] = []
        self._redo: list[_Snapshot] = []

    @property
    def enterprise(self) -> Enterprise:
        """Поточна модель підприємства (довідники + початкова модель доступу)."""
        return self._enterprise

    @property
    def optimized(self) -> AccessModel:
        """Поточна оптимізована модель (еталон мінімальних привілеїв)."""
        return self._optimized

    @property
    def result(self) -> AnalysisResult:
        """Результат аналізу поточного стану."""
        return self._result

    @property
    def file_path(self) -> Path | None:
        """Файл, з якого відкрито або в який збережено модель (None — вихідні дані)."""
        return self._file_path

    @property
    def is_dirty(self) -> bool:
        """Чи є незбережені зміни."""
        return self._dirty

    @property
    def can_undo(self) -> bool:
        """Чи можна скасувати останню зміну."""
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        """Чи можна повторити скасовану зміну."""
        return bool(self._redo)

    def load(self, enterprise: Enterprise, file_path: Path | None) -> None:
        """Завантажує нову модель: будує еталон, очищає історію, перераховує аналіз."""
        self._enterprise = enterprise
        self._optimized = build_min_privilege_model(enterprise)
        self._file_path = file_path
        self._dirty = False
        self._undo.clear()
        self._redo.clear()
        self._recompute()

    def apply(self, enterprise: Enterprise, optimized: AccessModel | None = None) -> list[str]:
        """Застосовує змінену модель; повертає перелік помилок (порожній — успіх)."""
        errors = enterprise.validate()
        if errors:
            return errors
        new_optimized = optimized if optimized is not None else self._optimized
        if enterprise == self._enterprise and new_optimized == self._optimized:
            return []
        self._undo.append(_Snapshot(self._enterprise, self._optimized))
        del self._undo[:-HISTORY_LIMIT]
        self._redo.clear()
        self._enterprise = enterprise
        self._optimized = new_optimized
        self._dirty = True
        self._recompute()
        return []

    def set_role_operations(
        self, role_id: str, resource_id: str, operations: Iterable[Operation]
    ) -> list[str]:
        """Змінює клітинку початкової матриці ролей («що буде, якщо»)."""
        model = self._enterprise.initial_model.with_role_operations(role_id, resource_id, operations)
        return self.apply(self._enterprise.with_initial_model(model))

    def set_user_rights(
        self,
        user_id: str,
        resource_id: str,
        operations: Iterable[Operation],
        reason: str,
    ) -> list[str]:
        """Задає ефективні права користувача на ресурсі через індивідуальний дозвіл."""
        model = with_user_rights(
            self._enterprise, self._enterprise.initial_model, user_id, resource_id, operations, reason
        )
        return self.apply(self._enterprise.with_initial_model(model))

    def undo(self) -> None:
        """Скасовує останню зміну."""
        if self._undo:
            self._redo.append(_Snapshot(self._enterprise, self._optimized))
            self._restore(self._undo.pop())

    def redo(self) -> None:
        """Повторює скасовану зміну."""
        if self._redo:
            self._undo.append(_Snapshot(self._enterprise, self._optimized))
            self._restore(self._redo.pop())

    def mark_saved(self, file_path: Path) -> None:
        """Позначає модель збереженою у файл."""
        self._file_path = file_path
        self._dirty = False
        self.meta_changed.emit()

    def _restore(self, snapshot: _Snapshot) -> None:
        self._enterprise = snapshot.enterprise
        self._optimized = snapshot.optimized
        self._dirty = True
        self._recompute()

    def _recompute(self) -> None:
        self._result = analyze(self._enterprise, self._optimized)
        self.changed.emit(self._result)
        self.meta_changed.emit()
