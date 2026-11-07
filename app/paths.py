"""Шляхи до файлів застосунку з урахуванням збирання PyInstaller."""

from __future__ import annotations

import sys
from pathlib import Path


def app_base_dir() -> Path:
    """Повертає кореневу теку застосунку.

    Після збирання PyInstaller файли даних розпаковуються в тимчасову теку
    ``sys._MEIPASS``; під час запуску з вихідного коду — це тека проєкту.
    """
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        return Path(bundle_dir)
    return Path(__file__).resolve().parent.parent


def resource_path(relative: str | Path) -> Path:
    """Повертає абсолютний шлях до файлу даних застосунку (напр. ``data/variant7.json``)."""
    return app_base_dir() / relative
