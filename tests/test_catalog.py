from __future__ import annotations

import pytest

from pos.services.errors import ValidationError


def _item(ctx, admin, **kwargs):
    defaults = dict(
        name="Кофе",
        kind="product",
        price=15000,
        cost=6000,
        sku="COF-1",
        initial_stock=10,
        user_id=admin.id,
    )
    defaults.update(kwargs)
    return ctx.catalog.create_item(**defaults)


def test_catalog_and_stock(ctx, admin):
    category = ctx.catalog.create_category("Напитки", "product")
    item = _item(ctx, admin, category_id=category.id)
    assert item.stock == 10
    assert ctx.catalog.stock_balance(item.id) == 10

    assert ctx.catalog.add_stock_movement(item.id, 5, "receipt", admin.id, "Приход") == 15
    assert ctx.catalog.set_stock(item.id, 7, admin.id) == 7
    with pytest.raises(ValidationError):
        ctx.catalog.add_stock_movement(item.id, -100, "writeoff", admin.id)
    assert ctx.catalog.stock_balance(item.id) == 7

    movements = ctx.catalog.stock_movements(item_id=item.id)
    assert len(movements) == 3  # initial, receipt, adjustment, no failed write-off


def test_category_kind_validation(ctx, admin):
    category = ctx.catalog.create_category("Услуги", "service")
    with pytest.raises(ValidationError):
        _item(ctx, admin, category_id=category.id, kind="product", sku="X")


def test_duplicate_sku(ctx, admin):
    _item(ctx, admin, sku="DUP")
    with pytest.raises(ValidationError):
        _item(ctx, admin, name="Другой", sku="DUP")


def test_price_list_override(ctx, admin):
    item = _item(ctx, admin, price=10000)
    base_list = ctx.catalog.list_price_lists()[0]
    assert ctx.catalog.effective_price(item.id) == 10000
    ctx.catalog.set_price_list_item(base_list.id, item.id, 8000)
    assert ctx.catalog.effective_price(item.id) == 8000
    sellable = next(entry for entry in ctx.catalog.sellable_items() if entry.id == item.id)
    assert sellable.price == 8000

    second = ctx.catalog.create_price_list("Оптовый")
    ctx.catalog.set_active_price_list(second.id)
    assert ctx.catalog.effective_price(item.id) == 10000
    with pytest.raises(ValidationError):
        ctx.catalog.delete_price_list(second.id)

    ctx.catalog.set_active_price_list(base_list.id)
    ctx.catalog.delete_price_list(second.id)
    with pytest.raises(ValidationError):
        ctx.catalog.delete_price_list(base_list.id)


def test_service_has_no_stock(ctx, admin):
    service = ctx.catalog.create_item(
        name="Доставка", kind="service", price=30000, cost=10000, user_id=admin.id
    )
    assert service.track_stock is False
    with pytest.raises(ValidationError):
        ctx.catalog.add_stock_movement(service.id, 1, "receipt", admin.id)


def test_service_consumables_are_shared_and_validated(ctx, admin):
    paper = ctx.catalog.create_item(
        name="Бумага Снегурочка",
        kind="product",
        cost=250,
        unit="лист",
        initial_stock=2500,
        user_id=admin.id,
        is_consumable=True,
    )
    regular = _item(ctx, admin, name="Обычный товар", sku="REG-1", initial_stock=5)
    copy_bw = ctx.catalog.create_item(
        name="Копия ч/б",
        kind="service",
        price=500,
        user_id=admin.id,
        consumables=[(paper.id, 1)],
    )
    copy_color = ctx.catalog.create_item(
        name="Копия цветная",
        kind="service",
        price=2000,
        user_id=admin.id,
    )
    ctx.catalog.set_service_consumables(copy_color.id, [(paper.id, 1), (paper.id, 2)])

    assert paper.is_consumable and paper.track_stock
    assert ctx.catalog.stock_balance(paper.id) == 2500
    assert [(item.id, qty) for item, qty in ctx.catalog.service_consumables(copy_bw.id)] == [
        (paper.id, 1)
    ]
    assert [(item.id, qty) for item, qty in ctx.catalog.service_consumables(copy_color.id)] == [
        (paper.id, 3)
    ]

    sellable_ids = {item.id for item in ctx.catalog.sellable_items()}
    assert paper.id not in sellable_ids
    assert copy_bw.id in sellable_ids
    assert ctx.catalog.consumable_items()[0].id == paper.id

    with pytest.raises(ValidationError):
        ctx.catalog.set_service_consumables(copy_bw.id, [(regular.id, 1)])
    with pytest.raises(ValidationError):
        ctx.catalog.set_service_consumables(paper.id, [(paper.id, 1)])
    with pytest.raises(ValidationError):
        ctx.catalog.set_service_consumables(copy_bw.id, [(paper.id, 0)])
    with pytest.raises(ValidationError):
        ctx.catalog.delete_item(paper.id)
    with pytest.raises(ValidationError):
        ctx.catalog.update_item(
            paper.id,
            name=paper.name,
            kind="product",
            price=0,
            cost=250,
            is_consumable=False,
        )

    ctx.catalog.set_service_consumables(copy_bw.id, [])
    assert ctx.catalog.service_consumables(copy_bw.id) == []
    assert ctx.catalog.stock_balance(paper.id) == 2500
