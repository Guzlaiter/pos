"""Shift lifecycle with crash-safe accounting.

Shift totals are never stored as running counters. Every report is
recomputed from committed sales, so a crash or power loss cannot corrupt
a shift: the shift simply stays open and can be resumed.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime

from ..database import Database
from ..models import Shift
from .errors import ShiftError, ValidationError

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class ShiftService:
    def __init__(self, db: Database):
        self.db = db

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Shift:
        return Shift(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            user_name=str(row["user_name"]),
            opened_at=str(row["opened_at"]),
            closed_at=str(row["closed_at"]) if row["closed_at"] else None,
            status=str(row["status"]),
            opening_cash=int(row["opening_cash"]),
            closing_cash=int(row["closing_cash"]) if row["closing_cash"] is not None else None,
            expected_cash=int(row["expected_cash"]) if row["expected_cash"] is not None else None,
            cash_difference=(
                int(row["cash_difference"]) if row["cash_difference"] is not None else None
            ),
            note=str(row["note"]) if row["note"] else None,
            closed_by_user_id=(
                int(row["closed_by_user_id"]) if row["closed_by_user_id"] else None
            ),
        )

    _SELECT = """
        SELECT s.*, COALESCE(NULLIF(u.full_name, ''), u.username) AS user_name
        FROM shifts s
        JOIN users u ON u.id = s.user_id
    """

    def get(self, shift_id: int) -> Shift | None:
        row = self.db.query_one(self._SELECT + " WHERE s.id=?", (shift_id,))
        return self._from_row(row) if row else None

    def open_shift_for_user(self, user_id: int) -> Shift | None:
        row = self.db.query_one(
            self._SELECT + " WHERE s.user_id=? AND s.status='open'", (user_id,)
        )
        return self._from_row(row) if row else None

    def list_open_shifts(self) -> list[Shift]:
        rows = self.db.query(self._SELECT + " WHERE s.status='open' ORDER BY s.opened_at")
        return [self._from_row(row) for row in rows]

    def list_shifts(self, limit: int = 200) -> list[Shift]:
        rows = self.db.query(
            self._SELECT + " ORDER BY s.id DESC LIMIT ?", (int(limit),)
        )
        return [self._from_row(row) for row in rows]

    def open_shift(self, user_id: int, opening_cash: int = 0, note: str = "") -> Shift:
        if opening_cash < 0:
            raise ValidationError("Разменная сумма не может быть отрицательной")
        existing = self.open_shift_for_user(user_id)
        if existing is not None:
            raise ShiftError(
                f"У вас уже открыта смена №{existing.id} с {existing.opened_at}. "
                "Сначала закройте её."
            )
        user = self.db.query_one(
            "SELECT id, is_active FROM users WHERE id=?", (user_id,)
        )
        if user is None or not bool(user["is_active"]):
            raise ShiftError("Пользователь не найден или отключён")
        try:
            with self.db.transaction():
                cursor = self.db.execute(
                    "INSERT INTO shifts(user_id, opened_at, status, opening_cash, note) "
                    "VALUES (?, ?, 'open', ?, ?)",
                    (user_id, _now(), int(opening_cash), (note or "").strip() or None),
                )
                shift_id = int(cursor.lastrowid)
                self._log_event(
                    shift_id,
                    "opened",
                    {"user_id": user_id, "opening_cash": int(opening_cash)},
                )
        except sqlite3.IntegrityError as exc:
            raise ShiftError(
                "Не удалось открыть смену: у пользователя уже есть открытая смена"
            ) from exc
        shift = self.get(shift_id)
        assert shift is not None
        logger.info("Открыта смена №%s (пользователь %s)", shift_id, user_id)
        return shift

    def expected_cash(self, shift_id: int) -> int:
        shift = self.get(shift_id)
        if shift is None:
            raise ShiftError("Смена не найдена")
        cash_sales = int(
            self.db.scalar(
                """
                SELECT COALESCE(SUM(sp.amount), 0)
                FROM sale_payments sp
                JOIN sales s ON s.id = sp.sale_id
                WHERE s.shift_id=? AND s.status='completed' AND sp.affects_cash=1
                """,
                (shift_id,),
            )
        )
        return shift.opening_cash + cash_sales

    def close_shift(
        self,
        shift_id: int,
        counted_cash: int,
        closed_by_user_id: int,
        note: str = "",
    ) -> Shift:
        if counted_cash < 0:
            raise ValidationError("Сумма в кассе не может быть отрицательной")
        # One IMMEDIATE transaction prevents a sale from sneaking in between
        # computing expected cash and closing the shift.
        with self.db.transaction():
            row = self.db.query_one(
                self._SELECT + " WHERE s.id=?", (shift_id,)
            )
            if row is None:
                raise ShiftError("Смена не найдена")
            shift = self._from_row(row)
            if not shift.is_open:
                raise ShiftError("Смена уже закрыта")
            expected = self.expected_cash(shift_id)
            difference = int(counted_cash) - expected
            closed_at = _now()
            self.db.execute(
                """
                UPDATE shifts
                SET status='closed', closed_at=?, closing_cash=?, expected_cash=?,
                    cash_difference=?, closed_by_user_id=?, note=?
                WHERE id=? AND status='open'
                """,
                (
                    closed_at,
                    int(counted_cash),
                    expected,
                    difference,
                    closed_by_user_id,
                    (note or "").strip() or shift.note,
                    shift_id,
                ),
            )
            self._log_event(
                shift_id,
                "closed",
                {
                    "closed_by": closed_by_user_id,
                    "counted_cash": int(counted_cash),
                    "expected_cash": expected,
                    "difference": difference,
                },
            )
        logger.info(
            "Закрыта смена №%s: выручка учтена, наличные %s, ожидалось %s",
            shift_id,
            counted_cash,
            expected,
        )
        # A backup after every shift close is a cheap extra safety net.
        try:
            self.db.backup(tag=f"shift-{shift_id}-closed")
        except Exception:  # pragma: no cover - backup must not break closing
            logger.exception("Ошибка резервного копирования при закрытии смены")
        closed = self.get(shift_id)
        assert closed is not None
        return closed

    def mark_resumed(self, shift_id: int) -> None:
        """Record that an open shift was picked up after a restart."""
        try:
            with self.db.transaction():
                self._log_event(shift_id, "resumed", {"at": _now()})
        except sqlite3.Error:
            logger.exception("Не удалось записать событие восстановления смены")

    def _log_event(self, shift_id: int, kind: str, details: dict | None = None) -> None:
        self.db.execute(
            "INSERT INTO shift_events(shift_id, kind, details, created_at) VALUES (?, ?, ?, ?)",
            (
                shift_id,
                kind,
                json.dumps(details or {}, ensure_ascii=False, sort_keys=True),
                _now(),
            ),
        )

    def events(self, shift_id: int) -> list[sqlite3.Row]:
        return self.db.query(
            "SELECT * FROM shift_events WHERE shift_id=? ORDER BY id", (shift_id,)
        )

    def shift_sale_count(self, shift_id: int) -> int:
        return int(
            self.db.scalar(
                "SELECT COUNT(*) FROM sales WHERE shift_id=? AND status='completed'",
                (shift_id,),
            )
        )
