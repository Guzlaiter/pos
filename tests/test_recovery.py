from __future__ import annotations

import sqlite3

import pytest

from pos.context import AppContext
from pos.database import Database
from pos.models import PaymentInput, SaleLineInput
from pos.services.errors import ShiftError


def _item(ctx, admin, name="Кофе", price=15000, cost=5000, stock=10):
    return ctx.catalog.create_item(
        name=name,
        kind="product",
        price=price,
        cost=cost,
        initial_stock=stock,
        user_id=admin.id,
    )


def _sale(ctx, admin, shift_id, item, qty, payments):
    return ctx.sales.create_sale(
        user_id=admin.id,
        shift_id=shift_id,
        lines=[SaleLineInput(item_id=item.id, qty=qty, unit_price=item.price)],
        payments=payments,
    )


def _method_ids(ctx):
    return {method.kind: method.id for method in ctx.payments.list_methods()}


def test_open_shift_survives_reconnect_and_resumes(ctx, admin):
    item = _item(ctx, admin)
    cash = _method_ids(ctx)["cash"]
    shift = ctx.shifts.open_shift(admin.id, opening_cash=50000)
    _sale(ctx, admin, shift.id, item, 2, [PaymentInput(method_id=cash, amount=30000)])
    ctx.shifts.mark_resumed(shift.id)

    db_path = ctx.paths.db_path
    backup_dir = ctx.paths.backup_dir
    ctx.db.close()

    db = Database(db_path, backup_dir)
    db.connect()
    restored_ctx = AppContext.create(ctx.paths, db)
    try:
        restored = restored_ctx.shifts.open_shift_for_user(admin.id)
        assert restored is not None
        assert restored.id == shift.id
        assert restored.is_open

        events = [row["kind"] for row in restored_ctx.shifts.events(shift.id)]
        assert events == ["opened", "sale", "resumed"]

        assert restored_ctx.shifts.expected_cash(shift.id) == 80000
        summary = restored_ctx.stats.shift_summary(shift.id)
        assert summary.revenue == 30000
        assert summary.sales_count == 1

        assert db.quick_check()[0]
        assert db.table_count("sales") == 1
        assert db.table_count("shifts") == 1
    finally:
        db.close()


def test_close_shift_recomputes_cash_and_creates_backup(ctx, admin):
    item = _item(ctx, admin)
    ids = _method_ids(ctx)
    shift = ctx.shifts.open_shift(admin.id, opening_cash=10000)
    _sale(
        ctx,
        admin,
        shift.id,
        item,
        1,
        [
            PaymentInput(method_id=ids["cash"], amount=5000),
            PaymentInput(method_id=ids["qr"], amount=10000),
        ],
    )

    assert ctx.shifts.expected_cash(shift.id) == 15000
    closed = ctx.shifts.close_shift(shift.id, counted_cash=14500, closed_by_user_id=admin.id)
    assert not closed.is_open
    assert closed.expected_cash == 15000
    assert closed.closing_cash == 14500
    assert closed.cash_difference == -500

    events = ctx.shifts.events(shift.id)
    assert [row["kind"] for row in events] == ["opened", "sale", "closed"]
    assert ctx.db.query_one(
        "SELECT COUNT(*) AS n FROM shifts WHERE status='open'"
    )["n"] == 0

    backups = list(ctx.paths.backup_dir.glob(f"pos-*-shift-{shift.id}-closed.db"))
    assert backups

    with pytest.raises(ShiftError):
        ctx.shifts.close_shift(shift.id, 0, admin.id)

    # A closed shift no longer blocks the user, and the next shift starts clean.
    next_shift = ctx.shifts.open_shift(admin.id, opening_cash=0)
    assert next_shift.id != shift.id
    assert ctx.shifts.expected_cash(next_shift.id) == 0


def test_backup_is_a_consistent_readable_snapshot(ctx, admin):
    _item(ctx, admin, name="До копии", stock=3)
    backup = ctx.db.backup(tag="test")
    assert backup is not None
    assert backup.is_file()

    _item(ctx, admin, name="После копии", stock=1)

    conn = sqlite3.connect(str(backup))
    try:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        names = {
            row[0] for row in conn.execute("SELECT name FROM items").fetchall()
        }
    finally:
        conn.close()
    assert names == {"До копии"}

    assert ctx.db.latest_backup() is not None
    assert ctx.db.quick_check()[0]
    assert ctx.db.integrity_check()[0]


def test_backup_pruning_keeps_configured_number(ctx, admin):
    ctx.settings.set("backup_keep", 3)
    for index in range(5):
        assert ctx.db.backup(tag=f"prune-{index}") is not None
    files = list(ctx.paths.backup_dir.glob("pos-*.db"))
    assert 0 < len(files) <= 3
