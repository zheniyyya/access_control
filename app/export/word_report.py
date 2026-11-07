"""Звіт у Word (python-docx) для пояснювальної записки: розділи за завданнями 1–6.

Оформлення: Times New Roman 14 пт, міжрядковий інтервал 1,5, абзацний відступ
1,25 см; таблиці з рамками, шрифт 12 пт, рядок заголовків повторюється на
кожній сторінці; підписи «Таблиця 2.1 – …» над таблицями та «Рисунок 2.1 – …»
під рисунками. Діаграми — ті самі фігури matplotlib, що й у застосунку.
Модуль не залежить від Qt: зображення структурних схем передає GUI (PNG-байти).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentObject
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.styles.style import ParagraphStyle
from docx.table import _Cell
from docx.text.paragraph import Paragraph
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.textpath import TextToPath

from app import APP_NAME, palette
from app.domain.models import GAP_MARK, Operation
from app.export import tables
from app.export.charts import heatmaps_figure, protection_figure, risk_figure, role_operations_figure
from app.export.tables import Highlight, Table, TableCell
from app.services.analysis import AnalysisResult
from app.services.analyzer import Severity
from app.services.formatting import fmt_percent
from app.services.optimizer import function_count

FONT_NAME = "Times New Roman"
BODY_SIZE = Pt(14)
TABLE_SIZE = Pt(12)
LINE_SPACING = 1.5
FIRST_LINE_INDENT = Cm(1.25)
CHAPTER = 2
FIGURE_DPI = 200
# Поля клітинки Word (2 × 0,19 см) і запас на рамки — для автоширини стовпців, см.
CELL_PADDING_CM = 0.45
CM_PER_POINT = 2.54 / 72
_TEXT_PATH = TextToPath()
MARGINS = {"left": Cm(3.0), "right": Cm(1.5), "top": Cm(2.0), "bottom": Cm(2.0)}

# Ключі зображень структурних схем, які передає GUI.
SCHEME_INITIAL = "initial"
SCHEME_OPTIMIZED = "optimized"


def _set_run_font(run_properties: OxmlElement, name: str) -> None:
    """Шрифт для всіх систем письма (зокрема кирилиці) у властивостях run або стилю."""
    fonts = run_properties.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts")
        run_properties.insert(0, fonts)
    for attribute in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        fonts.set(qn(attribute), name)
    # Шрифти теми (у стилях заголовків) мають пріоритет над явними — прибираємо їх.
    for attribute in ("w:asciiTheme", "w:hAnsiTheme", "w:eastAsiaTheme", "w:cstheme"):
        fonts.attrib.pop(qn(attribute), None)


def _shade(cell: _Cell, color: str) -> None:
    """Заливка клітинки таблиці кольором «#rrggbb»."""
    properties = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), color.lstrip("#").upper())
    properties.append(shading)


def _repeat_header(row_element: OxmlElement) -> None:
    """Позначає рядок як заголовок, що повторюється на кожній сторінці."""
    properties = row_element.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    properties.append(header)


def _keep_row_together(row_element: OxmlElement) -> None:
    """Забороняє розривати рядок таблиці між сторінками."""
    properties = row_element.get_or_add_trPr()
    properties.append(OxmlElement("w:cantSplit"))


def _rgb(color: str) -> RGBColor:
    return RGBColor.from_string(color.lstrip("#").upper())


@lru_cache(maxsize=8192)
def _text_width_cm(text: str, bold: bool) -> float:
    """Ширина тексту шрифтом таблиць (Times New Roman 12 пт), виміряна за метриками шрифту, см.

    Якщо Times New Roman у системі немає, вимірюється ширшим DejaVu Serif — із запасом.
    """
    font = FontProperties(
        family=[FONT_NAME, "DejaVu Serif"], weight="bold" if bold else "normal", size=TABLE_SIZE.pt
    )
    width, _height, _descent = _TEXT_PATH.get_text_width_height_descent(text, font, ismath=False)
    return width * CM_PER_POINT


