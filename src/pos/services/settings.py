"""Application settings stored in the database."""

from __future__ import annotations

from typing import Any

from ..database import DEFAULT_SETTINGS, Database
from .errors import ValidationError


class SettingsService:
    def __init__(self, db: Database):
        self.db = db

    def all(self) -> dict[str, str]:
        rows = self.db.query("SELECT key, value FROM settings")
        data = dict(DEFAULT_SETTINGS)
        data.update({row["key"]: row["value"] for row in rows})
        return data

    def get(self, key: str, default: str = "") -> str:
        row = self.db.query_one("SELECT value FROM settings WHERE key = ?", (key,))
        if row is None:
            return DEFAULT_SETTINGS.get(key, default)
        return str(row["value"])

    def get_int(self, key: str, default: int = 0) -> int:
        try:
            return int(self.get(key, str(default)))
        except (TypeError, ValueError):
            return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        value = self.get(key, "1" if default else "0").strip().casefold()
        return value in {"1", "true", "yes", "да", "on"}

    def set(self, key: str, value: Any) -> None:
        if not key or not key.replace("_", "").isalnum():
            raise ValidationError("Некорректный ключ настройки")
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    def set_many(self, values: dict[str, Any]) -> None:
        with self.db.transaction():
            for key, value in values.items():
                self.db.execute(
                    "INSERT INTO settings(key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, str(value)),
                )

    @property
    def currency(self) -> str:
        return self.get("currency", "₽") or "₽"

    @property
    def company_name(self) -> str:
        return self.get("company_name", "Моя компания") or "Моя компания"

    @property
    def receipt_footer(self) -> str:
        return self.get("receipt_footer", "")

    @property
    def low_stock_threshold(self) -> int:
        return max(0, self.get_int("low_stock_threshold", 5))

    @property
    def active_price_list_id(self) -> int | None:
        try:
            value = int(self.get("active_price_list_id", "0"))
        except ValueError:
            return None
        return value or None

    def set_active_price_list(self, price_list_id: int) -> None:
        self.set("active_price_list_id", price_list_id)
