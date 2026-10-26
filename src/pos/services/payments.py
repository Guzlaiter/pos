"""Configurable payment methods."""

from __future__ import annotations

import sqlite3

from ..database import Database
from ..models import PaymentMethod
from .errors import ValidationError

PAYMENT_KIND_LABELS = {
    "cash": "Наличные",
    "qr": "QR-код",
    "transfer": "Перевод",
    "terminal": "Терминал",
    "other": "Другое",
}


class PaymentMethodService:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _from_row(row: sqlite3.Row) -> PaymentMethod:
        return PaymentMethod(
            id=int(row["id"]),
            name=str(row["name"]),
            kind=str(row["kind"]),
            affects_cash=bool(row["affects_cash"]),
            is_active=bool(row["is_active"]),
            sort_order=int(row["sort_order"]),
        )

    def list_methods(self, include_inactive: bool = False) -> list[PaymentMethod]:
        sql = "SELECT * FROM payment_methods"
        if not include_inactive:
            sql += " WHERE is_active=1"
        sql += " ORDER BY sort_order, name"
        return [self._from_row(row) for row in self.db.query(sql)]

    def get(self, method_id: int) -> PaymentMethod | None:
        row = self.db.query_one("SELECT * FROM payment_methods WHERE id=?", (method_id,))
        return self._from_row(row) if row else None

    def _validate(self, name: str, kind: str) -> str:
        name = (name or "").strip()
        if not name:
            raise ValidationError("Укажите название способа оплаты")
        if kind not in PAYMENT_KIND_LABELS:
            raise ValidationError("Некорректный тип оплаты")
        return name

    def create_method(
        self,
        name: str,
        kind: str = "other",
        affects_cash: bool = False,
        sort_order: int = 0,
        is_active: bool = True,
    ) -> PaymentMethod:
        name = self._validate(name, kind)
        try:
            with self.db.transaction():
                cursor = self.db.execute(
                    "INSERT INTO payment_methods(name, kind, affects_cash, sort_order, is_active) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        name,
                        kind,
                        int(affects_cash),
                        int(sort_order),
                        int(is_active),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"Способ оплаты «{name}» уже существует") from exc
        method = self.get(int(cursor.lastrowid))
        assert method is not None
        return method

    def update_method(
        self,
        method_id: int,
        *,
        name: str,
        kind: str,
        affects_cash: bool,
        sort_order: int,
        is_active: bool,
    ) -> PaymentMethod:
        name = self._validate(name, kind)
        current = self.get(method_id)
        if current is None:
            raise ValidationError("Способ оплаты не найден")
        if current.is_active and not is_active:
            active_count = int(
                self.db.scalar(
                    "SELECT COUNT(*) FROM payment_methods WHERE is_active=1 AND id<>?",
                    (method_id,),
                )
            )
            if active_count == 0:
                raise ValidationError(
                    "Должен остаться хотя бы один активный способ оплаты"
                )
        try:
            with self.db.transaction():
                self.db.execute(
                    """
                    UPDATE payment_methods
                    SET name=?, kind=?, affects_cash=?, sort_order=?, is_active=?
                    WHERE id=?
                    """,
                    (
                        name,
                        kind,
                        int(affects_cash),
                        int(sort_order),
                        int(is_active),
                        method_id,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ValidationError(f"Способ оплаты «{name}» уже существует") from exc
        updated = self.get(method_id)
        assert updated is not None
        return updated

    def set_active(self, method_id: int, active: bool) -> None:
        method = self.get(method_id)
        if method is None:
            raise ValidationError("Способ оплаты не найден")
        self.update_method(
            method_id,
            name=method.name,
            kind=method.kind,
            affects_cash=method.affects_cash,
            sort_order=method.sort_order,
            is_active=active,
        )