def column_widths(table: Table, available: float) -> list[float]:
    """Автоширина стовпців, см: кожен стовпець не вужчий за найдовше слово,
    вільне місце розподіляється пропорційно до потреби в ньому (без переносу всередині слів)."""
    minimum: list[float] = []
    desired: list[float] = []
    for index, header in enumerate(table.headers):
        texts = [(header, True)] + [(row[index].text, row[index].bold) for row in table.rows if index < len(row)]
        # Розбиваємо лише за звичайними пробілами: нерозривні («−50,0 %») тримають текст разом.
        word = max(_text_width_cm(part, bold) for text, bold in texts for part in text.split(" "))
        full = max(_text_width_cm(text, bold) for text, bold in texts)
        minimum.append(word + CELL_PADDING_CM)
        desired.append(max(full, word) + CELL_PADDING_CM)
    total_minimum = sum(minimum)
    if total_minimum >= available:
        return [width * available / total_minimum for width in minimum]
    if sum(desired) <= available:
        return [width * available / sum(desired) for width in desired]
    extra = available - total_minimum
    wanted = [full - word for full, word in zip(desired, minimum)]
    return [word + extra * want / sum(wanted) for word, want in zip(minimum, wanted)]


def _figure_png(figure: Figure) -> BytesIO:
    """PNG-зображення фігури matplotlib у пам'яті."""
    buffer = BytesIO()
    figure.savefig(buffer, format="png", dpi=FIGURE_DPI, facecolor=figure.get_facecolor())
    buffer.seek(0)
    return buffer


