"""Тести експорту: Excel (аркуші, значення, кольори, умовне форматування) і Word (оформлення, підписи)."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from docx import Document
from docx.shared import Pt
from openpyxl import load_workbook

from app import palette
from app.export import tables
from app.export.charts import risk_figure
from app.export.excel_export import (
    SHEET_COMPARISON,
    SHEET_FINDINGS,
    SHEET_INITIAL_ROLES,
    SHEET_INITIAL_USERS,
    SHEET_NAMES,
    SHEET_OPTIMIZED_USERS,
    SHEET_RISKS,
    argb,
    export_excel,
)
from app.export.word_report import SCHEME_INITIAL, build_report, column_widths, export_word
from app.services.analysis import AnalysisResult
from app.services.matrix import CellLevel


def _rows(sheet) -> list[tuple]:  # type: ignore[no-untyped-def]
    return list(sheet.iter_rows(min_row=3, values_only=True))


def test_excel_sheets_and_values(result: AnalysisResult, tmp_path: Path) -> None:
    path = export_excel(result, tmp_path / "результати")
    assert path.suffix == ".xlsx"
    workbook = load_workbook(path)
    assert workbook.sheetnames == list(SHEET_NAMES)
    assert all(len(name) <= 31 for name in workbook.sheetnames)

    roles = workbook[SHEET_INITIAL_ROLES]
    manager = next(row for row in _rows(roles) if row[0] == "Керівник")
    assert manager[2:8] == ("ЧЗРВ", "ЧЗРВ", "ЧЗРВ", "ЧЗРВ", "Ч·РВ", "ЧЗРВ") and manager[8] == 23
    assert roles.freeze_panes == "C3"
    r5 = roles.cell(4, 7)  # Адміністратор → R5 («ЧЗРВ»)
    assert r5.fill.start_color.rgb == argb(palette.CELL_FILL[CellLevel.DELETE])
    assert roles.conditional_formatting  # кольори за вмістом клітинок

    users = workbook[SHEET_INITIAL_USERS]
    assert sum(row[-1] for row in _rows(users) if isinstance(row[-1], int)) == 316
    optimized = workbook[SHEET_OPTIMIZED_USERS]
    assert sum(row[-1] for row in _rows(optimized) if isinstance(row[-1], int)) == 158

    findings = workbook[SHEET_FINDINGS]
    data = [row for row in _rows(findings) if row[0] is not None]
    assert len(data) == 158
    levels = [row[7] for row in data]
    assert levels.count("Критичний") == 26 and levels.count("Низький") == 83
    assert findings.auto_filter.ref

    comparison = {row[0]: row[1:] for row in _rows(workbook[SHEET_COMPARISON]) if row[0]}
    assert comparison["Дозволені операції — матриця користувачів (з 480)"][:3] == (316, 158, -158)
    assert comparison["Рівень захищеності"][:2] == (40.8, 74.1)  # останній такий рядок — усі ресурси

    risks = {row[0]: row for row in _rows(workbook[SHEET_RISKS]) if row[0]}
    r1 = risks["R1 База даних клієнтів"]
    assert (r1[3], r1[4], r1[9], r1[10]) == (498, 17.0, 288, 52.0)


def test_excel_grant_cells_marked(result: AnalysisResult, tmp_path: Path) -> None:
    workbook = load_workbook(export_excel(result, tmp_path / "grants.xlsx"), rich_text=True)
    users = workbook[SHEET_INITIAL_USERS]
    row = next(number for number in range(3, users.max_row + 1) if str(users.cell(number, 1).value).startswith("U12"))
    finance = users.cell(row, 4)  # R2
    assert str(finance.value) == "ЧЗРВ"
    assert finance.comment is not None and "Успадковано" in finance.comment.text


def test_word_report_formatting(result: AnalysisResult, tmp_path: Path) -> None:
    path = export_word(result, tmp_path / "звіт")
    assert path.suffix == ".docx" and path.stat().st_size > 100_000
    document = Document(str(path))
    normal = document.styles["Normal"]
    assert normal.font.name == "Times New Roman" and normal.font.size == Pt(14)
    assert normal.paragraph_format.line_spacing == 1.5
    texts = [paragraph.text for paragraph in document.paragraphs]
    tables_captions = [text for text in texts if text.startswith("Таблиця 2.")]
    figure_captions = [text for text in texts if text.startswith("Рисунок 2.")]
    assert tables_captions[0].startswith("Таблиця 2.1 – ")
    assert figure_captions[0].startswith("Рисунок 2.1 – ")
    assert len(tables_captions) == len(document.tables) >= 15
    assert len(figure_captions) == len(document.inline_shapes) == 4  # без схем — лише діаграми
    headings = [paragraph.text for paragraph in document.paragraphs if paragraph.style.name.startswith("Heading")]
    assert [text.split()[0] for text in headings[1:]] == ["2.1", "2.2", "2.3", "2.4", "2.5", "2.6"]
    assert any("158 надлишкових прав" in text for text in texts)
    table = document.tables[0]
    run = table.rows[1].cells[0].paragraphs[0].runs[0]
    assert run.font.size == Pt(12)


def test_word_report_with_schemes(result: AnalysisResult) -> None:
    # Замість схеми (її малює Qt) підійде будь-яке PNG — беремо діаграму.
    buffer = BytesIO()
    risk_figure(result).savefig(buffer, format="png", dpi=50)
    document = build_report(result, {SCHEME_INITIAL: buffer.getvalue()})
    captions = [p.text for p in document.paragraphs if p.text.startswith("Рисунок 2.")]
    assert captions[0] == "Рисунок 2.1 – Структурна схема початкової моделі розмежування доступу"
    assert len(document.inline_shapes) == 5


def test_column_widths_fit_page(result: AnalysisResult) -> None:
    for table in (
        tables.user_matrix_table(result, result.initial),
        tables.findings_table(result, compact=True),
        tables.comparison_table(result),
        tables.compromise_table(result),
    ):
        widths = column_widths(table, 16.5)
        assert len(widths) == len(table.headers)
        assert abs(sum(widths) - 16.5) < 1e-6
