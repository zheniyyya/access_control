"""Вкладка «Моделювання»: перевірка запиту доступу та сценарій компрометації облікового запису.

Обидва сценарії виконуються одночасно для початкової та оптимізованої моделей,
щоб наочно показати дію принципу мінімальних привілеїв.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app import palette
from app.domain.models import AccessModel, Enterprise, Operation, OperationSet, operations_code, operations_weight
from app.services.analysis import AnalysisResult
from app.services.analyzer import find_finding
from app.services.formatting import fmt_percent, fmt_signed_percent, percent
from app.services.matrix import cell_level
from app.services.simulation import (
    CHANGING_OPERATIONS,
    AccessDecision,
    CompromiseImpact,
    check_access,
    simulate_compromise,
)
from app.ui.state import ModelState
from app.ui.table_models import CENTER, Column, RecordTableModel
from app.ui.tabs.base import ResultTab
from app.ui.widgets import fill_combo, make_table, section

DEFAULT_REQUEST = ("U20", "R2", Operation.READ.name)  # стажер читає фінансову документацію
DEFAULT_COMPROMISED = "U12"  # аналітик з успадкованими правами бухгалтерії


@dataclass(frozen=True)
class _ImpactRow:
    """Рядок «радіусу ураження»: ресурс і доступні зловмиснику операції."""

    resource_id: str
    name: str
    criticality: int
    critical: bool
    operations: OperationSet

    @property
    def risk(self) -> int:
        """Внесок ресурсу в ризик облікового запису: K × Σ ваг операцій."""
        return self.criticality * operations_weight(self.operations)

    @property
    def abilities(self) -> str:
        """Що може зробити зловмисник: прочитати / змінити / видалити."""
        parts = []
        if Operation.READ in self.operations:
            parts.append("прочитати")
        if self.operations & CHANGING_OPERATIONS:
            parts.append("змінити")
        if Operation.DELETE in self.operations:
            parts.append("видалити")
        return ", ".join(parts) or "—"


def impact_rows(enterprise: Enterprise, impact: CompromiseImpact) -> list[_ImpactRow]:
    """Рядки таблиці «радіусу ураження» для всіх ресурсів."""
    return [
        _ImpactRow(
            resource.id,
            resource.name,
            resource.criticality,
            resource.critical,
            impact.rights.get(resource.id, frozenset()),
        )
        for resource in enterprise.resources
    ]


def impact_summary(impact: CompromiseImpact) -> str:
    """Один рядок підсумку «радіусу ураження»: операції та ризик облікового запису."""
    return (
        f"Операцій: {impact.operation_count} · ризик: {impact.risk} із {impact.max_risk} "
        f"({fmt_percent(impact.risk_share)})"
    )


class _VerdictCard(QFrame):
    """Картка рішення за запитом доступу в одній моделі."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("verdictCard")
        self._title = QLabel(title)
        self._title.setProperty("role", "hint")
        self._verdict = QLabel()
        font = self._verdict.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() + 5)
        self._verdict.setFont(font)
        self._explanation = QLabel()
        self._explanation.setWordWrap(True)
        self._explanation.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.addWidget(self._title)
        layout.addWidget(self._verdict)
        layout.addWidget(self._explanation, 1)

    @property
    def verdict_text(self) -> str:
        """Показаний вердикт («ДОЗВОЛЕНО» / «ЗАБОРОНЕНО»)."""
        return self._verdict.text()

    def show_decision(self, model_name: str, decision: AccessDecision, note: str = "") -> None:
        """Показує рішення: колір — дозволено (зелений) чи заборонено (червоний), поруч підпис."""
        stroke = palette.STATUS_GOOD if decision.allowed else palette.STATUS_CRITICAL
        fill = palette.tint(stroke, 0.16)
        self._title.setText(model_name)
        self._verdict.setText(decision.verdict)
        self._explanation.setText(decision.explanation + (f"\n{note}" if note else ""))
        self.setStyleSheet(
            f"QFrame#verdictCard {{ background: {fill}; border: 1px solid {stroke}; "
            f"border-left: 6px solid {stroke}; border-radius: 4px; }}"
        )