class _Report:
    """Побудова документа: нумерація таблиць і рисунків у межах розділу."""

    def __init__(self) -> None:
        self.document: DocumentObject = Document()
        self._tables = 0
        self._figures = 0
        self._setup_page()
        self._setup_styles()

    @property
    def text_width_cm(self) -> float:
        """Ширина області тексту сторінки, см."""
        section = self.document.sections[0]
        return (section.page_width - section.left_margin - section.right_margin) / Cm(1)

    def next_table(self, offset: int = 0) -> str:
        """Номер наступної (offset — подальшої) таблиці, напр. «2.3», — для посилань у тексті."""
        return f"{CHAPTER}.{self._tables + 1 + offset}"

    def next_figure(self, offset: int = 0) -> str:
        """Номер наступного (offset — подальшого) рисунка — для посилань у тексті."""
        return f"{CHAPTER}.{self._figures + 1 + offset}"

    def _setup_page(self) -> None:
        section = self.document.sections[0]
        section.orientation = WD_ORIENT.PORTRAIT
        section.page_width, section.page_height = Cm(21.0), Cm(29.7)
        section.left_margin = MARGINS["left"]
        section.right_margin = MARGINS["right"]
        section.top_margin = MARGINS["top"]
        section.bottom_margin = MARGINS["bottom"]
        self._add_page_number(section.header.paragraphs[0])

    @staticmethod
    def _add_page_number(paragraph: Paragraph) -> None:
        """Номер сторінки у верхньому правому куті (поле PAGE)."""
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        run = paragraph.add_run()
        for kind, text in (("begin", None), (None, "PAGE"), ("end", None)):
            if kind is not None:
                char = OxmlElement("w:fldChar")
                char.set(qn("w:fldCharType"), kind)
                run._r.append(char)
            else:
                instruction = OxmlElement("w:instrText")
                instruction.set(qn("xml:space"), "preserve")
                instruction.text = text
                run._r.append(instruction)
        run.font.name = FONT_NAME
        run.font.size = BODY_SIZE

    def _setup_styles(self) -> None:
        styles = self.document.styles
        normal = styles["Normal"]
        assert isinstance(normal, ParagraphStyle)
        normal.font.name = FONT_NAME
        normal.font.size = BODY_SIZE
        _set_run_font(normal.element.get_or_add_rPr(), FONT_NAME)
        normal.paragraph_format.line_spacing = LINE_SPACING
        normal.paragraph_format.first_line_indent = FIRST_LINE_INDENT
        normal.paragraph_format.space_before = Pt(0)
        normal.paragraph_format.space_after = Pt(0)
        normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        for name, centered in (("Heading 1", True), ("Heading 2", False)):
            style = styles[name]
            assert isinstance(style, ParagraphStyle)
            style.font.name = FONT_NAME
            style.font.size = BODY_SIZE
            style.font.bold = True
            style.font.italic = False
            style.font.color.rgb = RGBColor(0, 0, 0)
            _set_run_font(style.element.get_or_add_rPr(), FONT_NAME)
            fmt = style.paragraph_format
            fmt.line_spacing = LINE_SPACING
            fmt.space_before = Pt(12)
            fmt.space_after = Pt(12)
            fmt.keep_with_next = True
            fmt.first_line_indent = Cm(0) if centered else FIRST_LINE_INDENT
            fmt.alignment = WD_ALIGN_PARAGRAPH.CENTER if centered else WD_ALIGN_PARAGRAPH.LEFT

    def heading(self, text: str, level: int) -> None:
        """Заголовок розділу (1) або підрозділу (2)."""
        self.document.add_heading(text, level=level)

    def paragraph(self, text: str, *, bold_prefix: str = "") -> Paragraph:
        """Абзац основного тексту; bold_prefix — виділений початок абзацу."""
        paragraph = self.document.add_paragraph()
        if bold_prefix:
            paragraph.add_run(bold_prefix).bold = True
        paragraph.add_run(text)
        return paragraph

    def _caption(self, text: str, centered: bool) -> Paragraph:
        paragraph = self.document.add_paragraph(text)
        fmt = paragraph.paragraph_format
        fmt.first_line_indent = Cm(0)
        fmt.alignment = WD_ALIGN_PARAGRAPH.CENTER if centered else WD_ALIGN_PARAGRAPH.LEFT
        fmt.keep_with_next = not centered
        fmt.space_before = Pt(6)
        fmt.space_after = Pt(6)
        return paragraph

    def table(self, table: Table, caption: str | None = None) -> None:
        """Таблиця з підписом «Таблиця 2.N – …», рамками, шрифтом 12 пт і кольорами як у GUI."""
        self._tables += 1
        self._caption(f"Таблиця {CHAPTER}.{self._tables} – {caption or table.title}", centered=False)
        document_table = self.document.add_table(rows=1, cols=len(table.headers))
        document_table.style = "Table Grid"
        document_table.alignment = WD_TABLE_ALIGNMENT.CENTER
        document_table.autofit = False
        widths = self._column_widths(table)
        for column, width in zip(document_table.columns, widths):
            column.width = width  # ширини сітки таблиці (w:gridCol) — їх і використовує Word
        header = document_table.rows[0]
        _repeat_header(header._tr)
        for cell, title, width in zip(header.cells, table.headers, widths):
            cell.width = width
            self._write_cell(cell, TableCell(title, bold=True, fill=palette.PAGE), center=True)
            cell.paragraphs[0].paragraph_format.keep_with_next = True  # заголовок не відривається від даних
        matrix_columns = {index for index, kind in table.highlights.items() if kind is Highlight.MATRIX}
        for row in table.rows:
            document_row = document_table.add_row()
            _keep_row_together(document_row._tr)
            for position, (cell, data, width) in enumerate(zip(document_row.cells, row, widths)):
                cell.width = width
                center = not isinstance(data.value, str) or position in matrix_columns or len(data.text) <= 4
                self._write_cell(cell, data, center=center, matrix=position in matrix_columns)
        spacer = self.document.add_paragraph()
        spacer.paragraph_format.space_after = Pt(6)

    def _column_widths(self, table: Table) -> list[Cm]:
        return [Cm(width) for width in column_widths(table, self.text_width_cm)]

    @staticmethod
    def _write_cell(cell: _Cell, data: TableCell, *, center: bool, matrix: bool = False) -> None:
        paragraph = cell.paragraphs[0]
        fmt = paragraph.paragraph_format
        fmt.first_line_indent = Cm(0)
        fmt.line_spacing = 1.0
        fmt.alignment = WD_ALIGN_PARAGRAPH.CENTER if center else WD_ALIGN_PARAGRAPH.LEFT
        if matrix and data.operations is not None and data.grant_operations:
            for operation in Operation:
                if operation in data.grant_operations:
                    run = paragraph.add_run(operation.short)
                    run.font.color.rgb = _rgb(palette.GRANT_INK)
                    run.underline = True
                    run.bold = True
                elif operation in data.operations:
                    run = paragraph.add_run(operation.short)
                else:
                    run = paragraph.add_run(GAP_MARK)
                run.font.size = TABLE_SIZE
        else:
            run = paragraph.add_run(data.text)
            run.font.size = TABLE_SIZE
            run.bold = data.bold
        if data.fill:
            _shade(cell, data.fill)

    def figure(self, image: BytesIO | Path, caption: str, width_share: float = 1.0) -> None:
        """Рисунок по центру з підписом «Рисунок 2.N – …» під ним."""
        self._figures += 1
        picture = self.document.add_paragraph()
        picture.paragraph_format.first_line_indent = Cm(0)
        picture.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        picture.paragraph_format.keep_with_next = True
        picture.paragraph_format.line_spacing = 1.0
        width = Cm(self.text_width_cm * width_share)
        picture.add_run().add_picture(image if isinstance(image, BytesIO) else str(image), width=width)
        self._caption(f"Рисунок {CHAPTER}.{self._figures} – {caption}", centered=True)

    def chart(self, figure: Figure, caption: str, width_share: float = 1.0) -> None:
        """Рисунок із фігури matplotlib."""
        self.figure(_figure_png(figure), caption, width_share)


