from __future__ import annotations

from datetime import date

from pos.models import PaymentInput, SaleLineInput


def _sale(ctx, admin, shift_id, cash_id, item, qty, price):
    return ctx.sales.create_sale(
        user_id=admin.id,
        shift_id=shift_id,
        lines=[SaleLineInput(item_id=item.id, qty=qty, unit_price=price)],
        payments=[PaymentInput(method_id=cash_id, amount=qty * price)],
    )


def test_month_stats_and_shift_summary(ctx, admin):
    coffee = ctx.catalog.create_item(
        name="Кофе", price=15000, cost=5000, initial_stock=100, user_id=admin.id
    )
    tea = ctx.catalog.create_item(
        name="Чай", price=10000, cost=8000, initial_stock=100, user_id=admin.id
    )
    cash_id = ctx.payments.list_methods()[0].id
    shift = ctx.shifts.open_shift(admin.id, 0)
    _sale(ctx, admin, shift.id, cash_id, coffee, 3, 15000)
    _sale(ctx, admin, shift.id, cash_id, tea, 10, 10000)

    today = date.today()
    stats = ctx.stats.month_stats(today.year, today.month)
    assert stats.revenue == 145000
    assert stats.profit == 50000
    assert stats.sales_count == 2
    assert stats.items_sold == 13
    assert stats.top_profit is not None and stats.top_profit.name == "Кофе"
    assert stats.top_profit.profit == 30000
    assert stats.top_revenue is not None and stats.top_revenue.name == "Чай"
    assert stats.avg_check == 72500
    assert len(stats.daily) >= 28
    assert stats.payments[0].amount == 145000

    summary = ctx.stats.shift_summary(shift.id)
    assert summary.revenue == 145000
    assert summary.profit == 50000
    assert summary.month_revenue == 145000
    assert summary.month_top_profit.name == "Кофе"
    assert summary.month_top_revenue.name == "Чай"

    overview = ctx.stats.shifts_overview()
    assert overview
    row = overview[0]
    assert int(row["id"]) == shift.id
    assert int(row["revenue"]) == 145000
    assert int(row["sales_count"]) == 2

    today_stats = ctx.stats.today_stats()
    assert today_stats.revenue == 145000