class _ImpactPanel(QWidget):
    """«Радіус ураження» в одній моделі: підсумок і таблиця ресурсів."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: RecordTableModel[_ImpactRow] = RecordTableModel(_impact_columns(), parent=self)
        self._summary = QLabel()
        self._summary.setToolTip("Ризик облікового запису = Σ K(r) × Σ ваг операцій, доступних зловмиснику")
        self._view = make_table(self._rows, stretch_column=0)
        content = QVBoxLayout()
        content.addWidget(self._summary)
        content.addWidget(self._view, 1)
        self._box = section("", content)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._box)

    @property
    def summary_text(self) -> str:
        """Текст підсумку."""
        return self._summary.text()

    @property
    def rows(self) -> list[_ImpactRow]:
        """Рядки таблиці ресурсів."""
        return self._rows.records

    def show_impact(self, enterprise: Enterprise, model: AccessModel, impact: CompromiseImpact) -> None:
        """Показує «радіус ураження» облікового запису в моделі model."""
        self._box.setTitle(model.name)
        self._summary.setText(impact_summary(impact))
        self._rows.set_rows(impact_rows(enterprise, impact))


def _impact_columns() -> list[Column[_ImpactRow]]:
    critical_fill = palette.tint(palette.STATUS_CRITICAL, 0.10)
    return [
        Column(
            "Ресурс", lambda row: f"{row.resource_id} {row.name}",
            tooltip=lambda row: "Критичний ресурс" if row.critical else "", bold=True,
            fill=lambda row: critical_fill if row.critical and row.operations else None,
        ),
        Column("K", lambda row: str(row.criticality), align=CENTER, width=32),
        Column(
            "Операції", lambda row: operations_code(row.operations),
            fill=lambda row: palette.CELL_FILL[cell_level(row.operations)], align=CENTER, width=76,
        ),
        Column("Зловмисник може", lambda row: row.abilities, width=190),
        Column(
            "Ризик", lambda row: str(row.risk), align=CENTER, width=56,
            header_tooltip="K × Σ ваг доступних операцій",
        ),
    ]


class SimulationTab(ResultTab):
    """Моделювання запитів доступу та компрометації облікових записів."""

    def __init__(self, state: ModelState, parent: QWidget | None = None) -> None:
        super().__init__(state, parent)
        self._user = QComboBox()
        self._resource = QComboBox()
        self._operation = QComboBox()
        for combo in (self._user, self._resource, self._operation):
            combo.currentIndexChanged.connect(self._check_request)
        self._user.setMinimumWidth(260)
        self._resource.setMinimumWidth(240)
        request = QHBoxLayout()
        for title, combo in (("Користувач:", self._user), ("Ресурс:", self._resource), ("Операція:", self._operation)):
            request.addWidget(QLabel(title))
            request.addWidget(combo)
            request.addSpacing(8)
        request.addStretch(1)
        self._initial_card = _VerdictCard("Початкова модель")
        self._optimized_card = _VerdictCard("Оптимізована модель")
        cards = QGridLayout()
        cards.addWidget(self._initial_card, 0, 0)
        cards.addWidget(self._optimized_card, 0, 1)
        request_layout = QVBoxLayout()
        request_layout.addLayout(request)
        request_layout.addLayout(cards)
        request_box = section("Перевірка запиту доступу", request_layout)

        self._compromised = QComboBox()
        self._compromised.setMinimumWidth(260)
        self._compromised.currentIndexChanged.connect(self._simulate)
        self._delta = QLabel()
        self._delta.setMargin(4)
        account = QHBoxLayout()
        account.addWidget(QLabel("Обліковий запис:"))
        account.addWidget(self._compromised)
        account.addSpacing(12)
        account.addWidget(self._delta)
        account.addStretch(1)
        self._initial_impact = _ImpactPanel()
        self._optimized_impact = _ImpactPanel()
        panels = QSplitter(Qt.Orientation.Horizontal)
        panels.addWidget(self._initial_impact)
        panels.addWidget(self._optimized_impact)
        compromise_layout = QVBoxLayout()
        compromise_layout.addLayout(account)
        compromise_layout.addWidget(panels, 1)
        compromise_box = section("Компрометація облікового запису", compromise_layout)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(request_box)
        splitter.addWidget(compromise_box)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)

    @property
    def cards(self) -> tuple[_VerdictCard, _VerdictCard]:
        """Картки рішень: початкова й оптимізована моделі."""
        return self._initial_card, self._optimized_card

    @property
    def impact_panels(self) -> tuple[_ImpactPanel, _ImpactPanel]:
        """Панелі «радіусу ураження»: початкова й оптимізована моделі."""
        return self._initial_impact, self._optimized_impact

    def select_request(self, user_id: str, resource_id: str, operation: Operation) -> None:
        """Обирає запит доступу (для тестів і швидкого переходу)."""
        for combo, value in ((self._user, user_id), (self._resource, resource_id), (self._operation, operation.name)):
            position = combo.findData(value)
            if position >= 0:
                combo.setCurrentIndex(position)

    def select_compromised(self, user_id: str) -> None:
        """Обирає скомпрометований обліковий запис."""
        position = self._compromised.findData(user_id)
        if position >= 0:
            self._compromised.setCurrentIndex(position)

    def refresh(self, result: AnalysisResult) -> None:
        enterprise = result.enterprise
        users = [
            (f"{user.id} {user.full_name} — {enterprise.role(user.role_id).name}", user.id)
            for user in enterprise.users
        ]
        user_id, resource_id, operation_name = DEFAULT_REQUEST
        fill_combo(self._user, users, user_id)
        fill_combo(
            self._resource,
            [(f"{resource.id} — {resource.name}", resource.id) for resource in enterprise.resources],
            resource_id,
        )
        fill_combo(
            self._operation,
            [(f"{operation.short} — {operation.label}", operation.name) for operation in Operation],
            operation_name,
        )
        fill_combo(self._compromised, users, DEFAULT_COMPROMISED)
        self._check_request()
        self._simulate()

    def _models(self) -> tuple[Enterprise, AccessModel, AccessModel]:
        result = self.result
        return result.enterprise, result.initial.model, result.optimized.model

    def _check_request(self, *_args: object) -> None:
        user_id, resource_id = self._user.currentData(), self._resource.currentData()
        operation_name = self._operation.currentData()
        if not user_id or not resource_id or not operation_name:
            return
        operation = Operation[operation_name]
        enterprise, initial, optimized = self._models()
        finding = find_finding(self.result.findings, user_id, resource_id, operation)
        note = (
            f"Надлишкове право: {finding.severity.label.lower()} рівень ({', '.join(finding.rule_codes)})."
            if finding is not None
            else ""
        )
        self._initial_card.show_decision(
            initial.name, check_access(enterprise, initial, user_id, resource_id, operation), note
        )
        self._optimized_card.show_decision(
            optimized.name, check_access(enterprise, optimized, user_id, resource_id, operation)
        )

    def _simulate(self, *_args: object) -> None:
        user_id = self._compromised.currentData()
        if not user_id:
            return
        enterprise, initial, optimized = self._models()
        before = simulate_compromise(enterprise, initial, user_id)
        after = simulate_compromise(enterprise, optimized, user_id)
        self._initial_impact.show_impact(enterprise, initial, before)
        self._optimized_impact.show_impact(enterprise, optimized, after)
        change = fmt_signed_percent(percent(after.risk - before.risk, before.risk)) if before.risk else "—"
        self._delta.setText(f"Ризик: {before.risk} → {after.risk} ({change})")
        self._delta.setStyleSheet(
            f"background: {palette.ACCENT_SOFT}; border-left: 4px solid {palette.ACCENT}; "
            "border-radius: 3px; padding: 2px 8px;"
        )