def _image(source: bytes | Path | None) -> BytesIO | Path | None:
    if isinstance(source, bytes):
        return BytesIO(source)
    return source


def _section_structure(report: _Report, result: AnalysisResult, schemes: Mapping[str, bytes | Path]) -> None:
    enterprise = result.enterprise
    critical = enterprise.critical_resources()
    report.heading(f"{CHAPTER}.1 Структурна схема системи розмежування доступу", 2)
    roles = ", ".join(
        f"«{role.name}» ({len(enterprise.users_of_role(role.id))})" for role in enterprise.roles
    )
    report.paragraph(
        f"Об'єкт моделювання — система розмежування доступу підприємства ({enterprise.name}). "
        f"Суб'єкти доступу — {len(enterprise.users)} користувачів, яким призначено одну з "
        f"{len(enterprise.roles)} ролей: {roles}. Об'єкти доступу — {len(enterprise.resources)} "
        f"інформаційних ресурсів, з них критичних — {len(critical)} "
        f"({', '.join(f'{resource.id} «{resource.name}»' for resource in critical)}). Перелік ресурсів "
        f"з коефіцієнтами критичності K наведено в табл. {report.next_table()}."
    )
    report.table(tables.resources_table(result))
    report.paragraph(
        f"Для кожного ресурсу розглянуто чотири типи операцій (табл. {report.next_table()}); "
        "вага операції характеризує її потенційну шкоду і використовується в індексі ризику."
    )
    report.table(tables.operations_table())
    report.paragraph(
        f"Користувачі, їхні посади та ролі наведено в табл. {report.next_table()}. Ефективні права "
        "користувача = права його ролі ∪ індивідуальні дозволи поза роллю."
    )
    report.table(tables.users_table(result))
    scheme = _image(schemes.get(SCHEME_INITIAL))
    if scheme is not None:
        report.paragraph(
            f"Структурну схему «Користувачі → Ролі → Ресурси» початкової моделі показано на рис. "
            f"{report.next_figure()}: ребра «роль → ресурс» підписано операціями, критичні ресурси "
            "виділено червоною рамкою, індивідуальні дозволи — червоні пунктирні ребра."
        )
        report.figure(scheme, "Структурна схема початкової моделі розмежування доступу")


def _section_initial_matrix(report: _Report, result: AnalysisResult) -> None:
    initial = result.initial
    report.heading(f"{CHAPTER}.2 Початкова матриця доступу", 2)
    report.paragraph(
        "У клітинках матриць позначено дозволені операції: Ч — читання, З — запис, Р — редагування, "
        f"В — видалення, «{GAP_MARK}» — операція заборонена. Колір клітинки відповідає "
        "найнебезпечнішій операції: сірий — доступу немає, зелений — лише читання, жовтий — запис або "
        "редагування, червоний — є видалення."
    )
    report.paragraph(
        f"Матриця ролей (табл. {report.next_table()}) містить {initial.role_stats.total} можливих "
        f"операцій, з яких дозволено {initial.role_stats.allowed}, заборонено {initial.role_stats.denied}."
    )
    report.table(tables.role_matrix_table(result, initial), "Початкова матриця доступу ролей")
    report.paragraph(
        f"Матриця ефективних прав користувачів (табл. {report.next_table()}) враховує індивідуальні "
        f"дозволи поза роллю (виділено червоними підкресленими літерами): дозволено "
        f"{initial.user_stats.allowed} із {initial.user_stats.total} операцій, заборонено {initial.user_stats.denied}."
    )
    report.table(tables.user_matrix_table(result, initial), "Початкова матриця доступу користувачів")
    report.paragraph(
        f"Індивідуальні дозволи поза роллю ({initial.individual_operations} операцій у "
        f"{initial.model.grant_user_count} користувачів) з причинами надання наведено в табл. {report.next_table()}."
    )
    report.table(tables.grants_table(result))


