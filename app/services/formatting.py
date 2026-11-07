"""Округлення та форматування чисел і фраз українською мовою.

Десятковий роздільник — кома, знак мінус — «−», між числом і «%» —
нерозривний пропуск. Округлення виконується за правилом «половина — вгору»
через Decimal, тому 15,25 → 15,3 без похибок двійкового подання чисел.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

MINUS = "−"
NBSP = " "
NO_VALUE = "—"


def _decimal(value: float | int) -> Decimal:
    """Перетворює число на Decimal без артефактів двійкового подання float."""
    return Decimal(value) if isinstance(value, int) else Decimal(repr(value))


def _quantum(digits: int) -> Decimal:
    """Крок округлення: digits = 1 → 0,1."""
    return Decimal(1).scaleb(-digits)


def round_half_up(value: float | int, digits: int = 1) -> float:
    """Округлює до digits знаків після коми за правилом «половина — вгору»."""
    return float(_decimal(value).quantize(_quantum(digits), rounding=ROUND_HALF_UP))


def percent(part: float | int, whole: float | int, digits: int = 1) -> float:
    """Частка part від whole у відсотках, округлена до digits знаків."""
    if whole == 0:
        raise ZeroDivisionError("частка від нуля не визначена")
    exact = _decimal(part) * 100 / _decimal(whole)
    return float(exact.quantize(_quantum(digits), rounding=ROUND_HALF_UP))


def fmt_number(value: float | int, digits: int = 0) -> str:
    """Число з комою як десятковим роздільником: «17,0»; від'ємне — зі знаком «−»."""
    rounded = _decimal(value).quantize(_quantum(digits), rounding=ROUND_HALF_UP)
    text = f"{abs(rounded):f}".replace(".", ",")
    return f"{MINUS}{text}" if rounded < 0 else text


def fmt_percent(value: float | int, digits: int = 1) -> str:
    """Відсоток: «17,0 %»."""
    return f"{fmt_number(value, digits)}{NBSP}%"


def fmt_signed(value: float | int, digits: int = 0) -> str:
    """Зміна зі знаком: «+35,0», «−34», «0»."""
    rounded = _decimal(value).quantize(_quantum(digits), rounding=ROUND_HALF_UP)
    text = fmt_number(value, digits)
    return f"+{text}" if rounded > 0 else text


def fmt_signed_percent(value: float | None, digits: int = 1) -> str:
    """Відносна зміна у відсотках: «−50,7 %»; None — «—» (база дорівнює нулю)."""
    if value is None:
        return NO_VALUE
    return f"{fmt_signed(value, digits)}{NBSP}%"


def plural(count: int, one: str, few: str, many: str) -> str:
    """Форма слова для числа: 1 операція, 2 операції, 5 операцій, 21 операція."""
    remainder = abs(count) % 100
    if 11 <= remainder <= 14:
        return many
    last = remainder % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def count_phrase(count: int, one: str, few: str, many: str) -> str:
    """Число разом з узгодженим словом: «14 операцій»."""
    return f"{count} {plural(count, one, few, many)}"


def join_and(items: Sequence[str]) -> str:
    """Перелік через кому з «і» перед останнім: «A, B і C»."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} і {items[-1]}"
