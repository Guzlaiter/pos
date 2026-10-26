from __future__ import annotations

import sqlite3

import pytest

from pos.context import AppContext
from pos.database import Database
from pos.models import PaymentInput, SaleLineInput
from pos.services.errors import SaleError, ValidationError


def _catalog(ctx, admin):
    coffee = ctx.catalog.create_item(
        name="Кофе",
        kind="product",
        price=15000,
        cost=6000,
        sku="COF",
        initial_stock=10,
        user_id=admin.id,
    )
    delivery = ctx.catalog.create_item(
        name="Доставка",
        kind="service",
        price=30000,
        cost=10000,
        sku="DEL",
        user_id=admin.id,
    )
    return coffee, delivery


def _method_ids(ctx):
    methods = {method.kind: method.id for method in ctx.payments.list_methods()}
    return methods["cash"], methods["qr"]


def test_multi_payment_sale_and_shift_close(ctx, admin):
    coffee, delivery = _catalog(ctx, admin)
    shift = ctx.shifts.open_shift(admin.id, opening_cash=10000)
    cash_id, qr_id = _method_ids(ctx)

    sale = ctx.sales.create_sale(
        user_id=admin.id,
        shift_id=shift.id,
        lines=[
            SaleLineInput(item_id=coffee.id, qty=2, unit_price=15000),
            SaleLineInput(item_id=delivery.id, qty=1, unit_price=30000),
        ],
        payments=[
            PaymentInput(method_id=cash_id, amount=20000),
            PaymentInput(method_id=qr_id, amount=40000),
        ],
    )
    assert sale.total == 60000
    assert len(sale.payments) == 2
    assert sale.number.endswith(f"{sale.id:04d}")
    assert ctx.catalog.stock_balance(coffee.id) == 8
    assert ctx.catalog.stock_balance(delivery.id) == 0

    summary = ctx.stats.shift_summary(shift.id)
    assert summary.revenue == 60000
    assert summary.profit == 38000
    assert summary.sales_count == 1
    assert summary.items_sold == 3
    assert summary.cash_expected == 30000
    assert {p.method_name for p in summary.payments} == {"Наличные", "QR-код"}
    assert summary.top_items[0].name == "Доставка"
    assert summary.month_revenue >= 60000
    assert summary.month_top_profit is not None

    closed = ctx.shifts.close_shift(shift.id, 30500, admin.id, "проверка")
    assert closed.status == "closed"
    assert closed.expected_cash == 30000
    assert closed.cash_difference == 500

    with pytest.raises(SaleError):
        ctx.sales.create_sale(
            user_id=admin.id,
            shift_id=shift.id,
            lines=[SaleLineInput(item_id=coffee.id, qty=1)],
            payments=[PaymentInput(method_id=cash_id, amount=15000)],
        )


def test_payment_mismatch_rolls_back(ctx, admin):
    coffee, _ = _catalog(ctx, admin)
    shift = ctx.shifts.open_shift(admin.id)
    cash_id, _ = _method_ids(ctx)
    with pytest.raises(SaleError):
        ctx.sales.create_sale(
            user_id=admin.id,
            shift_id=shift.id,
            lines=[SaleLineInput(item_id=coffee.id, qty=2, unit_price=15000)],
            payments=[PaymentInput(method_id=cash_id, amount=10000)],
        )
    assert ctx.db.table_count("sales") == 0
    assert ctx.catalog.stock_balance(coffee.id) == 10


def test_insufficient_stock_rolls_back(ctx, admin):
    coffee, _ = _catalog(ctx, admin)
    shift = ctx.shifts.open_shift(admin.id)
    cash_id, _ = _method_ids(ctx)
    with pytest.raises(SaleError):
        ctx.sales.create_sale(
            user_id=admin.id,
            shift_id=shift.id,
            lines=[SaleLineInput(item_id=coffee.id, qty=11, unit_price=15000)],
            payments=[PaymentInput(method_id=cash_id, amount=165000)],
        )
    assert ctx.db.table_count("sales") == 0
    assert ctx.catalog.stock_balance(coffee.id) == 10


