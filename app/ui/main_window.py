"""Головне вікно: меню, панель інструментів, вкладки та рядок стану з ключовими числами."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QUrl
from PySide6.QtGui import QAction, QCloseEvent, QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStyle,
    QTabWidget,
    QToolBar,
    QToolButton,
)

from app import APP_NAME, APP_VERSION
from app.domain.seed import load_variant7, variant7_path
from app.export.excel_export import export_excel
from app.export.word_report import export_word
from app.services.analysis import AnalysisResult
from app.services.analyzer import Severity
from app.services.formatting import fmt_percent
from app.storage.json_repo import ModelFileError, load_enterprise, save_enterprise
from app.ui.dialogs import UnsavedChoice, ask_unsaved_changes
from app.ui.exporting import save_all_figures, scheme_images
from app.ui.state import ModelState
from app.ui.tabs.base import ResultTab
from app.ui.tabs.comparison_tab import ComparisonTab
from app.ui.tabs.data_tab import DataTab
from app.ui.tabs.matrix_tab import MatrixTab
from app.ui.tabs.optimization_tab import OptimizationTab
from app.ui.tabs.risk_tab import RiskTab
from app.ui.tabs.scheme_tab import SchemeTab
from app.ui.tabs.simulation_tab import SimulationTab

MIN_WIDTH = 1280
MIN_HEIGHT = 800
PREFERRED_WIDTH = 1440
PREFERRED_HEIGHT = 900
MODEL_FILTER = "Модель доступу (*.json);;Усі файли (*)"
STARTUP_TITLE = "Варіант №7 (вихідні дані)"
EXCEL_FILE_NAME = "Результати_варіант_7.xlsx"
WORD_FILE_NAME = "Звіт_варіант_7.docx"


class MainWindow(QMainWindow):
    """Головне вікно застосунку."""

    def __init__(self, state: ModelState) -> None:
        super().__init__()
        self._state = state
        self._last_export_dir: Path | None = None
        self._tabs = QTabWidget()
        self._pages: list[tuple[str, ResultTab]] = [
            ("Вихідні дані", DataTab(state)),
            ("Структурна схема", SchemeTab(state)),
            ("Початкова матриця", MatrixTab(state)),
            ("Аналіз ризиків", RiskTab(state)),
            ("Оптимізація", OptimizationTab(state)),
            ("Порівняння", ComparisonTab(state)),
            ("Моделювання", SimulationTab(state)),
        ]
        for number, (title, page) in enumerate(self._pages, start=1):
            index = self._tabs.addTab(page, title)
            self._tabs.setTabToolTip(index, f"Ctrl+{number}")
            shortcut = QShortcut(QKeySequence(f"Ctrl+{number}"), self)
            shortcut.activated.connect(lambda position=index: self._tabs.setCurrentIndex(position))
        self.setCentralWidget(self._tabs)
        self._create_actions()
        self._create_menus()
        self._create_toolbar()
        self._status_labels = [QLabel() for _ in range(3)]
        for label in self._status_labels:
            self.statusBar().addPermanentWidget(label)
        self._apply_window_size()
        state.changed.connect(self._update_status)
        state.meta_changed.connect(self._update_meta)
        self._update_status(state.result)
        self._update_meta()

    @property
    def tabs(self) -> QTabWidget:
        """Віджет вкладок."""
        return self._tabs

    def _action(
        self,
        text: str,
        handler: Callable[[], object],
        *,
        icon: QStyle.StandardPixmap | None = None,
        shortcut: QKeySequence | QKeySequence.StandardKey | str | None = None,
        tip: str = "",
    ) -> QAction:
        action = QAction(text, self)
        if icon is not None:
            action.setIcon(self.style().standardIcon(icon))
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        if tip:
            action.setToolTip(tip)
            action.setStatusTip(tip)
        action.triggered.connect(lambda _checked=False: handler())
        return action

    def _create_actions(self) -> None:
        pixmap = QStyle.StandardPixmap
        self._open_action = self._action(
            "Відкрити модель…", self._open, icon=pixmap.SP_DialogOpenButton,
            shortcut=QKeySequence.StandardKey.Open, tip="Відкрити збережену модель (JSON)",
        )
        self._save_action = self._action(
            "Зберегти модель", self._save, icon=pixmap.SP_DialogSaveButton,
            shortcut=QKeySequence.StandardKey.Save, tip="Зберегти поточну модель у файл JSON",
        )
        self._save_as_action = self._action(
            "Зберегти модель як…", self._save_as, shortcut="Ctrl+Shift+S",
            tip="Зберегти модель в інший файл",
        )
        self._reset_action = self._action(
            "Скинути до варіанту 7", self._reset, icon=pixmap.SP_BrowserReload,
            tip="Повернути вихідні дані варіанту №7",
        )
        self._undo_action = self._action(
            "Скасувати", self._state.undo, icon=pixmap.SP_ArrowBack,
            shortcut=QKeySequence.StandardKey.Undo, tip="Скасувати останню зміну моделі (Ctrl+Z)",
        )
        self._redo_action = self._action(
            "Повторити", self._state.redo, icon=pixmap.SP_ArrowForward,
            shortcut="Ctrl+Y", tip="Повторити скасовану зміну (Ctrl+Y)",
        )
        self._excel_action = self._action(
            "Експорт у Excel", self._export_excel, icon=pixmap.SP_FileDialogDetailedView,
            shortcut="Ctrl+E", tip="Зберегти матриці, надлишкові права, порівняння й ризики у файл Excel",
        )
        self._word_action = self._action(
            "Звіт Word", self._export_word, icon=pixmap.SP_FileIcon,
            shortcut="Ctrl+R", tip="Сформувати звіт для пояснювальної записки (Word)",
        )
        self._charts_action = self._action(
            "Зберегти діаграми", self._save_figures, icon=pixmap.SP_DirIcon,
            tip="Зберегти діаграми (PNG) і структурні схеми (PNG, SVG) у вибрану теку",
        )
        self._exit_action = self._action("Вихід", self.close, shortcut="Ctrl+Q")
        self._about_action = self._action("Про програму", self._about, icon=pixmap.SP_MessageBoxInformation)

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu("Файл")
        file_menu.addActions([self._open_action, self._save_action, self._save_as_action])
        file_menu.addSeparator()
        file_menu.addAction(self._reset_action)
        file_menu.addSeparator()
        file_menu.addAction(self._exit_action)
        export_menu = self.menuBar().addMenu("Експорт")
        export_menu.addActions([self._excel_action, self._word_action, self._charts_action])
        edit_menu = self.menuBar().addMenu("Правка")
        edit_menu.addActions([self._undo_action, self._redo_action])
        help_menu = self.menuBar().addMenu("Довідка")
        help_menu.addAction(self._about_action)

    def _create_toolbar(self) -> None:
        toolbar = QToolBar("Основні дії")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.addActions([self._open_action, self._save_action, self._reset_action])
        toolbar.addSeparator()
        toolbar.addActions([self._excel_action, self._word_action, self._charts_action])
        toolbar.addSeparator()
        toolbar.addActions([self._undo_action, self._redo_action])
        # «Скасувати» / «Повторити» — лише значки (назва й комбінація клавіш — у підказці).
        for action in (self._undo_action, self._redo_action):
            button = toolbar.widgetForAction(action)
            if isinstance(button, QToolButton):
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        self.addToolBar(toolbar)

    def _apply_window_size(self) -> None:
        """Мінімум 1280×800 (або весь доступний екран, якщо він менший)."""
        screen = self.screen() or QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        width = min(MIN_WIDTH, available.width())
        height = min(MIN_HEIGHT, available.height())
        self.setMinimumSize(width, height)
        self.resize(
            max(width, min(PREFERRED_WIDTH, available.width() - 40)),
            max(height, min(PREFERRED_HEIGHT, available.height() - 40)),
        )

    def _update_status(self, result: AnalysisResult) -> None:
        initial, optimized = result.initial, result.optimized
        critical = result.severity_counts[Severity.CRITICAL]
        items = [
            (
                f"Операцій: {initial.user_stats.allowed} → {optimized.user_stats.allowed}",
                f"Дозволені операції користувачів (із {initial.user_stats.total}): "
                "початкова → оптимізована модель",
            ),
            (
                f"Надлишкових прав: {len(result.findings)}",
                f"Надлишкових прав у початковій моделі: {len(result.findings)}, з них критичних — {critical}",
            ),
            (
                f"Захищеність: {fmt_percent(initial.critical.protection)} → "
                f"{fmt_percent(optimized.critical.protection)}",
                f"Захищеність критичних ресурсів: {fmt_percent(initial.critical.protection)} → "
                f"{fmt_percent(optimized.critical.protection)}; усіх ресурсів: "
                f"{fmt_percent(initial.overall.protection)} → {fmt_percent(optimized.overall.protection)}",
            ),
        ]
        for label, (text, tip) in zip(self._status_labels, items):
            label.setText(text)
            label.setToolTip(tip)

    def _update_meta(self) -> None:
        path = self._state.file_path
        self.setWindowTitle(f"{path.name if path else STARTUP_TITLE}[*] — {APP_NAME}")
        self.setWindowModified(self._state.is_dirty)
        self._undo_action.setEnabled(self._state.can_undo)
        self._redo_action.setEnabled(self._state.can_redo)

    def _start_directory(self) -> str:
        path = self._state.file_path
        if path is not None and not self._is_bundled(path):
            return str(path.parent)
        return QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)

    @staticmethod
    def _is_bundled(path: Path) -> bool:
        """Чи це файл вихідних даних застосунку (його не перезаписуємо)."""
        try:
            return path.resolve() == variant7_path().resolve()
        except OSError:
            return False

    def _confirm_discard(self, action: str) -> bool:
        """True — можна продовжувати (зміни збережено або їх відкинуто)."""
        if not self._state.is_dirty:
            return True
        choice = ask_unsaved_changes(self, action)
        if choice is UnsavedChoice.SAVE:
            return self._save()
        return choice is UnsavedChoice.DISCARD

    def _open(self) -> None:
        if not self._confirm_discard("відкрити іншу модель"):
            return
        path, _ = QFileDialog.getOpenFileName(self, "Відкрити модель", self._start_directory(), MODEL_FILTER)
        if not path:
            return
        try:
            enterprise = load_enterprise(path)
        except ModelFileError as exc:
            QMessageBox.critical(self, "Не вдалося відкрити модель", str(exc))
            return
        self._state.load(enterprise, Path(path))
        self.statusBar().showMessage(f"Відкрито модель: {path}", 6000)

    def _save(self) -> bool:
        path = self._state.file_path
        if path is None or self._is_bundled(path):
            return self._save_as()
        return self._write(path)

    def _save_as(self) -> bool:
        path = self._state.file_path
        if path is not None and not self._is_bundled(path):
            suggested = str(path)
        else:
            suggested = str(Path(self._start_directory()) / "model_variant7.json")
        chosen, _ = QFileDialog.getSaveFileName(self, "Зберегти модель", suggested, MODEL_FILTER)
        if not chosen:
            return False
        target = Path(chosen)
        if target.suffix.lower() != ".json":
            target = target.with_suffix(".json")
        if self._is_bundled(target):
            QMessageBox.warning(
                self, "Збереження", "Файл вихідних даних варіанту 7 не перезаписується — оберіть інше ім'я."
            )
            return False
        return self._write(target)

    def _write(self, path: Path) -> bool:
        try:
            save_enterprise(self._state.enterprise, path)
        except ModelFileError as exc:
            QMessageBox.critical(self, "Не вдалося зберегти модель", str(exc))
            return False
        self._state.mark_saved(path)
        self.statusBar().showMessage(f"Модель збережено: {path}", 6000)
        return True

    def _reset(self) -> None:
        if not self._confirm_discard("скинути модель до варіанту 7"):
            return
        try:
            enterprise = load_variant7()
        except ModelFileError as exc:
            QMessageBox.critical(self, "Не вдалося завантажити вихідні дані", str(exc))
            return
        self._state.load(enterprise, None)
        self.statusBar().showMessage("Модель скинуто до вихідних даних варіанту №7", 6000)

    def _export_directory(self) -> Path:
        """Тека для збереження звітів: остання використана або «Документи»."""
        if self._last_export_dir is not None:
            return self._last_export_dir
        return Path(self._start_directory())

    def _run_export(self, title: str, job: Callable[[], object]) -> bool:
        """Виконує експорт з курсором очікування; помилки файлів показує повідомленням."""
        error: OSError | None = None
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            job()
        except OSError as exc:
            error = exc
        finally:
            QApplication.restoreOverrideCursor()
        if error is not None:
            QMessageBox.critical(
                self,
                title,
                f"Не вдалося зберегти: {error}\n\nМожливо, файл відкрито в іншій програмі "
                "або немає дозволу на запис у цю теку.",
            )
            return False
        return True

    def _offer_open(self, title: str, text: str, target: Path) -> None:
        """Повідомлення про успіх із кнопкою «Відкрити»."""
        self.statusBar().showMessage(text, 8000)
        box = QMessageBox(QMessageBox.Icon.Information, title, text, parent=self)
        open_button = box.addButton("Відкрити", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Закрити", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() == open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def _ask_export_path(self, caption: str, file_name: str, file_filter: str, suffix: str) -> Path | None:
        chosen, _ = QFileDialog.getSaveFileName(
            self, caption, str(self._export_directory() / file_name), file_filter
        )
        if not chosen:
            return None
        target = Path(chosen)
        if target.suffix.lower() != suffix:
            target = target.with_suffix(suffix)
        self._last_export_dir = target.parent
        return target

    def _export_excel(self) -> None:
        target = self._ask_export_path("Експорт у Excel", EXCEL_FILE_NAME, "Книга Excel (*.xlsx)", ".xlsx")
        if target is None:
            return
        if self._run_export("Експорт у Excel", lambda: export_excel(self._state.result, target)):
            self._offer_open("Експорт у Excel", f"Результати збережено у файл:\n{target}", target)

    def _export_word(self) -> None:
        target = self._ask_export_path("Звіт Word", WORD_FILE_NAME, "Документ Word (*.docx)", ".docx")
        if target is None:
            return
        result = self._state.result
        if self._run_export("Звіт Word", lambda: export_word(result, target, scheme_images(result))):
            self._offer_open("Звіт Word", f"Звіт збережено у файл:\n{target}", target)

    def _save_figures(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Тека для діаграм і схем", str(self._export_directory())
        )
        if not chosen:
            return
        folder = Path(chosen)
        self._last_export_dir = folder
        saved: list[Path] = []
        if self._run_export("Зберегти діаграми", lambda: saved.extend(save_all_figures(self._state.result, folder))):
            self._offer_open(
                "Зберегти діаграми", f"Збережено файлів: {len(saved)} (діаграми PNG, схеми PNG і SVG)\nТека: {folder}",
                folder,
            )

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "Про програму",
            f"<b>{APP_NAME}</b><br>Версія {APP_VERSION}<br><br>"
            "Курсова робота, варіант №7: моделювання системи розмежування доступу "
            "до інформаційних ресурсів підприємства (RBAC, принцип мінімальних привілеїв).<br><br>"
            "Python, PySide6, matplotlib, openpyxl, python-docx.",
        )

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._confirm_discard("закрити програму"):
            event.accept()
        else:
            event.ignore()
