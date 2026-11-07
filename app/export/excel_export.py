"""Експорт результатів у Excel (openpyxl): дев'ять аркушів з кольорами як у застосунку.

Клітинки матриць мають і статичне тло, і умовне форматування за вмістом
(«В» — червоний, «З»/«Р» — жовтий, лише «Ч» — зелений, немає — сірий), тож
після редагування літер у самому Excel колір теж оновлюється. Заголовки
закріплено, ширину стовпців підібрано за вмістом.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app import APP_NAME, palette
from app.domain.models import GAP_MARK, Operation
from app.export import tables
from app.export.tables import CellKind, Highlight, Table, TableCell
from app.services.analysis import AnalysisResult
from app.services.analyzer import Severity
from app.services.matrix import CellLevel
from app.services.risk import ProtectionLevel

# Excel обмежує назву аркуша 31 символом, тому «користувачі» в останній матриці скорочено.
SHEET_USERS = "Користувачі"
SHEET_RESOURCES = "Ресурси"
SHEET_INITIAL_ROLES = "Початкова матриця (ролі)"
SHEET_INITIAL_USERS = "Початкова матриця (користувачі)"
SHEET_FINDINGS = "Надлишкові права"
SHEET_OPTIMIZED_ROLES = "Оптимізована матриця (ролі)"
SHEET_OPTIMIZED_USERS = "Оптимізована матриця (корист.)"
SHEET_COMPARISON = "Порівняння"
SHEET_RISKS = "Ризики"
SHEET_NAMES = (
    SHEET_USERS,
    SHEET_RESOURCES,
    SHEET_INITIAL_ROLES,
    SHEET_INITIAL_USERS,
    SHEET_FINDINGS,
    SHEET_OPTIMIZED_ROLES,
    SHEET_OPTIMIZED_USERS,
    SHEET_COMPARISON,
    SHEET_RISKS,
)

TITLE_ROW = 1
HEADER_ROW = 2
FIRST_DATA_ROW = 3
MAX_COLUMN_WIDTH = 60
MONO_FONT = "Consolas"

_THIN = Side(style="thin", color="FFC3C2B7")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)

NUMBER_FORMATS: dict[CellKind, str] = {
    CellKind.PERCENT: '0.0" %"',
    CellKind.SIGNED: '+0;"−"0;0',
    CellKind.POINTS: '+0.0" в. п.";"−"0.0" в. п.";0.0" в. п."',
    CellKind.SIGNED_PERCENT: '+0.0" %";"−"0.0" %";0.0" %"',
}


def argb(color: str) -> str:
    """«#rrggbb» → «FFRRGGBB» (формат кольору openpyxl)."""
    return "FF" + color.lstrip("#").upper()


def solid(color: str) -> PatternFill:
    """Суцільна заливка кольором «#rrggbb»."""
    return PatternFill(fill_type="solid", start_color=argb(color), end_color=argb(color))


def _number_format(cell: TableCell) -> str:
    if cell.kind in NUMBER_FORMATS:
        return NUMBER_FORMATS[cell.kind]
    return "0" if cell.digits == 0 else "0." + "0" * cell.digits


def _matrix_value(cell: TableCell) -> str | CellRichText:
    """Текст клітинки матриці; літери індивідуального дозволу — червоні підкреслені."""
    if cell.operations is None or not cell.grant_operations:
        return str(cell.value)
    normal = InlineFont(rFont=MONO_FONT, b=True, color=argb(palette.INK))
    grant = InlineFont(rFont=MONO_FONT, b=True, color=argb(palette.GRANT_INK), u="single")
    muted = InlineFont(rFont=MONO_FONT, b=True, color=argb(palette.INK_MUTED))
    blocks = []
    for operation in Operation:
        if operation in cell.grant_operations:
            blocks.append(TextBlock(grant, operation.short))
        elif operation in cell.operations:
            blocks.append(TextBlock(normal, operation.short))
        else:
            blocks.append(TextBlock(muted, GAP_MARK))
    return CellRichText(blocks)


def write_table(sheet: Worksheet, table: Table) -> None:
    """Записує таблицю на аркуш: назва, заголовки, рядки, кольори, формати, умовне форматування."""
    sheet.cell(TITLE_ROW, 1, table.title).font = Font(bold=True, size=12)
    header_fill = solid(palette.PAGE)
    for column, title in enumerate(table.headers, start=1):
        cell = sheet.cell(HEADER_ROW, column, title)
        cell.font = Font(bold=True, color=argb(palette.INK_SECONDARY))
        cell.fill = header_fill
        cell.border = _BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    matrix_columns = {index for index, kind in table.highlights.items() if kind is Highlight.MATRIX}
    for offset, row in enumerate(table.rows):
        number = FIRST_DATA_ROW + offset
        for position, data in enumerate(row):
            cell = sheet.cell(number, position + 1)
            cell.border = _BORDER
            if position in matrix_columns and data.operations is not None:
                cell.value = _matrix_value(data)
                cell.font = Font(name=MONO_FONT, bold=True)
                cell.alignment = Alignment(horizontal="center", vertical="center")
            elif data.value is None:
                cell.value = "—"
                cell.alignment = Alignment(horizontal="center")
            elif isinstance(data.value, str):
                cell.value = data.value
                cell.alignment = Alignment(vertical="center", wrap_text=len(data.value) > MAX_COLUMN_WIDTH)
                if data.bold:
                    cell.font = Font(bold=True)
            else:
                cell.value = data.value
                cell.number_format = _number_format(data)
                cell.alignment = Alignment(horizontal="center", vertical="center")
            if data.fill:
                cell.fill = solid(data.fill)
            if data.note:
                comment = Comment(data.note, APP_NAME)
                comment.width, comment.height = 320, 90
                cell.comment = comment
    _add_highlights(sheet, table)
    _fit_columns(sheet, table)
    sheet.freeze_panes = sheet.cell(FIRST_DATA_ROW, 1)


