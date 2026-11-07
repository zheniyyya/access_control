"""Вкладка «Аналіз ризиків»: знахідки з фільтрами, ризик і захищеність, рейтинг, діаграма."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app import palette
from app.domain.models import operations_code
from app.export.charts import risk_figure
from app.services.analysis import AnalysisResult
from app.services.analyzer import Finding, GrantSummary, RoleExcess, Severity, filter_findings, rule_by_code
from app.services.formatting import fmt_percent
from app.services.risk import ResourceRisk, rank_by_risk
from app.ui.state import ModelState
from app.ui.table_models import CENTER, Column, RecordTableModel
from app.ui.tabs.base import ResultTab
from app.ui.widgets import ChartView, fill_combo, make_table, section

SEVERITY_COLUMN = 6


@dataclass(frozen=True)
class _RiskRow:
    """Рядок таблиці ризику: показники ресурсу та кількість знахідок за рівнями."""

    risk: ResourceRisk
    findings: dict[Severity, int]


@dataclass(frozen=True)
class _RankRow:
    """Рядок рейтингу ресурсів."""

    place: int
    risk: ResourceRisk


class RiskTab(ResultTab):
    """Надлишкові й небезпечні права, ризик і захищеність ресурсів."""

    def __init__(self, state: ModelState, parent: QWidget | None = None) -> None:
        super().__init__(state, parent)
        self._findings: RecordTableModel[Finding] = RecordTableModel(self._finding_columns(), parent=self)
        self._risks: RecordTableModel[_RiskRow] = RecordTableModel(self._risk_columns(), parent=self)
        self._ranking: RecordTableModel[_RankRow] = RecordTableModel(self._rank_columns(), parent=self)
        self._role_excess: RecordTableModel[RoleExcess] = RecordTableModel(self._role_excess_columns(), parent=self)
        self._grants: RecordTableModel[GrantSummary] = RecordTableModel(self._grant_columns(), parent=self)
        self._chart = ChartView()

        self._severity = QComboBox()
        self._resource = QComboBox()
        self._role = QComboBox()
        for combo in (self._severity, self._resource, self._role):
            combo.currentIndexChanged.connect(self._apply_filters)
            combo.setMinimumWidth(170)
        reset = QPushButton("Скинути фільтри")
        reset.clicked.connect(self._reset_filters)
        self._count = QLabel()
        filters = QHBoxLayout()
        for title, combo in (("Рівень:", self._severity), ("Ресурс:", self._resource), ("Роль:", self._role)):
            filters.addWidget(QLabel(title))
            filters.addWidget(combo)
            filters.addSpacing(8)
        filters.addWidget(reset)
        filters.addStretch(1)
        filters.addWidget(self._count)

        self._chips = QHBoxLayout()
        self._chips.setSpacing(8)
        self._chip_labels: dict[Severity, QPushButton] = {}
        for severity in Severity:
            chip = QPushButton()
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setToolTip("Показати лише цей рівень (повторне клацання — усі рівні)")
            chip.setStyleSheet(
                f"QPushButton {{ background: {palette.SEVERITY_FILL[severity]}; border: none; border-left: 4px solid "
                f"{palette.SEVERITY_STROKE[severity]}; border-radius: 3px; padding: 3px 10px; }}"
                f"QPushButton:hover {{ border: 1px solid {palette.SEVERITY_STROKE[severity]}; "
                f"border-left: 4px solid {palette.SEVERITY_STROKE[severity]}; }}"
            )
            chip.clicked.connect(lambda _checked=False, chosen=severity: self._toggle_severity(chosen))
            self._chip_labels[severity] = chip
            self._chips.addWidget(chip)
        self._chips.addStretch(1)

        self._findings_view = make_table(self._findings, sortable=True)
        self._findings_view.sortByColumn(SEVERITY_COLUMN, Qt.SortOrder.AscendingOrder)
        findings_layout = QVBoxLayout()
        findings_layout.addLayout(filters)
        findings_layout.addLayout(self._chips)
        findings_layout.addWidget(self._findings_view, 1)
        self._findings_box = section("Надлишкові та небезпечні права", findings_layout)

        details = QTabWidget()
        details.addTab(make_table(self._risks, stretch_column=0), "Захищеність")
        details.addTab(make_table(self._ranking, stretch_column=1), "Рейтинг")
        details.addTab(make_table(self._role_excess, stretch_column=5), "Ролі")
        details.addTab(make_table(self._grants), "Поза роллю")
        details.setTabToolTip(2, "Надлишкові права на рівні матриці ролей")
        details.setTabToolTip(3, "Індивідуальні дозволи поза роллю")
        bottom = QSplitter(Qt.Orientation.Horizontal)
        bottom.addWidget(details)
        bottom.addWidget(section("Індекс ризику", self._chart))
        bottom.setStretchFactor(0, 6)
        bottom.setStretchFactor(1, 5)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._findings_box)
        splitter.addWidget(bottom)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 6)
        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)

    @property
    def findings_view(self) -> QTableView:
        """Таблиця знахідок (відсортована за рівнем небезпеки)."""
        return self._findings_view

    def refresh(self, result: AnalysisResult) -> None:
        enterprise = result.enterprise
        fill_combo(self._severity, [("Усі рівні", "")] + [(severity.label, severity.name) for severity in Severity])
        fill_combo(
            self._resource,
            [("Усі ресурси", "")] + [(f"{resource.id} — {resource.name}", resource.id) for resource in enterprise.resources],
        )
        fill_combo(self._role, [("Усі ролі", "")] + [(role.name, role.id) for role in enterprise.roles])
        counts = result.severity_counts
        for severity, chip in self._chip_labels.items():
            chip.setText(f"{severity.label}: {counts[severity]}")
        self._apply_filters()
        by_resource = result.findings_by_resource
        self._risks.set_rows(
            [_RiskRow(risk, by_resource[risk.resource_id]) for risk in result.initial.risks]
        )
        self._ranking.set_rows(
            [_RankRow(place, risk) for place, risk in enumerate(rank_by_risk(result.initial.risks), start=1)]
        )
        self._role_excess.set_rows(result.role_excess)
        self._grants.set_rows(result.grants)
        self._chart.set_figure(risk_figure(result))

    def _apply_filters(self, *_args: object) -> None:
        severity_name = self._severity.currentData()
        rows = filter_findings(
            self.result.findings,
            severity=Severity[severity_name] if severity_name else None,
            resource_id=self._resource.currentData() or None,
            role_id=self._role.currentData() or None,
        )
        self._findings.set_rows(rows)
        self._count.setText(f"Показано: {len(rows)} із {len(self.result.findings)}")

    def _toggle_severity(self, severity: Severity) -> None:
        """Фільтр за рівнем з кольорових лічильників: вибрати рівень або зняти фільтр."""
        current = self._severity.currentData()
        position = self._severity.findData("" if current == severity.name else severity.name)
        self._severity.setCurrentIndex(max(position, 0))

    def _reset_filters(self) -> None:
        for combo in (self._severity, self._resource, self._role):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            combo.blockSignals(False)
        self._apply_filters()

    def _user_label(self, user_id: str) -> str:
        user = self.result.enterprise.user(user_id)
        return f"{user.id} {user.full_name}"

    def _role_name(self, role_id: str) -> str:
        return self.result.enterprise.role(role_id).name

    def _resource_name(self, resource_id: str) -> str:
        resource = self.result.enterprise.resource(resource_id)
        return f"{resource.id} «{resource.name}»"

    def _finding_columns(self) -> list[Column[Finding]]:
        def rules_tooltip(finding: Finding) -> str:
            return "\n".join(f"{code}: {rule_by_code(code).title}" for code in finding.rule_codes)

        def recommendation_tooltip(finding: Finding) -> str:
            reason = f"\nПричина надання: {finding.grant_reason}" if finding.grant_reason else ""
            return finding.recommendation + reason

        return [
            Column("Користувач", lambda f: self._user_label(f.user_id), width=180, sort_key=lambda f: f.user_id),
            Column("Роль", lambda f: self._role_name(f.role_id), width=110),
            Column(
                "Ресурс", lambda f: f.resource_id, tooltip=lambda f: self._resource_name(f.resource_id),
                align=CENTER, width=64,
            ),
            Column(
                "Операція", lambda f: f"{f.operation.short} — {f.operation.label.lower()}",
                width=124, sort_key=lambda f: f.operation.weight,
            ),
            Column(
                "Джерело", lambda f: f.source.value,
                tooltip=lambda f: f.grant_reason or f.source.value, width=168,
            ),
            Column("Правила", lambda f: ", ".join(f.rule_codes), tooltip=rules_tooltip, width=140),
            Column(
                "Рівень", lambda f: f.severity.label, fill=lambda f: palette.SEVERITY_FILL[f.severity],
                sort_key=lambda f: -f.severity.rank, width=92,
            ),
            Column("Рекомендація", lambda f: f.recommendation, tooltip=recommendation_tooltip),
        ]

    def _risk_columns(self) -> list[Column[_RiskRow]]:
        severity_order = " / ".join(severity.label.lower() for severity in Severity)
        return [
            Column(
                "Ресурс", lambda row: f"{row.risk.resource_id} {row.risk.resource_name}",
                tooltip=lambda row: self._resource_name(row.risk.resource_id), bold=True,
            ),
            Column("K", lambda row: str(row.risk.criticality), align=CENTER, width=32,
                   header_tooltip="Коефіцієнт критичності"),
            Column("Ризик", lambda row: str(row.risk.risk), align=CENTER, width=52,
                   header_tooltip="Ризик(r) = K × Σ ваг дозволених операцій усіх користувачів"),
            Column("Max", lambda row: str(row.risk.max_risk), align=CENTER, width=46,
                   header_tooltip="Максимальний ризик: кількість користувачів × 10 × K"),
            Column("Z", lambda row: fmt_percent(row.risk.protection), align=CENTER, width=62,
                   header_tooltip="Рівень захищеності Z = (1 − Ризик / Max) × 100 %"),
            Column(
                "Оцінка", lambda row: row.risk.level.label,
                fill=lambda row: palette.PROTECTION_FILL[row.risk.level], width=76,
                header_tooltip="Z ≥ 80 % — високий, 50–80 % — середній, < 50 % — низький",
            ),
            Column(
                "Користувачі",
                lambda row: f"{row.risk.users_any} / {row.risk.users_modify} / {row.risk.users_delete}",
                align=CENTER, width=100,
                header_tooltip="Користувачів з будь-яким доступом / з модифікуючим (З, Р, В) / з видаленням",
            ),
            Column(
                "Знахідки",
                lambda row: " / ".join(str(row.findings[severity]) for severity in Severity),
                fill=lambda row: palette.SEVERITY_FILL[Severity.CRITICAL] if row.findings[Severity.CRITICAL] else None,
                align=CENTER, width=104,
                header_tooltip=f"Кількість знахідок за рівнями: {severity_order}",
            ),
        ]

    @staticmethod
    def _rank_columns() -> list[Column[_RankRow]]:
        return [
            Column("Місце", lambda row: str(row.place), align=CENTER, width=56, bold=True),
            Column("Ресурс", lambda row: f"{row.risk.resource_id} {row.risk.resource_name}"),
            Column("Індекс ризику", lambda row: f"{row.risk.risk} із {row.risk.max_risk}", align=CENTER, width=110),
            Column("Z", lambda row: fmt_percent(row.risk.protection), align=CENTER, width=70),
            Column(
                "Оцінка захищеності", lambda row: row.risk.level.label,
                fill=lambda row: palette.PROTECTION_FILL[row.risk.level],
            ),
        ]

    def _role_excess_columns(self) -> list[Column[RoleExcess]]:
        return [
            Column("Роль", lambda row: self._role_name(row.role_id), width=110),
            Column("Ресурс", lambda row: row.resource_id, tooltip=lambda row: self._resource_name(row.resource_id),
                   align=CENTER, width=60),
            Column("Надано", lambda row: operations_code(row.granted), align=CENTER, width=64),
            Column("Потрібно", lambda row: operations_code(row.required), align=CENTER, width=70,
                   header_tooltip="Операції за службовими функціями (еталон)"),
            Column("Надлишкові", lambda row: operations_code(row.excess), align=CENTER, width=84),
            Column("Правила", lambda row: ", ".join(row.rule_codes)),
            Column(
                "Рівень", lambda row: row.severity.label, fill=lambda row: palette.SEVERITY_FILL[row.severity],
                width=84,
            ),
            Column("Корист.", lambda row: str(row.user_count), align=CENTER, width=64,
                   header_tooltip="Скільки користувачів успадковують надлишкові права ролі"),
        ]

    def _grant_columns(self) -> list[Column[GrantSummary]]:
        return [
            Column("Користувач", lambda row: self._user_label(row.user_id), width=170),
            Column("Роль", lambda row: self._role_name(row.role_id), width=100),
            Column("Ресурс", lambda row: row.resource_id, tooltip=lambda row: self._resource_name(row.resource_id),
                   align=CENTER, width=60),
            Column("Операції", lambda row: operations_code(row.operations), align=CENTER, width=72),
            Column("Надлишкові", lambda row: operations_code(row.excess), align=CENTER, width=84),
            Column(
                "Рівень", lambda row: row.severity.label if row.severity else "—",
                fill=lambda row: palette.SEVERITY_FILL[row.severity] if row.severity else None, width=84,
            ),
            Column("Причина надання", lambda row: row.reason, tooltip=lambda row: row.reason),
        ]
