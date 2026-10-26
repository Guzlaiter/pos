"""Catalog: categories, items, price lists and stock."""

from __future__ import annotations

import sqlite3
from typing import Any

from ..database import Database
from ..models import Category, Item, PriceList
from .errors import ValidationError
from .settings import SettingsService

STOCK_KIND_LABELS = {
    "initial": "Начальный остаток",
    "receipt": "Приход",
    "sale": "Продажа",
    "consumable": "Расходник по услуге",
    "return": "Возврат",
    "writeoff": "Списание",
    "adjustment": "Корректировка",
    "import": "Импорт",
}


class CatalogService:
    def __init__(self, db: Database, settings: SettingsService | None = None):
        self.db = db
        self.settings = settings or SettingsService(db)

    # -------------------------------------------------------------- categories
    @staticmethod
    def _category(row: sqlite3.Row) -> Category:
        return Category(
            id=int(row["id"]),
            name=str(row["name"]),
            kind=str(row["kind"]),
            sort_order=int(row["sort_order"]),
            is_active=bool(row["is_active"]),
        )

    def categories(self, include_inactive: bool = True) -> list[Category]:
        sql = "SELECT * FROM categories"
        if not include_inactive:
            sql += " WHERE is_active=1"
        sql += " ORDER BY sort_order, name"
        return [self._category(row) for row in self.db.query(sql)]

    def get_category(self, category_id: int) -> Category | None:
        row = self.db.query_one("SELECT * FROM categories WHERE id=?", (category_id,))
        return self._category(row) if row else None

    def create_category(
        self, name: str, kind: str = "any", sort_order: int = 0, is_active: bool = True
    ) -> Category:
        name = (name or "").strip()
        if not name:
            raise ValidationError("Укажите название категории")
        if kind not in ("any", "product", "service"):
            raise ValidationError("Некорректный тип категории")
        try:
            with self.db.transaction():
                cursor = self.db.execute(
                    "INSERT INTO categories(name, kind, sort_order, is_active) "
                    "VALUES (?, ?, ?, ?)",
                    (name, kind, int(sort_order), int(is_active)),
                )
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"Категория «{name}» уже существует") from exc
        category = self.get_category(int(cursor.lastrowid))
        assert category is not None
        return category

    def update_category(
        self,
        category_id: int,
        name: str,
        kind: str,
        sort_order: int,
        is_active: bool,
    ) -> Category:
        name = (name or "").strip()
        if not name:
            raise ValidationError("Укажите название категории")
        if kind not in ("any", "product", "service"):
            raise ValidationError("Некорректный тип категории")
        try:
            with self.db.transaction():
                self.db.execute(
                    "UPDATE categories SET name=?, kind=?, sort_order=?, is_active=? "
                    "WHERE id=?",
                    (name, kind, int(sort_order), int(is_active), category_id),
                )
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"Категория «{name}» уже существует") from exc
        category = self.get_category(category_id)
        if category is None:
            raise ValidationError("Категория не найдена")
        return category

    def delete_category(self, category_id: int) -> None:
        with self.db.transaction():
            # Items keep working; their category becomes empty (ON DELETE SET NULL).
            self.db.execute("DELETE FROM categories WHERE id=?", (category_id,))

    # ------------------------------------------------------------------- items
    @staticmethod
    def _item(row: sqlite3.Row, price_override: int | None = None) -> Item:
        return Item(
            id=int(row["id"]),
            name=str(row["name"]),
            sku=str(row["sku"]) if row["sku"] else None,
            kind=str(row["kind"]),
            category_id=int(row["category_id"]) if row["category_id"] else None,
            category_name=str(row["category_name"]) if row["category_name"] else None,
            price=int(price_override if price_override is not None else row["price"]),
            cost=int(row["cost"]),
            unit=str(row["unit"] or "шт"),
            track_stock=bool(row["track_stock"]),
            is_active=bool(row["is_active"]),
            is_consumable=bool(row["is_consumable"]),
            stock=int(row["stock"] or 0),
        )

    _ITEM_SELECT = """
        SELECT i.*, c.name AS category_name, COALESCE(v.qty, 0) AS stock
        FROM items i
        LEFT JOIN categories c ON c.id = i.category_id
        LEFT JOIN item_stock v ON v.item_id = i.id
    """

    def items(self, include_inactive: bool = False) -> list[Item]:
        sql = self._ITEM_SELECT
        if not include_inactive:
            sql += " WHERE i.is_active=1"
        sql += " ORDER BY i.name"
        return [self._item(row) for row in self.db.query(sql)]

    def consumable_items(self, include_inactive: bool = False) -> list[Item]:
        sql = self._ITEM_SELECT + " WHERE i.is_consumable=1"
        if not include_inactive:
            sql += " AND i.is_active=1"
        sql += " ORDER BY i.name"
        return [self._item(row) for row in self.db.query(sql)]

    def get_item(self, item_id: int) -> Item | None:
        row = self.db.query_one(self._ITEM_SELECT + " WHERE i.id=?", (item_id,))
        return self._item(row) if row else None

    def get_item_by_sku(self, sku: str) -> Item | None:
        row = self.db.query_one(self._ITEM_SELECT + " WHERE i.sku=?", (sku,))
        return self._item(row) if row else None

    def sellable_items(self) -> list[Item]:
        """Active items with the effective price from the active price list."""
        price_list_id = self.settings.active_price_list_id
        sql = """
            SELECT i.*, c.name AS category_name, COALESCE(v.qty, 0) AS stock,
                   COALESCE(pl.price, i.price) AS effective_price
            FROM items i
            LEFT JOIN categories c ON c.id = i.category_id
            LEFT JOIN item_stock v ON v.item_id = i.id
            LEFT JOIN price_list_items pl
                   ON pl.item_id = i.id AND pl.price_list_id = ?
            WHERE i.is_active=1
              AND i.is_consumable=0
            ORDER BY i.kind, i.name
        """
        return [
            self._item(row, int(row["effective_price"]))
            for row in self.db.query(sql, (price_list_id,))
        ]

    def effective_price(self, item_id: int) -> int | None:
        price_list_id = self.settings.active_price_list_id
        row = self.db.query_one(
            """
            SELECT COALESCE(pl.price, i.price) AS price
            FROM items i
            LEFT JOIN price_list_items pl
                   ON pl.item_id = i.id AND pl.price_list_id = ?
            WHERE i.id=?
            """,
            (price_list_id, item_id),
        )
        return int(row["price"]) if row else None

    def _validate_item(
        self,
        name: str,
        kind: str,
        category_id: int | None,
        price: int,
        cost: int,
        sku: str | None,
    ) -> tuple[str, str | None]:
        name = (name or "").strip()
        if not name:
            raise ValidationError("Укажите название товара или услуги")
        if kind not in ("product", "service"):
            raise ValidationError("Некорректный тип позиции")
        if price < 0 or cost < 0:
            raise ValidationError("Цена и себестоимость не могут быть отрицательными")
        if cost > price:
            # Allowed (clearance), but never silently; UI shows a hint.
            pass
        if category_id is not None:
            category = self.get_category(category_id)
            if category is None:
                raise ValidationError("Категория не найдена")
            if category.kind != "any" and category.kind != kind:
                raise ValidationError(
                    "Категория предназначена для другого типа позиции"
                )
        sku = (sku or "").strip() or None
        return name, sku

    def create_item(
        self,
        *,
        name: str,
        kind: str = "product",
        price: int = 0,
        cost: int = 0,
        sku: str | None = None,
        category_id: int | None = None,
        unit: str = "шт",
        track_stock: bool = True,
        is_active: bool = True,
        initial_stock: int = 0,
        user_id: int | None = None,
        is_consumable: bool = False,
        consumables: list[tuple[int, int]] | None = None,
    ) -> Item:
        name, sku = self._validate_item(name, kind, category_id, price, cost, sku)
        if is_consumable and kind != "product":
            raise ValidationError("Расходником может быть только товар")
        if is_consumable:
            track_stock = True
        track_stock = bool(track_stock) and kind == "product"
        if initial_stock < 0:
            raise ValidationError("Начальный остаток не может быть отрицательным")
        try:
            with self.db.transaction():
                cursor = self.db.execute(
                    """
                    INSERT INTO items(sku, name, kind, category_id, price, cost, unit,
                                      track_stock, is_consumable, is_active, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                    """,
                    (
                        sku,
                        name,
                        kind,
                        category_id,
                        int(price),
                        int(cost),
                        (unit or "шт").strip() or "шт",
                        int(track_stock),
                        int(bool(is_consumable)),
                        int(is_active),
                    ),
                )
                item_id = int(cursor.lastrowid)
                if track_stock and initial_stock:
                    self.db.execute(
                        """
                        INSERT INTO stock_movements(item_id, qty, kind, note, user_id, created_at)
                        VALUES (?, ?, 'initial', 'Начальный остаток', ?, datetime('now', 'localtime'))
                        """,
                        (item_id, int(initial_stock), user_id),
                    )
                if kind == "service" and consumables is not None:
                    self._replace_service_consumables(item_id, consumables)
        except sqlite3.IntegrityError as exc:
            raise ValidationError("Позиция с таким артикулом уже существует") from exc
        item = self.get_item(item_id)
        assert item is not None
        return item

    def update_item(
        self,
        item_id: int,
        *,
        name: str,
        kind: str,
        price: int,
        cost: int,
        sku: str | None = None,
        category_id: int | None = None,
        unit: str = "шт",
        track_stock: bool = True,
        is_active: bool = True,
        is_consumable: bool = False,
        consumables: list[tuple[int, int]] | None = None,
    ) -> Item:
        name, sku = self._validate_item(name, kind, category_id, price, cost, sku)
        if is_consumable and kind != "product":
            raise ValidationError("Расходником может быть только товар")
        if is_consumable:
            track_stock = True
        track_stock = bool(track_stock) and kind == "product"
        current = self.get_item(item_id)
        if current is None:
            raise ValidationError("Позиция не найдена")
        if current.track_stock and not track_stock and current.stock != 0:
            raise ValidationError(
                "Нельзя отключить складской учёт, пока остаток не равен нулю"
            )
        used_as_consumable = int(
            self.db.scalar(
                "SELECT COUNT(*) FROM service_consumables WHERE consumable_item_id=?",
                (item_id,),
            )
        )
        if used_as_consumable and (not is_consumable or kind != "product"):
            raise ValidationError(
                "Расходник используется в услугах. Сначала уберите его из состава услуг."
            )
        try:
            with self.db.transaction():
                self.db.execute(
                    """
                    UPDATE items
                    SET sku=?, name=?, kind=?, category_id=?, price=?, cost=?, unit=?,
                        track_stock=?, is_consumable=?, is_active=?,
                        updated_at=datetime('now', 'localtime')
                    WHERE id=?
                    """,
                    (
                        sku,
                        name,
                        kind,
                        category_id,
                        int(price),
                        int(cost),
                        (unit or "шт").strip() or "шт",
                        int(track_stock),
                        int(bool(is_consumable)),
                        int(is_active),
                        item_id,
                    ),
                )
                if kind == "service":
                    if consumables is not None:
                        self._replace_service_consumables(item_id, consumables)
                else:
                    self.db.execute(
                        "DELETE FROM service_consumables WHERE service_item_id=?",
                        (item_id,),
                    )
        except sqlite3.IntegrityError as exc:
            raise ValidationError("Позиция с таким артикулом уже существует") from exc
        updated = self.get_item(item_id)
        assert updated is not None
        return updated

    def set_item_active(self, item_id: int, active: bool) -> None:
        with self.db.transaction():
            self.db.execute(
                "UPDATE items SET is_active=?, updated_at=datetime('now', 'localtime') WHERE id=?",
                (int(active), item_id),
            )

    def delete_item(self, item_id: int) -> None:
        used_as_consumable = int(
            self.db.scalar(
                "SELECT COUNT(*) FROM service_consumables WHERE consumable_item_id=?",
                (item_id,),
            )
        )
        if used_as_consumable:
            raise ValidationError(
                "Расходник используется в услугах. Сначала уберите его из состава услуг."
            )
        try:
            with self.db.transaction():
                self.db.execute("DELETE FROM items WHERE id=?", (item_id,))
        except sqlite3.IntegrityError as exc:
            raise ValidationError(
                "Позиция уже использовалась в продажах и не может быть удалена. "
                "Отключите её вместо удаления."
            ) from exc

    # ------------------------------------------------------- service consumables
    @staticmethod
    def _normalize_consumables(
        consumables: list[tuple[int, int]] | None,
    ) -> dict[int, int]:
        normalized: dict[int, int] = {}
        for item_id, qty in consumables or []:
            item_id = int(item_id)
            qty = int(qty)
            if qty <= 0:
                raise ValidationError("Количество расходника должно быть больше нуля")
            normalized[item_id] = normalized.get(item_id, 0) + qty
        return normalized

    def _replace_service_consumables(
        self, service_item_id: int, consumables: list[tuple[int, int]] | None
    ) -> None:
        normalized = self._normalize_consumables(consumables)
        for consumable_id, qty in normalized.items():
            if consumable_id == service_item_id:
                raise ValidationError("Услуга не может расходовать саму себя")
            consumable = self.get_item(consumable_id)
            if consumable is None:
                raise ValidationError("Расходник не найден")
            if (
                consumable.kind != "product"
                or not consumable.is_consumable
                or not consumable.track_stock
            ):
                raise ValidationError(
                    f"«{consumable.name}» не является расходником со складским учётом"
                )
        self.db.execute(
            "DELETE FROM service_consumables WHERE service_item_id=?",
            (service_item_id,),
        )
        if normalized:
            self.db.executemany(
                """
                INSERT INTO service_consumables(service_item_id, consumable_item_id, qty)
                VALUES (?, ?, ?)
                """,
                [
                    (service_item_id, consumable_id, qty)
                    for consumable_id, qty in sorted(normalized.items())
                ],
            )

    def service_consumables(self, service_item_id: int) -> list[tuple[Item, int]]:
        """Return ``(consumable, qty_per_service_unit)`` rows for a service."""
        rows = self.db.query(
            """
            SELECT i.*, c.name AS category_name, COALESCE(v.qty, 0) AS stock,
                   sc.qty AS consumable_qty
            FROM service_consumables sc
            JOIN items i ON i.id = sc.consumable_item_id
            LEFT JOIN categories c ON c.id = i.category_id
            LEFT JOIN item_stock v ON v.item_id = i.id
            WHERE sc.service_item_id=?
            ORDER BY i.name
            """,
            (service_item_id,),
        )
        return [
            (self._item(row), int(row["consumable_qty"]))
            for row in rows
        ]

    def set_service_consumables(
        self, service_item_id: int, consumables: list[tuple[int, int]]
    ) -> None:
        service = self.get_item(service_item_id)
        if service is None:
            raise ValidationError("Услуга не найдена")
        if service.kind != "service":
            raise ValidationError("Расходники можно назначать только услугам")
        with self.db.transaction():
            self._replace_service_consumables(service_item_id, consumables)

    # ------------------------------------------------------------------- stock
    def stock_balance(self, item_id: int) -> int:
        return int(
            self.db.scalar(
                "SELECT COALESCE(qty, 0) FROM item_stock WHERE item_id=?", (item_id,)
            )
        )

    def low_stock_items(self, threshold: int | None = None) -> list[Item]:
        limit = self.settings.low_stock_threshold if threshold is None else threshold
        return [
            item
            for item in self.items(include_inactive=False)
            if item.kind == "product" and item.track_stock and item.stock <= limit
        ]

    def add_stock_movement(
        self,
        item_id: int,
        qty_delta: int,
        kind: str,
        user_id: int | None,
        note: str = "",
        *,
        allow_negative: bool = False,
    ) -> int:
        if kind not in STOCK_KIND_LABELS:
            raise ValidationError("Некорректный тип движения склада")
        if qty_delta == 0:
            raise ValidationError("Количество должно отличаться от нуля")
        item = self.get_item(item_id)
        if item is None:
            raise ValidationError("Позиция не найдена")
        if not item.track_stock:
            raise ValidationError("Для этой позиции складской учёт не ведётся")
        new_balance = item.stock + int(qty_delta)
        if new_balance < 0 and not allow_negative:
            raise ValidationError(
                f"Недостаточно остатка: сейчас {item.stock} {item.unit}, "
                f"изменение {qty_delta}."
            )
        with self.db.transaction():
            self.db.execute(
                """
                INSERT INTO stock_movements(item_id, qty, kind, note, user_id, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))
                """,
                (item_id, int(qty_delta), kind, (note or "").strip(), user_id),
            )
        return new_balance

    def set_stock(
        self,
        item_id: int,
        target_qty: int,
        user_id: int | None,
        note: str = "",
    ) -> int:
        if target_qty < 0:
            raise ValidationError("Остаток не может быть отрицательным")
        item = self.get_item(item_id)
        if item is None:
            raise ValidationError("Позиция не найдена")
        if not item.track_stock:
            raise ValidationError("Для этой позиции складской учёт не ведётся")
        delta = int(target_qty) - item.stock
        if delta == 0:
            return item.stock
        return self.add_stock_movement(
            item_id, delta, "adjustment", user_id, note or "Инвентаризация"
        )

    def stock_movements(
        self, limit: int = 200, item_id: int | None = None
    ) -> list[sqlite3.Row]:
        sql = """
            SELECT m.*, i.name AS item_name, i.unit AS unit,
                   COALESCE(u.full_name, u.username, '—') AS user_name
            FROM stock_movements m
            JOIN items i ON i.id = m.item_id
            LEFT JOIN users u ON u.id = m.user_id
        """
        params: list[Any] = []
        if item_id is not None:
            sql += " WHERE m.item_id=?"
            params.append(item_id)
        sql += " ORDER BY m.id DESC LIMIT ?"
        params.append(int(limit))
        return self.db.query(sql, params)

    # -------------------------------------------------------------- price lists
    def list_price_lists(self) -> list[PriceList]:
        active_id = self.settings.active_price_list_id
        rows = self.db.query(
            """
            SELECT pl.*, COUNT(pli.item_id) AS item_count
            FROM price_lists pl
            LEFT JOIN price_list_items pli ON pli.price_list_id = pl.id
            GROUP BY pl.id
            ORDER BY pl.name
            """
        )
        return [
            PriceList(
                id=int(row["id"]),
                name=str(row["name"]),
                is_active=int(row["id"]) == active_id,
                item_count=int(row["item_count"]),
            )
            for row in rows
        ]

    def get_price_list(self, price_list_id: int) -> PriceList | None:
        for price_list in self.list_price_lists():
            if price_list.id == price_list_id:
                return price_list
        return None

    def create_price_list(self, name: str, *, activate: bool = False) -> PriceList:
        name = (name or "").strip()
        if not name:
            raise ValidationError("Укажите название прейскуранта")
        try:
            with self.db.transaction():
                cursor = self.db.execute(
                    "INSERT INTO price_lists(name, is_active) VALUES (?, 1)",
                    (name,),
                )
                price_list_id = int(cursor.lastrowid)
                if activate or not self.settings.active_price_list_id:
                    self.settings.set_active_price_list(price_list_id)
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"Прейскурант «{name}» уже существует") from exc
        price_list = self.get_price_list(price_list_id)
        assert price_list is not None
        return price_list

    def rename_price_list(self, price_list_id: int, name: str) -> None:
        name = (name or "").strip()
        if not name:
            raise ValidationError("Укажите название прейскуранта")
        try:
            with self.db.transaction():
                self.db.execute(
                    "UPDATE price_lists SET name=? WHERE id=?", (name, price_list_id)
                )
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"Прейскурант «{name}» уже существует") from exc

    def set_active_price_list(self, price_list_id: int) -> None:
        if self.get_price_list(price_list_id) is None:
            raise ValidationError("Прейскурант не найден")
        with self.db.transaction():
            self.settings.set_active_price_list(price_list_id)

    def delete_price_list(self, price_list_id: int) -> None:
        if self.settings.active_price_list_id == price_list_id:
            raise ValidationError("Нельзя удалить активный прейскурант")
        if len(self.list_price_lists()) <= 1:
            raise ValidationError("Должен остаться хотя бы один прейскурант")
        with self.db.transaction():
            self.db.execute("DELETE FROM price_lists WHERE id=?", (price_list_id,))

    def price_list_items(self, price_list_id: int) -> list[tuple[Item, int | None]]:
        """Return all items with their override price (``None`` = base price)."""
        rows = self.db.query(
            """
            SELECT i.*, c.name AS category_name, COALESCE(v.qty, 0) AS stock,
                   pli.price AS override_price
            FROM items i
            LEFT JOIN categories c ON c.id = i.category_id
            LEFT JOIN item_stock v ON v.item_id = i.id
            LEFT JOIN price_list_items pli
                   ON pli.item_id = i.id AND pli.price_list_id = ?
            WHERE i.is_consumable=0
            ORDER BY i.name
            """,
            (price_list_id,),
        )
        result: list[tuple[Item, int | None]] = []
        for row in rows:
            override = int(row["override_price"]) if row["override_price"] is not None else None
            result.append((self._item(row), override))
        return result

    def set_price_list_item(
        self, price_list_id: int, item_id: int, price: int | None
    ) -> None:
        if price is not None and price < 0:
            raise ValidationError("Цена не может быть отрицательной")
        with self.db.transaction():
            if price is None:
                self.db.execute(
                    "DELETE FROM price_list_items WHERE price_list_id=? AND item_id=?",
                    (price_list_id, item_id),
                )
            else:
                self.db.execute(
                    """
                    INSERT INTO price_list_items(price_list_id, item_id, price)
                    VALUES (?, ?, ?)
                    ON CONFLICT(price_list_id, item_id) DO UPDATE SET price=excluded.price
                    """,
                    (price_list_id, item_id, int(price)),
                )

    def clear_price_list_overrides(self, price_list_id: int) -> None:
        with self.db.transaction():
            self.db.execute(
                "DELETE FROM price_list_items WHERE price_list_id=?", (price_list_id,)
            )
