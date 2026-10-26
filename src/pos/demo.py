"""Create demo users and a small catalog for trying the POS.

Usage:
    uv run python -m pos.demo
"""

from __future__ import annotations

import sys

from .config import AppPaths
from .context import AppContext
from .database import Database


def seed_demo(ctx: AppContext) -> None:
    if ctx.users.count_users() > 0:
        print("В базе уже есть пользователи — демо-данные не добавлены.")
        return
    admin = ctx.users.create_user(
        "admin", "admin123", "Администратор", role="admin"
    )
    seller = ctx.users.create_user(
        "seller",
        "seller123",
        "Продавец Анна",
        role="seller",
        permissions={"manage_stock", "view_stats", "manage_catalog"},
    )
    drinks = ctx.catalog.create_category("Напитки", "product", 10)
    bakery = ctx.catalog.create_category("Выпечка", "product", 20)
    services = ctx.catalog.create_category("Услуги", "service", 30)
    materials = ctx.catalog.create_category("Расходники", "product", 40)
    items = [
        ("Кофе американо", "COF-001", "product", drinks.id, 15000, 6000, 40),
        ("Кофе латте", "COF-002", "product", drinks.id, 22000, 9000, 30),
        ("Чай чёрный", "TEA-001", "product", drinks.id, 12000, 3500, 25),
        ("Круассан", "BAK-001", "product", bakery.id, 14000, 6000, 18),
        ("Круассан с миндалём", "BAK-002", "product", bakery.id, 19000, 8500, 10),
        ("Доставка", "SRV-001", "service", services.id, 30000, 10000, 0),
    ]
    for name, sku, kind, category_id, price, cost, stock in items:
        ctx.catalog.create_item(
            name=name,
            sku=sku,
            kind=kind,
            category_id=category_id,
            price=price,
            cost=cost,
            initial_stock=stock,
            user_id=admin.id,
        )

    paper = ctx.catalog.create_item(
        name="Бумага Снегурочка A4",
        sku="PAP-A4",
        kind="product",
        category_id=materials.id,
        price=0,
        cost=250,
        unit="лист",
        initial_stock=2500,
        user_id=admin.id,
        is_consumable=True,
    )
    copy_bw = ctx.catalog.create_item(
        name="Копия ч/б",
        sku="CPY-BW",
        kind="service",
        category_id=services.id,
        price=500,
        cost=0,
        user_id=admin.id,
    )
    copy_color = ctx.catalog.create_item(
        name="Копия цветная",
        sku="CPY-COLOR",
        kind="service",
        category_id=services.id,
        price=2000,
        cost=0,
        user_id=admin.id,
    )
    for service in (copy_bw, copy_color):
        ctx.catalog.set_service_consumables(service.id, [(paper.id, 1)])
    print("Демо-данные созданы.")
    print("Администратор: admin / admin123")
    print(f"Продавец:      seller / seller123 (id {seller.id})")


def main() -> int:
    paths = AppPaths.create()
    db = Database(paths.db_path, paths.backup_dir)
    try:
        db.connect()
        ctx = AppContext.create(paths, db)
        seed_demo(ctx)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
