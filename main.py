"""Точка входу: python main.py — «Моделювання системи розмежування доступу» (варіант №7)."""

from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from app import APP_NAME, APP_VERSION
from app.domain.models import Enterprise
from app.domain.seed import load_variant7
from app.export.excel_export import export_excel
from app.export.word_report import export_word
from app.storage.json_repo import ModelFileError, load_enterprise
from app.ui.exporting import save_all_figures, scheme_images
from app.ui.main_window import MODEL_FILTER, MainWindow
from app.ui.state import ModelState
from app.ui.tabs.base import ResultTab
from app.ui.theme import apply_theme, install_translations

SELF_TEST_FLAG = "--self-test"


def _set_windows_app_id() -> None:
    """Власна іконка на панелі задач Windows (замість значка python.exe)."""
    if sys.platform != "win32":
        return
    import ctypes

    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("kursova.access-control")
    except (AttributeError, OSError):
        pass


def _load_start_model() -> tuple[Enterprise, Path | None] | None:
    """Вихідні дані варіанту №7; якщо файл пошкоджено — пропонує відкрити інший."""
    try:
        return load_variant7(), None
    except ModelFileError as exc:
        message = str(exc)
    while True:
        answer = QMessageBox.question(
            None,
            "Не вдалося завантажити вихідні дані",
            f"{message}\n\nВідкрити інший файл моделі?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None
        path, _ = QFileDialog.getOpenFileName(None, "Відкрити модель", "", MODEL_FILTER)
        if not path:
            return None
        try:
            return load_enterprise(path), Path(path)
        except ModelFileError as exc:
            message = str(exc)


def main() -> int:
    """Запускає застосунок; повертає код завершення."""
    _set_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    install_translations(app)
    apply_theme(app)
    loaded = _load_start_model()
    if loaded is None:
        return 1
    enterprise, path = loaded
    state = ModelState(enterprise, path)
    window = MainWindow(state)
    if SELF_TEST_FLAG in sys.argv:
        return _self_test(window, state)
    window.show()
    return app.exec()


def _self_test(window: MainWindow, state: ModelState) -> int:
    """Перевірка збірки без участі користувача: усі вкладки й експорт у тимчасову теку.

    Повертає 0, якщо все вдалося, інакше 1 (опис помилки — у self_test.log поруч із .exe).
    """
    log = Path(sys.executable if getattr(sys, "frozen", False) else __file__).with_name("self_test.log")
    try:
        for index in range(window.tabs.count()):
            page = window.tabs.widget(index)
            if isinstance(page, ResultTab):
                page.ensure_current()
        result = state.result
        with tempfile.TemporaryDirectory() as folder:
            export_excel(result, Path(folder) / "test.xlsx")
            export_word(result, Path(folder) / "test.docx", scheme_images(result))
            figures = save_all_figures(result, Path(folder) / "figures")
        log.write_text(
            f"OK: дозволено {result.initial.user_stats.allowed} → {result.optimized.user_stats.allowed}, "
            f"знахідок {len(result.findings)}, рисунків {len(figures)}\n",
            encoding="utf-8",
        )
        return 0
    except Exception:  # noqa: BLE001 — самоперевірка має записати будь-яку помилку
        log.write_text(traceback.format_exc(), encoding="utf-8")
        return 1


if __name__ == "__main__":
    sys.exit(main())