def _section_excess(report: _Report, result: AnalysisResult) -> None:
    counts = result.severity_counts
    report.heading(f"{CHAPTER}.3 Виявлення надлишкових і небезпечних прав", 2)
    report.paragraph(
        "Надлишкове право (знахідка) — трійка «користувач – ресурс – операція», яка є в ефективних "
        "правах початкової моделі, але відсутня в еталонній моделі мінімальних привілеїв, побудованій "
        "зі службових функцій ролей. Для кожної знахідки визначено джерело (роль чи індивідуальний "
        "дозвіл), правила, що спрацювали, рівень небезпеки (максимум серед правил) і рекомендацію. "
        f"Правила наведено в табл. {report.next_table()}."
    )
    report.table(tables.rules_table(result))
    summary = ", ".join(f"{severity.label.lower()} — {counts[severity]}" for severity in Severity)
    report.paragraph(
        f"Виявлено {len(result.findings)} надлишкових прав; за рівнями небезпеки: {summary} "
        f"(табл. {report.next_table()})."
    )
    report.table(tables.severity_summary_table(result))
    excess = sum(len(row.excess) for row in result.role_excess)
    report.paragraph(
        f"На рівні матриці ролей надлишковими є {excess} операцій (табл. {report.next_table()}); "
        f"ще {result.initial.individual_operations} надлишкових операцій надано індивідуальними дозволами."
    )
    report.table(tables.role_excess_table(result))
    report.paragraph(
        f"Повний перелік надлишкових прав наведено в табл. {report.next_table()}, рекомендації щодо "
        f"їх усунення — у табл. {report.next_table(1)}."
    )
    report.table(tables.findings_table(result, compact=True))
    report.table(tables.recommendations_table(result))
    ranking = result.risk_ranking
    top = ranking[0] if ranking else None
    if top is not None:
        report.paragraph(
            f"Ризик і рівень захищеності ресурсів наведено в табл. {report.next_table()} та на рис. "
            f"{report.next_figure()}. Найбільший ризик у початковій моделі має ресурс {top.resource_id} "
            f"«{top.resource_name}»: індекс ризику {top.risk} із {top.max_risk}, захищеність "
            f"{fmt_percent(top.protection)}."
        )
    report.table(tables.risks_table(result, detailed=False))
    report.chart(risk_figure(result), "Індекс ризику інформаційних ресурсів у початковій моделі")


def _section_optimized(report: _Report, result: AnalysisResult, schemes: Mapping[str, bytes | Path]) -> None:
    enterprise = result.enterprise
    optimized = result.optimized
    report.heading(f"{CHAPTER}.4 Оптимізована модель мінімальних привілеїв", 2)
    report.paragraph(
        "Оптимізовану модель побудовано за принципом мінімальних привілеїв: права ролі на ресурсі — "
        "об'єднання операцій, потрібних для її службових функцій; індивідуальні дозволи поза роллю "
        f"скасовано. Службові функції ролей ({function_count(enterprise)}) наведено в табл. {report.next_table()}."
    )
    report.table(tables.functions_table(result))
    if enterprise.principles:
        report.paragraph("У модель закладено такі принципи (обґрунтування):")
        for number, text in enumerate(enterprise.principles, start=1):
            report.paragraph(f"{number}) {text}")
    report.paragraph(
        f"Оптимізовану матрицю ролей наведено в табл. {report.next_table()}: дозволено "
        f"{optimized.role_stats.allowed} із {optimized.role_stats.total} операцій "
        f"(у початковій — {result.initial.role_stats.allowed})."
    )
    report.table(tables.role_matrix_table(result, optimized), "Оптимізована матриця доступу ролей")
    report.paragraph(
        f"Обґрунтування кожної зміненої клітинки матриці ролей наведено в табл. {report.next_table()}."
    )
    report.table(tables.justification_table(result))
    subset = "є підмножиною початкової — жодного нового права не надано" if result.is_subset else (
        "не є підмножиною початкової"
    )
    report.paragraph(
        f"Матриця ефективних прав користувачів оптимізованої моделі (табл. {report.next_table()}) містить "
        f"{optimized.user_stats.allowed} дозволених операцій із {optimized.user_stats.total}; модель {subset}; "
        f"порушень правил П1–П8 — {len(optimized.violations)}."
    )
    report.table(tables.user_matrix_table(result, optimized), "Оптимізована матриця доступу користувачів")
    scheme = _image(schemes.get(SCHEME_OPTIMIZED))
    if scheme is not None:
        report.paragraph(f"Структурну схему оптимізованої моделі показано на рис. {report.next_figure()}.")
        report.figure(scheme, "Структурна схема оптимізованої моделі розмежування доступу")


