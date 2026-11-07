"""Вихідні дані варіанту №7: завантаження та скидання моделі до початкового стану."""

from __future__ import annotations

from pathlib import Path

from app.domain.models import Enterprise
from app.paths import resource_path
from app.storage.json_repo import load_enterprise

VARIANT7_FILE = Path("data") / "variant7.json"


def variant7_path() -> Path:
    """Шлях до файлу вихідних даних (працює і після збирання PyInstaller)."""
    return resource_path(VARIANT7_FILE)


def load_variant7() -> Enterprise:
    """Завантажує вихідні дані варіанту №7; ModelFileError — якщо файл відсутній чи пошкоджений."""
    return load_enterprise(variant7_path())
