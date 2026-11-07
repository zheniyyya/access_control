"""Єдина палітра кольорів: GUI, діаграми matplotlib та експорт (Excel, Word).

Кольори рівнів (немає доступу / лише читання / запис-редагування / видалення,
рівні небезпеки та захищеності) — статусні. Вони ніколи не несуть зміст самі
по собі: поруч завжди є підпис (літери операцій, назва рівня). Статусна трійка
зелений / жовтий / червоний перевірена валідатором палітр: розділення сусідніх
кольорів для протанопії та дейтеранопії ΔE ≥ 11.
"""

from __future__ import annotations

from app.services.analyzer import Severity
from app.services.matrix import CellLevel
from app.services.risk import ProtectionLevel

# Поверхні, лінії та «чорнило» тексту.
SURFACE = "#fcfcfb"
PAGE = "#f4f4f2"
WHITE = "#ffffff"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
AXIS = "#c3c2b7"
TRACK = "#ecebe7"  # «доріжка»: максимально можливе значення під стовпчиком
ACCENT = "#2a78d6"
ACCENT_SOFT = "#cde2fb"

# Статусні кольори (фіксовані).
STATUS_GOOD = "#0ca30c"
STATUS_WARNING = "#fab219"
STATUS_SERIOUS = "#ec835a"
STATUS_CRITICAL = "#d03b3b"

# Індивідуальні дозволи: «чорнило» літер і позначки в матриці (контраст ≥ 5:1 на всіх фонах).
GRANT_INK = "#9b1c1c"

# Порівняння «до / після»: початкова модель — нейтральний сірий контекст,
# оптимізована — акцент. Поруч завжди є легенда й підписи значень.
BEFORE = INK_MUTED
AFTER = ACCENT

# Матриця змін: «чорнило» збережених операцій і тло змінених клітинок.
KEPT_INK = "#0b6e0b"


def hex_to_rgb(color: str) -> tuple[int, int, int]:
    """Перетворює «#rrggbb» на кортеж (r, g, b)."""
    value = color.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def tint(color: str, share: float, base: str = SURFACE) -> str:
    """Світлий відтінок: частка share кольору color на тлі base."""
    mixed = (
        round(channel * share + background * (1 - share))
        for channel, background in zip(hex_to_rgb(color), hex_to_rgb(base))
    )
    return "#" + "".join(f"{channel:02x}" for channel in mixed)


# Клітинки матриць: лінія/акцент і світлий фон під літерами «ЧЗРВ».
CELL_STROKE: dict[CellLevel, str] = {
    CellLevel.NONE: AXIS,
    CellLevel.READ: STATUS_GOOD,
    CellLevel.MODIFY: STATUS_WARNING,
    CellLevel.DELETE: STATUS_CRITICAL,
}
CELL_FILL: dict[CellLevel, str] = {
    CellLevel.NONE: TRACK,
    CellLevel.READ: tint(STATUS_GOOD, 0.28),
    CellLevel.MODIFY: tint(STATUS_WARNING, 0.35),
    CellLevel.DELETE: tint(STATUS_CRITICAL, 0.28),
}
# Тло зміненої клітинки в матриці змін (вилучені або додані операції).
CHANGED_FILL = tint(STATUS_CRITICAL, 0.10)

# Рівні небезпеки знахідок.
SEVERITY_STROKE: dict[Severity, str] = {
    Severity.CRITICAL: STATUS_CRITICAL,
    Severity.HIGH: STATUS_SERIOUS,
    Severity.MEDIUM: STATUS_WARNING,
    Severity.LOW: INK_MUTED,
}
SEVERITY_FILL: dict[Severity, str] = {
    Severity.CRITICAL: tint(STATUS_CRITICAL, 0.28),
    Severity.HIGH: tint(STATUS_SERIOUS, 0.30),
    Severity.MEDIUM: tint(STATUS_WARNING, 0.35),
    Severity.LOW: TRACK,
}

# Рівні захищеності ресурсів.
PROTECTION_STROKE: dict[ProtectionLevel, str] = {
    ProtectionLevel.HIGH: STATUS_GOOD,
    ProtectionLevel.MEDIUM: STATUS_WARNING,
    ProtectionLevel.LOW: STATUS_CRITICAL,
}
PROTECTION_FILL: dict[ProtectionLevel, str] = {
    ProtectionLevel.HIGH: tint(STATUS_GOOD, 0.28),
    ProtectionLevel.MEDIUM: tint(STATUS_WARNING, 0.35),
    ProtectionLevel.LOW: tint(STATUS_CRITICAL, 0.28),
}
