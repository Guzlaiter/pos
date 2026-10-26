"""Plain-text receipts and printable shift reports."""

from __future__ import annotations

from ..models import Sale, ShiftSummary
from .settings import SettingsService

WIDTH = 44


def _line(left: str, right: str = "") -> str:
    if not right:
        return left[:WIDTH]
    space = WIDTH - len(left) - len(right)
    if space < 1:
        left = left[: max(0, WIDTH - len(right) - 1)]
        space = max(1, WIDTH - len(left) - len(right))
    return f"{left}{' ' * space}{right}"


def _header(settings: SettingsService) -> list[str]:
    lines = [settings.company_name.center(WIDTH)]
    address = settings.get("company_address", "").strip()
    phone = settings.get("company_phone", "").strip()
    if address:
        lines.append(address.center(WIDTH))
    if phone:
        lines.append(f"тел. {phone}".center(WIDTH))
    return lines


def build_sale_receipt(sale: Sale, settings: SettingsService) -> str:
    currency = settings.currency
    lines = _header(settings)
    lines.append("=" * WIDTH)
    lines.append(f"Чек № {sale.number}")
    lines.append(f"Смена № {sale.shift_id}   Кассир: {sale.user_name}")
    lines.append(sale.created_at)
    lines.append("-" * WIDTH)
    for index, line in enumerate(sale.lines, start=1):
        lines.append(f"{index}. {line.name}"[:WIDTH])
        lines.append(
            _line(
                f"   {line.qty} x {_money(line.unit_price, currency)}",
                _money(line.line_total, currency),
            )
        )
    lines.append("-" * WIDTH)
    lines.append(_line("ИТОГО", _money(sale.total, currency)))
    lines.append("Оплата:")
    for payment in sale.payments:
        lines.append(_line(f"  {payment.method_name}", _money(payment.amount, currency)))
    if sale.note:
        lines.append("-" * WIDTH)
        lines.append(sale.note)
    lines.append("=" * WIDTH)
    footer = settings.receipt_footer.strip()
    if footer:
        for part in footer.splitlines():
            lines.append(part.center(WIDTH))
    return "\n".join(lines)


def build_preview_receipt(
    lines: list[tuple[str, int, int, int]],
    total: int,
    cashier: str,
    settings: SettingsService,
) -> str:
    """Build a preview receipt from ``(name, qty, price, total)`` tuples."""
    currency = settings.currency
    out = _header(settings)
    out.append("=" * WIDTH)
    out.append("ПРЕДВАРИТЕЛЬНЫЙ ПРОСМОТР".center(WIDTH))
    out.append(f"Кассир: {cashier}")
    out.append("-" * WIDTH)
    for index, (name, qty, price, line_total) in enumerate(lines, start=1):
        out.append(f"{index}. {name}"[:WIDTH])
        out.append(
            _line(
                f"   {qty} x {_money(price, currency)}",
                _money(line_total, currency),
            )
        )
    out.append("-" * WIDTH)
    out.append(_line("ИТОГО", _money(total, currency)))
    out.append("=" * WIDTH)
    out.append("Чек будет сохранён после оплаты.".center(WIDTH))
    return "\n".join(out)


def build_shift_report(summary: ShiftSummary, settings: SettingsService) -> str:
    currency = settings.currency
    shift = summary.shift
    lines = _header(settings)
    lines.append("=" * WIDTH)
    lines.append("ОТЧЁТ ПО СМЕНЕ".center(WIDTH))
    lines.append("=" * WIDTH)
    lines.append(f"Смена № {shift.id}")
    lines.append(f"Продавец: {shift.user_name}")
    lines.append(f"Открыта:  {shift.opened_at}")
    lines.append(f"Закрыта:  {shift.closed_at or '—'}")
    lines.append("-" * WIDTH)
    lines.append(_line("Выручка", _money(summary.revenue, currency)))
    lines.append(_line("Прибыль", _money(summary.profit, currency)))
    lines.append(_line("Чеков", str(summary.sales_count)))
    lines.append(_line("Продано единиц", str(summary.items_sold)))
    lines.append(_line("Средний чек", _money(summary.avg_check, currency)))
    lines.append("-" * WIDTH)
    lines.append("ОПЛАТЫ")
    for payment in summary.payments:
        lines.append(_line(f"  {payment.method_name} ({payment.count})", _money(payment.amount, currency)))
    lines.append("-" * WIDTH)
    lines.append("КАССА")
    lines.append(_line("Размен на начало", _money(shift.opening_cash, currency)))
    lines.append(_line("Ожидалось наличных", _money(summary.cash_expected, currency)))
    if summary.cash_counted is not None:
        lines.append(_line("Фактически в кассе", _money(summary.cash_counted, currency)))
        lines.append(_line("Расхождение", _money(summary.cash_difference or 0, currency)))
    lines.append("-" * WIDTH)
    lines.append("ТОП ПО ПРИБЫЛИ")
    if not summary.top_items:
        lines.append("  Нет продаж")
    for index, item in enumerate(summary.top_items[:10], start=1):
        lines.append(f"{index}. {item.name}"[:WIDTH])
        lines.append(
            _line(
                f"   {item.qty} шт, выручка {_money(item.revenue, currency)}",
                _money(item.profit, currency),
            )
        )
    lines.append("-" * WIDTH)
    lines.append("МЕСЯЦ")
    lines.append(_line("Выручка за месяц", _money(summary.month_revenue, currency)))
    lines.append(_line("Прибыль за месяц", _money(summary.month_profit, currency)))
    if summary.month_top_profit:
        item = summary.month_top_profit
        lines.append(f"Лидер по прибыли: {item.name}"[:WIDTH])
        lines.append(_line("  прибыль", _money(item.profit, currency)))
    if summary.month_top_revenue:
        item = summary.month_top_revenue
        lines.append(f"Лидер по выручке: {item.name}"[:WIDTH])
        lines.append(_line("  выручка", _money(item.revenue, currency)))
    if shift.note:
        lines.append("-" * WIDTH)
        lines.append(shift.note)
    lines.append("=" * WIDTH)
    return "\n".join(lines)


def _money(cents: int, currency: str) -> str:
    return _format_money(cents, currency)


def _format_money(cents: int, currency: str) -> str:
    # Local import avoids a module cycle with money at import time? It is safe,
    # but keeping one canonical implementation is important.
    from ..money import format_money

    return format_money(cents, currency)