def _add_highlights(sheet: Worksheet, table: Table) -> None:
    """Умовне форматування кольорами для стовпців матриць, рівнів небезпеки й захищеності."""
    if not table.rows:
        return
    last = FIRST_DATA_ROW + len(table.rows) - 1
    for index, kind in table.highlights.items():
        letter = get_column_letter(index + 1)
        area = f"{letter}{FIRST_DATA_ROW}:{letter}{last}"
        top = f"{letter}{FIRST_DATA_ROW}"
        if kind is Highlight.MATRIX:
            rules = (
                (f'ISNUMBER(SEARCH("{Operation.DELETE.short}",{top}))', CellLevel.DELETE),
                (
                    f'OR(ISNUMBER(SEARCH("{Operation.WRITE.short}",{top})),'
                    f'ISNUMBER(SEARCH("{Operation.EDIT.short}",{top})))',
                    CellLevel.MODIFY,
                ),
                (f'ISNUMBER(SEARCH("{Operation.READ.short}",{top}))', CellLevel.READ),
                (f'{top}="{GAP_MARK * len(Operation)}"', CellLevel.NONE),
            )
            for formula, level in rules:
                sheet.conditional_formatting.add(
                    area, FormulaRule(formula=[formula], fill=solid(palette.CELL_FILL[level]), stopIfTrue=True)
                )
        elif kind is Highlight.SEVERITY:
            for severity in Severity:
                sheet.conditional_formatting.add(
                    area,
                    CellIsRule(operator="equal", formula=[f'"{severity.label}"'], fill=solid(palette.SEVERITY_FILL[severity])),
                )
        elif kind is Highlight.PROTECTION:
            for level in ProtectionLevel:
                sheet.conditional_formatting.add(
                    area,
                    CellIsRule(operator="equal", formula=[f'"{level.label}"'], fill=solid(palette.PROTECTION_FILL[level])),
                )


def _fit_columns(sheet: Worksheet, table: Table) -> None:
    """Автоширина: найдовший текст стовпця (заголовок — з урахуванням переносу)."""
    for index, header in enumerate(table.headers):
        longest_word = max((len(word) for word in header.split()), default=4)
        width = max(longest_word, min(len(header), 16))
        for row in table.rows:
            if index < len(row):
                width = max(width, len(row[index].text))
        sheet.column_dimensions[get_column_letter(index + 1)].width = min(width + 2, MAX_COLUMN_WIDTH)
    sheet.row_dimensions[HEADER_ROW].height = 32


def _sheet_tables(result: AnalysisResult) -> list[tuple[str, Callable[[], Table], str]]:
    """Аркуші: назва, побудова таблиці, клітинка для закріплення областей."""
    return [
        (SHEET_USERS, lambda: tables.users_table(result), "C3"),
        (SHEET_RESOURCES, lambda: tables.resources_table(result), "C3"),
        (SHEET_INITIAL_ROLES, lambda: tables.role_matrix_table(result, result.initial), "C3"),
        (SHEET_INITIAL_USERS, lambda: tables.user_matrix_table(result, result.initial), "C3"),
        (SHEET_FINDINGS, lambda: tables.findings_table(result), "C3"),
        (SHEET_OPTIMIZED_ROLES, lambda: tables.role_matrix_table(result, result.optimized), "C3"),
        (SHEET_OPTIMIZED_USERS, lambda: tables.user_matrix_table(result, result.optimized), "C3"),
        (SHEET_COMPARISON, lambda: tables.comparison_table(result), "B3"),
        (SHEET_RISKS, lambda: tables.risks_table(result, detailed=True), "B3"),
    ]


def build_workbook(result: AnalysisResult) -> Workbook:
    """Будує книгу Excel з усіма аркушами результатів."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    workbook.properties.title = f"{APP_NAME} — {result.enterprise.name}"
    workbook.properties.creator = APP_NAME
    for name, build, freeze in _sheet_tables(result):
        sheet = workbook.create_sheet(name)
        table = build()
        write_table(sheet, table)
        sheet.freeze_panes = freeze
        if name == SHEET_FINDINGS:
            last = FIRST_DATA_ROW + len(table.rows) - 1
            sheet.auto_filter.ref = f"A{HEADER_ROW}:{get_column_letter(len(table.headers))}{last}"
        if name in (SHEET_INITIAL_USERS, SHEET_OPTIMIZED_USERS):
            note_row = FIRST_DATA_ROW + len(table.rows) + 1
            sheet.cell(note_row, 1, "Червоні підкреслені літери — операції з індивідуального дозволу поза роллю "
                                    "(причина — у примітці до клітинки).").font = Font(italic=True, color=argb(palette.INK_MUTED))
    return workbook


def export_excel(result: AnalysisResult, path: str | Path) -> Path:
    """Зберігає результати у файл .xlsx; OSError — якщо файл недоступний (напр. відкритий в Excel)."""
    target = Path(path)
    if target.suffix.lower() != ".xlsx":
        target = target.with_suffix(".xlsx")
    build_workbook(result).save(target)
    return target
