"""Оформлення застосунку: стиль Fusion, світла палітра, шрифти, переклад і іконка."""

from __future__ import annotations

from PySide6.QtCore import QLibraryInfo, QLocale, QPointF, Qt, QTranslator
from PySide6.QtGui import QColor, QFont, QFontDatabase, QIcon, QPainter, QPainterPath, QPalette, QPixmap
from PySide6.QtWidgets import QApplication

from app import palette

BASE_POINT_SIZE = 10
_MONOSPACE_FAMILIES = ("Consolas", "Cascadia Mono", "DejaVu Sans Mono")

STYLESHEET = f"""
QToolBar {{
    spacing: 4px; padding: 4px 6px; border: none;
    border-bottom: 1px solid {palette.GRIDLINE}; background: {palette.SURFACE};
}}
QToolButton {{ padding: 4px 8px; border-radius: 4px; }}
QToolButton:hover {{ background: {palette.ACCENT_SOFT}; }}
QTabWidget::pane {{
    border: 1px solid {palette.GRIDLINE}; border-radius: 4px;
    background: {palette.SURFACE}; top: -1px;
}}
QTabBar::tab {{
    padding: 6px 16px; margin-right: 2px; border: 1px solid {palette.GRIDLINE};
    border-bottom: none; border-top-left-radius: 4px; border-top-right-radius: 4px;
    background: {palette.PAGE}; color: {palette.INK_SECONDARY};
}}
QTabBar::tab:selected {{ background: {palette.SURFACE}; color: {palette.INK}; }}
QGroupBox {{
    border: 1px solid {palette.GRIDLINE}; border-radius: 6px; margin-top: 12px;
    padding: 10px 6px 6px 6px; background: {palette.SURFACE};
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {palette.INK_SECONDARY};
}}
QHeaderView::section {{
    background: {palette.PAGE}; color: {palette.INK_SECONDARY}; padding: 4px 6px; border: none;
    border-right: 1px solid {palette.GRIDLINE}; border-bottom: 1px solid {palette.GRIDLINE};
}}
QTableView {{
    gridline-color: {palette.GRIDLINE};
    selection-background-color: {palette.ACCENT_SOFT}; selection-color: {palette.INK};
}}
QStatusBar {{ background: {palette.SURFACE}; border-top: 1px solid {palette.GRIDLINE}; }}
QStatusBar QLabel {{ padding: 0 6px; color: {palette.INK_SECONDARY}; }}
QLabel[role="hint"] {{ color: {palette.INK_MUTED}; }}
"""


def light_palette() -> QPalette:
    """Світла палітра Qt (незалежно від темної теми Windows)."""
    result = QPalette()
    window, base, text = QColor(palette.PAGE), QColor(palette.WHITE), QColor(palette.INK)
    roles = {
        QPalette.ColorRole.Window: window,
        QPalette.ColorRole.WindowText: text,
        QPalette.ColorRole.Base: base,
        QPalette.ColorRole.AlternateBase: QColor("#f7f7f5"),
        QPalette.ColorRole.Text: text,
        QPalette.ColorRole.Button: window,
        QPalette.ColorRole.ButtonText: text,
        QPalette.ColorRole.ToolTipBase: base,
        QPalette.ColorRole.ToolTipText: text,
        QPalette.ColorRole.Highlight: QColor(palette.ACCENT),
        QPalette.ColorRole.HighlightedText: QColor(palette.WHITE),
        QPalette.ColorRole.PlaceholderText: QColor(palette.INK_MUTED),
        QPalette.ColorRole.Link: QColor(palette.ACCENT),
        QPalette.ColorRole.Light: QColor(palette.WHITE),
        QPalette.ColorRole.Midlight: QColor(palette.TRACK),
        QPalette.ColorRole.Mid: QColor(palette.AXIS),
        QPalette.ColorRole.Dark: QColor("#a3a19a"),
        QPalette.ColorRole.Shadow: QColor("#6f6d66"),
    }
    for role, color in roles.items():
        result.setColor(role, color)
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.ButtonText,
    ):
        result.setColor(QPalette.ColorGroup.Disabled, role, QColor(palette.INK_MUTED))
    return result


def install_translations(app: QApplication) -> None:
    """Підключає український переклад стандартних діалогів і кнопок Qt (якщо є)."""
    QLocale.setDefault(QLocale(QLocale.Language.Ukrainian, QLocale.Country.Ukraine))
    translator = QTranslator(app)
    directory = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if translator.load(QLocale(), "qtbase", "_", directory):
        app.installTranslator(translator)


def apply_theme(app: QApplication) -> None:
    """Стиль Fusion, світла палітра, шрифт інтерфейсу та іконка вікна."""
    app.setStyle("Fusion")
    hints = app.styleHints()
    if hasattr(hints, "setColorScheme"):
        hints.setColorScheme(Qt.ColorScheme.Light)
    app.setPalette(light_palette())
    font = app.font()
    font.setPointSize(BASE_POINT_SIZE)
    app.setFont(font)
    app.setStyleSheet(STYLESHEET)
    app.setWindowIcon(app_icon())


def monospace_font(point_size: float = 11.0, bold: bool = True) -> QFont:
    """Моноширинний шрифт для клітинок «ЧЗРВ» (однакова ширина літер)."""
    families = QFontDatabase.families()
    family = next((name for name in _MONOSPACE_FAMILIES if name in families), None)
    font = QFont(family) if family else QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    font.setPointSizeF(point_size)
    font.setBold(bold)
    return font


def _icon_pixmap(size: int) -> QPixmap:
    """Іконка застосунку: щит із замковою щілиною."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    scale = size / 64.0
    shield = QPainterPath()
    shield.moveTo(32 * scale, 4 * scale)
    shield.lineTo(56 * scale, 13 * scale)
    shield.lineTo(56 * scale, 30 * scale)
    shield.cubicTo(56 * scale, 46 * scale, 45 * scale, 56 * scale, 32 * scale, 61 * scale)
    shield.cubicTo(19 * scale, 56 * scale, 8 * scale, 46 * scale, 8 * scale, 30 * scale)
    shield.lineTo(8 * scale, 13 * scale)
    shield.closeSubpath()
    keyhole = QPainterPath()
    keyhole.moveTo(28.5 * scale, 31 * scale)
    keyhole.lineTo(35.5 * scale, 31 * scale)
    keyhole.lineTo(37 * scale, 46 * scale)
    keyhole.lineTo(27 * scale, 46 * scale)
    keyhole.closeSubpath()
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(palette.ACCENT))
    painter.drawPath(shield)
    painter.setBrush(QColor(palette.WHITE))
    painter.drawEllipse(QPointF(32 * scale, 27 * scale), 7 * scale, 7 * scale)
    painter.drawPath(keyhole)
    painter.end()
    return pixmap


def app_icon() -> QIcon:
    """Іконка застосунку в кількох розмірах."""
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(_icon_pixmap(size))
    return icon
