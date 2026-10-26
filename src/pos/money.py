"""Money helpers.

All monetary values are stored as integer cents (копейки) to avoid
floating point rounding errors.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

_CENT = Decimal("0.01")


def format_money(
    cents: int | None,
    currency: str = "₽",
    *,
    with_currency: bool = True,
) -> str:
    """Format integer cents as a human readable string: ``1 234,50 ₽``."""
    cents = int(cents or 0)
    sign = "−" if cents < 0 else ""
    value = (Decimal(abs(cents)) / 100).quantize(_CENT)
    text = f"{value:,.2f}".replace(",", "\u202f").replace(".", ",")
    if with_currency and currency:
        return f"{sign}{text}\u00a0{currency}"
    return f"{sign}{text}"


def format_plain(cents: int | None) -> str:
    """Format cents without currency, suitable for input widgets."""
    return format_money(cents, with_currency=False).replace("\u202f", "").replace("\u00a0", "")


def parse_money(value: object, *, units: str = "rub") -> int:
    """Parse a legacy/source value into integer cents.

    ``units`` may be ``"rub"`` (source stores rubles, e.g. ``123.45``) or
    ``"cents"`` (source already stores integer cents).
    """
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, Decimal)):
        dec = Decimal(str(value))
    else:
        text = str(value).strip()
        if not text:
            return 0
        text = (
            text.replace("\u00a0", " ")
            .replace("\u202f", " ")
            .replace(" ", "")
            .replace("\t", "")
        )
        text = re.sub(r"(?i)(₽|руб\.?|р\.|rub|rur)", "", text).strip()
        if not text:
            return 0
        if units == "cents":
            try:
                return int(Decimal(text.replace(",", ".")).to_integral_value(rounding=ROUND_HALF_UP))
            except InvalidOperation as exc:
                raise ValueError(f"Некорректная сумма: {value!r}") from exc
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
        try:
            dec = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"Некорректная сумма: {value!r}") from exc

    if units == "cents":
        return int(dec.to_integral_value(rounding=ROUND_HALF_UP))
    return int((dec * 100).to_integral_value(rounding=ROUND_HALF_UP))


def parse_int(value: object, default: int = 0) -> int:
    """Parse an integer quantity, tolerating spaces and trailing units."""
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    text = str(value).strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
    if not text:
        return default
    match = re.match(r"^[+-]?\d+(?:\.\d+)?", text)
    if not match:
        raise ValueError(f"Некорректное количество: {value!r}")
    return int(round(Decimal(match.group(0))))


def parse_bool(value: object, default: bool = True) -> bool:
    """Parse boolean-like legacy values (1/0, да/нет, yes/no, ...)."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().casefold()
    if not text:
        return default
    if text in {"1", "true", "yes", "y", "да", "есть", "истина", "+"}:
        return True
    if text in {"0", "false", "no", "n", "нет", "ложь", "-"}:
        return False
    return default
