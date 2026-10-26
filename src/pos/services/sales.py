"""Sales: atomic creation of orders, line items, payments and stock moves."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime

from ..database import Database
from ..models import (
    PaymentInput,
    Sale,
    SaleLine,
    SaleLineInput,
    SalePayment,
)
from .catalog import CatalogService
from .errors import SaleError, ValidationError
from .shifts import ShiftService

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class SalesService:
    def __init__(
        self,
        db: Database,
        catalog: CatalogService | None = None,
        shifts: ShiftService | None = None,
    ):
        self.db = db
        self.catalog = catalog or CatalogService(db)
        self.shifts = shifts or ShiftService(db)

    # ------------------------------------------------------------------ write
    def create_sale(
        self,
        *,
        user_id: int,
        shift_id: int,
        lines: list[SaleLineInput],
        payments: list[PaymentInput],
        note: str | None = None,
    ) -> Sale:
        if not lines:
            raise ValidationError("Чек пуст")
        merged: dict[int, list[int]] = {}
        for line in lines:
            if line.qty <= 0:
                raise ValidationError("Количество должно быть больше нуля")
            if line.unit_price is not None and line.unit_price < 0:
                raise ValidationError("Цена не может быть отрицательной")
            key = int(line.item_id)
            if key in merged:
                merged[key][0] += int(line.qty)
                if line.unit_price is not None:
                    merged[key][1] = int(line.unit_price)
            else:
                merged[key] = [
                    int(line.qty),
                    int(line.unit_price) if line.unit_price is not None else -1,
                ]
        try:
            with self.db.transaction():
                shift_row = self.db.query_one(
                    "SELECT id, user_id, status, opening_cash FROM shifts WHERE id=?",
                    (shift_id,),
                )
                if shift_row is None:
                    raise SaleError("Смена не найдена")
                if str(shift_row["status"]) != "open":
                    raise SaleError("Смена закрыта. Откройте новую смену.")
                if int(shift_row["user_id"]) != int(user_id):
                    raise SaleError("Нельзя продавать в смене другого продавца")

                prepared: list[SaleLine] = []
                total = 0
                consumable_demand: dict[int, int] = {}
                consumable_stock: dict[int, int] = {}
                consumable_names: dict[int, str] = {}
                consumable_services: dict[int, set[str]] = {}
                for item_id, (qty, price) in merged.items():
                    row = self.db.query_one(
                        """
                        SELECT i.*, COALESCE(v.qty, 0) AS stock
                        FROM items i
                        LEFT JOIN item_stock v ON v.item_id = i.id
                        WHERE i.id=?
                        """,
                        (item_id,),
                    )
                    if row is None:
                        raise SaleError("Товар или услуга не найдены")
                    if not bool(row["is_active"]):
                        raise SaleError(f"«{row['name']}» снят с продажи")
                    if bool(row["is_consumable"]):
                        raise SaleError(
                            f"«{row['name']}» — расходник, его нельзя продать как товар"
                        )
                    effective = self.catalog.effective_price(item_id)
                    unit_price = effective if price < 0 else price
                    if unit_price is None:
                        raise SaleError("Не удалось определить цену позиции")
                    if bool(row["track_stock"]) and int(row["stock"]) < qty:
                        raise SaleError(
                            f"Недостаточно «{row['name']}»: остаток "
                            f"{int(row['stock'])}, требуется {qty}"
                        )
                    line_total = int(unit_price) * qty
                    line_cost = int(row["cost"])
                    # Services consume materials from their recipe. The same
                    # consumable may be shared by any number of services, so
                    # demand is accumulated across all lines of the sale.
                    if str(row["kind"]) == "service":
                        for consumable, per_unit in self.catalog.service_consumables(item_id):
                            need = int(per_unit) * qty
                            consumable_demand[consumable.id] = (
                                consumable_demand.get(consumable.id, 0) + need
                            )
                            consumable_stock[consumable.id] = consumable.stock
                            consumable_names[consumable.id] = consumable.name
                            consumable_services.setdefault(consumable.id, set()).add(
                                str(row["name"])
                            )
                            line_cost += int(consumable.cost) * int(per_unit)
                    total += line_total
                    prepared.append(
                        SaleLine(
                            item_id=item_id,
                            name=str(row["name"]),
                            kind=str(row["kind"]),
                            qty=qty,
                            unit_price=int(unit_price),
                            cost=line_cost,
                            line_total=line_total,
                        )
                    )

                for consumable_id, need in consumable_demand.items():
                    available = consumable_stock.get(consumable_id, 0)
                    if available < need:
                        raise SaleError(
                            f"Недостаточно расходника «{consumable_names[consumable_id]}»: "
                            f"остаток {available}, требуется {need}"
                        )

                # Validate payment methods and amounts against the server total.
                clean_payments: list[tuple[int, str, str, int, int]] = []
                paid = 0
                for payment in payments:
                    if payment.amount <= 0:
                        continue
                    method = self.db.query_one(
                        "SELECT * FROM payment_methods WHERE id=?", (payment.method_id,)
                    )
                    if method is None:
                        raise SaleError("Способ оплаты не найден")
                    if not bool(method["is_active"]):
                        raise SaleError(
                            f"Способ оплаты «{method['name']}» отключён"
                        )
                    paid += int(payment.amount)
                    clean_payments.append(
                        (
                            int(method["id"]),
                            str(method["name"]),
                            str(method["kind"]),
                            int(method["affects_cash"]),
                            int(payment.amount),
                        )
                    )
                if not clean_payments and total != 0:
                    raise ValidationError("Добавьте хотя бы один способ оплаты")
                if paid != total:
                    raise SaleError("Сумма оплат не совпадает с итогом чека")

                created_at = _now()
                cursor = self.db.execute(
                    """
                    INSERT INTO sales(number, shift_id, user_id, status, subtotal,
                                      discount, total, note, created_at)
                    VALUES (?, ?, ?, 'completed', ?, 0, ?, ?, ?)
                    """,
                    (
                        f"TMP-{uuid.uuid4().hex}",
                        shift_id,
                        user_id,
                        total,
                        total,
                        (note or "").strip() or None,
                        created_at,
                    ),
                )
                sale_id = int(cursor.lastrowid)
                number = f"{datetime.now():%Y%m%d}-{sale_id:04d}"
                self.db.execute(
                    "UPDATE sales SET number=? WHERE id=?", (number, sale_id)
                )

                for line in prepared:
                    self.db.execute(
                        """
                        INSERT INTO sale_items(sale_id, item_id, name_snapshot, kind,
                                               qty, unit_price, cost, line_total)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            sale_id,
                            line.item_id,
                            line.name,
                            line.kind,
                            line.qty,
                            line.unit_price,
                            line.cost,
                            line.line_total,
                        ),
                    )
                    if line.kind == "product" and line.item_id:
                        item_row = self.db.query_one(
                            "SELECT track_stock FROM items WHERE id=?", (line.item_id,)
                        )
                        if item_row is not None and bool(item_row["track_stock"]):
                            self.db.execute(
                                """
                                INSERT INTO stock_movements(item_id, qty, kind, ref_type,
                                                            ref_id, note, user_id, created_at)
                                VALUES (?, ?, 'sale', 'sale', ?, ?, ?, ?)
                                """,
                                (
                                    line.item_id,
                                    -line.qty,
                                    sale_id,
                                    f"Чек {number}",
                                    user_id,
                                    created_at,
                                ),
                            )

                for consumable_id, need in consumable_demand.items():
                    services = ", ".join(sorted(consumable_services.get(consumable_id, ())))
                    self.db.execute(
                        """
                        INSERT INTO stock_movements(item_id, qty, kind, ref_type,
                                                    ref_id, note, user_id, created_at)
                        VALUES (?, ?, 'consumable', 'sale', ?, ?, ?, ?)
                        """,
                        (
                            consumable_id,
                            -need,
                            sale_id,
                            f"Чек {number}: {services}",
                            user_id,
                            created_at,
                        ),
                    )

                for method_id, method_name, method_kind, affects_cash, amount in clean_payments:
                    self.db.execute(
                        """
                        INSERT INTO sale_payments(sale_id, method_id, method_name,
                                                  method_kind, affects_cash, amount)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            sale_id,
                            method_id,
                            method_name,
                            method_kind,
                            affects_cash,
                            amount,
                        ),
                    )

                self.db.execute(
                    """
                    INSERT INTO shift_events(shift_id, kind, details, created_at)
                    VALUES (?, 'sale', ?, ?)
                    """,
                    (
                        shift_id,
                        json.dumps(
                            {
                                "sale_id": sale_id,
                                "number": number,
                                "total": total,
                                "items": len(prepared),
                                "payments": [
                                    {"method": p[1], "amount": p[4]} for p in clean_payments
                                ],
                            },
                            ensure_ascii=False,
                        ),
                        created_at,
                    ),
                )
        except sqlite3.Error as exc:
            logger.exception("Ошибка базы данных при создании продажи")
            raise SaleError(f"Не удалось сохранить продажу: {exc}") from exc

        logger.info("Продажа %s на сумму %s коп. сохранена", number, total)
        sale = self.get_sale(sale_id)
        assert sale is not None
        return sale

    # ------------------------------------------------------------------- read
    def get_sale(self, sale_id: int) -> Sale | None:
        row = self.db.query_one(
            """
            SELECT s.*, COALESCE(NULLIF(u.full_name, ''), u.username) AS user_name
            FROM sales s JOIN users u ON u.id = s.user_id
            WHERE s.id=?
            """,
            (sale_id,),
        )
        if row is None:
            return None
        lines = [
            SaleLine(
                item_id=int(r["item_id"]) if r["item_id"] else None,
                name=str(r["name_snapshot"]),
                kind=str(r["kind"]),
                qty=int(r["qty"]),
                unit_price=int(r["unit_price"]),
                cost=int(r["cost"]),
                line_total=int(r["line_total"]),
            )
            for r in self.db.query(
                "SELECT * FROM sale_items WHERE sale_id=? ORDER BY id", (sale_id,)
            )
        ]
        payments = [
            SalePayment(
                method_name=str(r["method_name"]),
                method_kind=str(r["method_kind"]),
                amount=int(r["amount"]),
            )
            for r in self.db.query(
                "SELECT * FROM sale_payments WHERE sale_id=? ORDER BY id", (sale_id,)
            )
        ]
        return Sale(
            id=int(row["id"]),
            number=str(row["number"]),
            shift_id=int(row["shift_id"]),
            user_id=int(row["user_id"]),
            user_name=str(row["user_name"]),
            status=str(row["status"]),
            subtotal=int(row["subtotal"]),
            discount=int(row["discount"]),
            total=int(row["total"]),
            note=str(row["note"]) if row["note"] else None,
            created_at=str(row["created_at"]),
            lines=lines,
            payments=payments,
        )

    def list_sales(self, limit: int = 100, shift_id: int | None = None) -> list[Sale]:
        sql = """
            SELECT s.*, COALESCE(NULLIF(u.full_name, ''), u.username) AS user_name
            FROM sales s JOIN users u ON u.id = s.user_id
        """
        params: list[object] = []
        if shift_id is not None:
            sql += " WHERE s.shift_id=?"
            params.append(shift_id)
        sql += " ORDER BY s.id DESC LIMIT ?"
        params.append(int(limit))
        result = []
        for row in self.db.query(sql, params):
            sale = self.get_sale(int(row["id"]))
            if sale:
                result.append(sale)
        return result
