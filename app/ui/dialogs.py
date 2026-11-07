"""Діалоги: редагування клітинки матриці (чотири прапорці) та незбережені зміни."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import Enum

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from app import palette
from app.domain.models import NO_OPERATIONS, Operation, OperationSet, operations_cell
from app.services.matrix import cell_level
from app.ui.widgets import hint_label


class OperationsDialog(QDialog):
    """Редагування клітинки матриці: чотири прапорці «Ч», «З», «Р», «В».

    locked — операції, які не можна зняти тут (напр. надані роллю в матриці
    користувачів); reason — поле причини індивідуального дозволу (None — без поля).
    """

    def __init__(
        self,
        title: str,
        subtitle: str,
        current: OperationSet,
        *,
        locked: OperationSet = NO_OPERATIONS,
        locked_hint: str = "",
        hints: Mapping[Operation, str] | None = None,
        reason: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Зміна прав доступу")
        self.setMinimumWidth(560)
        self._locked = locked
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setWordWrap(True)
        font = heading.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() + 1)
        heading.setFont(font)
        layout.addWidget(heading)
        if subtitle:
            layout.addWidget(hint_label(subtitle))
        notes = hints or {}
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(6)
        self._boxes: dict[Operation, QCheckBox] = {}
        for row, operation in enumerate(Operation):
            box = QCheckBox(f"{operation.short} — {operation.label}")
            box.setToolTip(operation.description)
            box.setChecked(operation in current or operation in locked)
            note = notes.get(operation, "")
            if operation in locked:
                box.setEnabled(False)
                note = locked_hint
            box.toggled.connect(self._update_preview)
            grid.addWidget(box, row, 0)
            grid.addWidget(hint_label(note), row, 1)
            self._boxes[operation] = box
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        self._reason: QLineEdit | None = None
        if reason is not None:
            form = QFormLayout()
            self._reason = QLineEdit(reason)
            self._reason.setPlaceholderText("Підстава для індивідуального дозволу")
            form.addRow("Причина надання:", self._reason)
            layout.addLayout(form)
        self._preview = QLabel()
        self._preview.setMargin(6)
        layout.addWidget(self._preview)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Застосувати")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Скасувати")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_preview()

    def selected_operations(self) -> OperationSet:
        """Операції, позначені прапорцями (разом із заблокованими)."""
        return frozenset(operation for operation, box in self._boxes.items() if box.isChecked())

    def set_operations(self, operations: Iterable[Operation]) -> None:
        """Встановлює прапорці доступних операцій (заблоковані не змінюються)."""
        wanted = set(operations)
        for operation, box in self._boxes.items():
            if box.isEnabled():
                box.setChecked(operation in wanted)

    def reason(self) -> str:
        """Причина індивідуального дозволу (порожньо, якщо поля немає)."""
        return self._reason.text().strip() if self._reason is not None else ""

    def _update_preview(self, *_args: object) -> None:
        operations = self.selected_operations()
        level = cell_level(operations)
        self._preview.setText(
            f"Результат: <b>{operations_cell(operations)}</b> — {level.value.lower()}"
        )
        self._preview.setStyleSheet(
            f"background: {palette.CELL_FILL[level]}; border: 1px solid {palette.CELL_STROKE[level]};"
            " border-radius: 4px;"
        )
        if self._reason is not None:
            self._reason.setEnabled(bool(operations - self._locked))


class UnsavedChoice(Enum):
    """Відповідь на запит про незбережені зміни."""

    SAVE = "save"
    DISCARD = "discard"
    CANCEL = "cancel"


def ask_unsaved_changes(parent: QWidget, action: str) -> UnsavedChoice:
    """Питає, чи зберегти зміни перед дією action («закрити програму» тощо)."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Незбережені зміни")
    box.setText("Модель містить незбережені зміни.")
    box.setInformativeText(f"Зберегти їх, перш ніж {action}?")
    save = box.addButton("Зберегти", QMessageBox.ButtonRole.AcceptRole)
    discard = box.addButton("Не зберігати", QMessageBox.ButtonRole.DestructiveRole)
    box.addButton("Скасувати", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(save)
    box.exec()
    clicked = box.clickedButton()
    if clicked == save:
        return UnsavedChoice.SAVE
    if clicked == discard:
        return UnsavedChoice.DISCARD
    return UnsavedChoice.CANCEL