def _section_comparison(report: _Report, result: AnalysisResult) -> None:
    report.heading(f"{CHAPTER}.5 Порівняльний аналіз моделей", 2)
    report.paragraph(
        f"Порівняльні показники обох моделей наведено в табл. {report.next_table()}. Для відсоткових "
        "показників зміну подано у відсоткових пунктах (в. п.); зелене тло — показник змінився в бік "
        "підвищення захищеності."
    )
    report.table(tables.comparison_table(result))
    report.paragraph(
        f"Зміну кількості дозволених операцій за ролями показано на рис. {report.next_figure()}, "
        f"рівня захищеності ресурсів — на рис. {report.next_figure(1)}, теплові карти матриць "
        f"користувачів обох моделей — на рис. {report.next_figure(2)}."
    )
    report.chart(role_operations_figure(result), "Дозволені операції за ролями до та після оптимізації")
    report.chart(protection_figure(result), "Рівень захищеності ресурсів до та після оптимізації")
    report.chart(heatmaps_figure(result), "Теплові карти матриць доступу користувачів")
    report.paragraph(
        "Для оцінки наслідків компрометації облікового запису змодельовано «радіус ураження» кожного "
        "користувача: ризик операцій, доступних зловмиснику, у початковій та оптимізованій моделях "
        f"(табл. {report.next_table()})."
    )
    report.table(tables.compromise_table(result))


def _section_conclusions(report: _Report, result: AnalysisResult) -> None:
    report.heading(f"{CHAPTER}.6 Висновки", 2)
    for number, item in enumerate(result.conclusions, start=1):
        report.paragraph(f" {item.text}", bold_prefix=f"{number}. {item.title}.")


def build_report(result: AnalysisResult, schemes: Mapping[str, bytes | Path] | None = None) -> DocumentObject:
    """Будує документ звіту; schemes — PNG структурних схем («initial», «optimized»)."""
    images = schemes or {}
    report = _Report()
    report.heading(
        f"{CHAPTER} МОДЕЛЮВАННЯ СИСТЕМИ РОЗМЕЖУВАННЯ ДОСТУПУ ДО ІНФОРМАЦІЙНИХ РЕСУРСІВ ПІДПРИЄМСТВА", 1
    )
    report.paragraph(
        f"Розрахунки виконано програмою «{APP_NAME}» {date.today():%d.%m.%Y} для моделі «{result.enterprise.name}». "
        "Усі числа звіту обчислено автоматично з вихідних даних; ті самі значення відображає застосунок."
    )
    _section_structure(report, result, images)
    _section_initial_matrix(report, result)
    _section_excess(report, result)
    _section_optimized(report, result, images)
    _section_comparison(report, result)
    _section_conclusions(report, result)
    core = report.document.core_properties
    core.title = f"{APP_NAME} — {result.enterprise.name}"
    core.author = APP_NAME
    return report.document


def export_word(result: AnalysisResult, path: str | Path, schemes: Mapping[str, bytes | Path] | None = None) -> Path:
    """Зберігає звіт у файл .docx; OSError — якщо файл недоступний (напр. відкритий у Word)."""
    target = Path(path)
    if target.suffix.lower() != ".docx":
        target = target.with_suffix(".docx")
    build_report(result, schemes).save(str(target))
    return target