def test_crash_during_sale_keeps_shift_and_stock_consistent(ctx, admin, monkeypatch):
    coffee, _ = _catalog(ctx, admin)
    shift = ctx.shifts.open_shift(admin.id, opening_cash=5000)
    cash_id, _ = _method_ids(ctx)
    original_execute = ctx.db.execute

    def failing_execute(sql, params=()):
        if "INSERT INTO shift_events" in sql and "'sale'" in sql:
            raise sqlite3.OperationalError("simulated power loss")
        return original_execute(sql, params)

    monkeypatch.setattr(ctx.db, "execute", failing_execute)
    with pytest.raises(SaleError):
        ctx.sales.create_sale(
            user_id=admin.id,
            shift_id=shift.id,
            lines=[SaleLineInput(item_id=coffee.id, qty=1, unit_price=15000)],
            payments=[PaymentInput(method_id=cash_id, amount=15000)],
        )
    monkeypatch.setattr(ctx.db, "execute", original_execute)

    assert ctx.db.table_count("sales") == 0
    assert ctx.catalog.stock_balance(coffee.id) == 10
    still_open = ctx.shifts.open_shift_for_user(admin.id)
    assert still_open is not None and still_open.id == shift.id
    summary = ctx.stats.shift_summary(shift.id)
    assert summary.revenue == 0
    assert summary.cash_expected == 5000


def test_zero_total_sale_without_payment(ctx, admin):
    free = ctx.catalog.create_item(
        name="Пробник", kind="product", price=0, cost=0, initial_stock=3, user_id=admin.id
    )
    shift = ctx.shifts.open_shift(admin.id)
    sale = ctx.sales.create_sale(
        user_id=admin.id,
        shift_id=shift.id,
        lines=[SaleLineInput(item_id=free.id, qty=1, unit_price=0)],
        payments=[],
    )
    assert sale.total == 0
    assert sale.payments == []
    assert ctx.catalog.stock_balance(free.id) == 2


def test_shift_survives_reconnect(paths, ctx, admin):
    coffee, _ = _catalog(ctx, admin)
    shift = ctx.shifts.open_shift(admin.id, opening_cash=1000)
    cash_id, _ = _method_ids(ctx)
    ctx.sales.create_sale(
        user_id=admin.id,
        shift_id=shift.id,
        lines=[SaleLineInput(item_id=coffee.id, qty=1, unit_price=15000)],
        payments=[PaymentInput(method_id=cash_id, amount=15000)],
    )
    ctx.db.close()

    db = Database(paths.db_path, paths.backup_dir)
    db.connect()
    try:
        reopened = AppContext.create(paths, db)
        open_shift = reopened.shifts.open_shift_for_user(admin.id)
        assert open_shift is not None
        assert open_shift.id == shift.id
        summary = reopened.stats.shift_summary(shift.id)
        assert summary.revenue == 15000
        assert summary.cash_expected == 16000
        assert reopened.catalog.stock_balance(coffee.id) == 9
        reopened.shifts.close_shift(shift.id, 16000, admin.id)
        assert db.quick_check()[0]
        assert db.latest_backup() is not None
    finally:
        db.close()


def test_services_consume_shared_consumable(ctx, admin):
    paper = ctx.catalog.create_item(
        name="Бумага Снегурочка A4",
        kind="product",
        price=0,
        cost=250,
        unit="лист",
        initial_stock=10,
        user_id=admin.id,
        is_consumable=True,
    )
    copy_bw = ctx.catalog.create_item(
        name="Копия ч/б",
        kind="service",
        price=500,
        cost=0,
        user_id=admin.id,
        consumables=[(paper.id, 1)],
    )
    copy_color = ctx.catalog.create_item(
        name="Копия цветная",
        kind="service",
        price=2000,
        cost=0,
        user_id=admin.id,
        consumables=[(paper.id, 2)],
    )
    shift = ctx.shifts.open_shift(admin.id)
    cash_id, _ = _method_ids(ctx)

    sale = ctx.sales.create_sale(
        user_id=admin.id,
        shift_id=shift.id,
        lines=[
            SaleLineInput(item_id=copy_bw.id, qty=2),
            SaleLineInput(item_id=copy_color.id, qty=1),
        ],
        payments=[PaymentInput(method_id=cash_id, amount=3000)],
    )

    assert sale.total == 3000
    assert ctx.catalog.stock_balance(paper.id) == 6
    movements = ctx.db.query(
        "SELECT * FROM stock_movements WHERE item_id=? AND kind='consumable'",
        (paper.id,),
    )
    assert len(movements) == 1
    assert int(movements[0]["qty"]) == -4
    assert int(movements[0]["ref_id"]) == sale.id
    assert "Копия ч/б" in movements[0]["note"]
    assert "Копия цветная" in movements[0]["note"]

    # Consumable cost is included in the service cost snapshot and profit.
    costs = {
        row["name_snapshot"]: int(row["cost"])
        for row in ctx.db.query(
            "SELECT name_snapshot, cost FROM sale_items WHERE sale_id=?", (sale.id,)
        )
    }
    assert costs == {"Копия ч/б": 250, "Копия цветная": 500}
    summary = ctx.stats.shift_summary(shift.id)
    assert summary.profit == 2000


def test_service_can_use_several_consumables(ctx, admin):
    paper = ctx.catalog.create_item(
        name="Бумага",
        kind="product",
        cost=250,
        unit="лист",
        initial_stock=10,
        user_id=admin.id,
        is_consumable=True,
    )
    toner = ctx.catalog.create_item(
        name="Тонер",
        kind="product",
        cost=1000,
        unit="мл",
        initial_stock=5,
        user_id=admin.id,
        is_consumable=True,
    )
    service = ctx.catalog.create_item(
        name="Печать документа",
        kind="service",
        price=5000,
        user_id=admin.id,
        consumables=[(paper.id, 2), (toner.id, 1)],
    )
    shift = ctx.shifts.open_shift(admin.id)
    cash_id, _ = _method_ids(ctx)

    ctx.sales.create_sale(
        user_id=admin.id,
        shift_id=shift.id,
        lines=[SaleLineInput(item_id=service.id, qty=2)],
        payments=[PaymentInput(method_id=cash_id, amount=10000)],
    )

    assert ctx.catalog.stock_balance(paper.id) == 6
    assert ctx.catalog.stock_balance(toner.id) == 3
    summary = ctx.stats.shift_summary(shift.id)
    assert summary.profit == 7000


def test_insufficient_consumable_rolls_back_sale(ctx, admin):
    paper = ctx.catalog.create_item(
        name="Бумага",
        kind="product",
        cost=250,
        unit="лист",
        initial_stock=3,
        user_id=admin.id,
        is_consumable=True,
    )
    copy_color = ctx.catalog.create_item(
        name="Копия цветная",
        kind="service",
        price=2000,
        user_id=admin.id,
        consumables=[(paper.id, 2)],
    )
    shift = ctx.shifts.open_shift(admin.id)
    cash_id, _ = _method_ids(ctx)

    with pytest.raises(SaleError):
        ctx.sales.create_sale(
            user_id=admin.id,
            shift_id=shift.id,
            lines=[SaleLineInput(item_id=copy_color.id, qty=2)],
            payments=[PaymentInput(method_id=cash_id, amount=4000)],
        )

    assert ctx.db.table_count("sales") == 0
    assert ctx.catalog.stock_balance(paper.id) == 3


def test_consumable_cannot_be_sold_directly(ctx, admin):
    paper = ctx.catalog.create_item(
        name="Бумага",
        kind="product",
        cost=250,
        initial_stock=10,
        user_id=admin.id,
        is_consumable=True,
    )
    shift = ctx.shifts.open_shift(admin.id)
    cash_id, _ = _method_ids(ctx)
    with pytest.raises(SaleError):
        ctx.sales.create_sale(
            user_id=admin.id,
            shift_id=shift.id,
            lines=[SaleLineInput(item_id=paper.id, qty=1, unit_price=500)],
            payments=[PaymentInput(method_id=cash_id, amount=500)],
        )
    assert ctx.catalog.stock_balance(paper.id) == 10


def test_cannot_sell_into_foreign_shift(ctx, admin, seller):
    coffee, _ = _catalog(ctx, admin)
    shift = ctx.shifts.open_shift(seller.id)
    cash_id, _ = _method_ids(ctx)
    with pytest.raises(SaleError):
        ctx.sales.create_sale(
            user_id=admin.id,
            shift_id=shift.id,
            lines=[SaleLineInput(item_id=coffee.id, qty=1, unit_price=15000)],
            payments=[PaymentInput(method_id=cash_id, amount=15000)],
        )
