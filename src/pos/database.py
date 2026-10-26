"""SQLite access layer.

Reliability choices:

* WAL journal mode for crash consistency and fast commits.
* ``synchronous=FULL`` so a committed sale survives power loss.
* Explicit ``BEGIN IMMEDIATE`` transactions for every write.
* ``quick_check`` on startup and automatic backups.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 2

DEFAULT_SETTINGS: dict[str, str] = {
    "company_name": "Моя компания",
    "company_address": "",
    "company_phone": "",
    "currency": "₽",
    "receipt_footer": "Спасибо за покупку!",
    "low_stock_threshold": "5",
    "backup_keep": "20",
    "backup_on_start": "1",
}

DEFAULT_PAYMENT_METHODS = [
    ("Наличные", "cash", 1, 10),
    ("QR-код", "qr", 0, 20),
    ("Перевод", "transfer", 0, 30),
    ("Терминал", "terminal", 0, 40),
]


class DatabaseError(RuntimeError):
    """Raised when the database cannot be opened or is damaged."""


class Database:
    def __init__(self, path: str | Path, backup_dir: str | Path | None = None):
        self.path = Path(path)
        self.backup_dir = Path(backup_dir) if backup_dir else self.path.parent / "backups"
        self.conn: sqlite3.Connection | None = None
        self._savepoint_counter = 0

    # ------------------------------------------------------------------ open
    def connect(self) -> sqlite3.Connection:
        if self.conn is not None:
            return self.conn
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        try:
            conn = sqlite3.connect(
                str(self.path),
                timeout=15,
                isolation_level=None,
                check_same_thread=True,
            )
        except sqlite3.Error as exc:
            raise DatabaseError(f"Не удалось открыть базу данных: {exc}") from exc

        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = FULL")
        conn.execute("PRAGMA wal_autocheckpoint = 1000")
        conn.execute("PRAGMA temp_store = MEMORY")
        self.conn = conn
        try:
            self._migrate()
            self._seed()
        except Exception:
            conn.close()
            self.conn = None
            raise
        return conn

    def close(self) -> None:
        if self.conn is not None:
            try:
                self.conn.execute("PRAGMA optimize")
                self.conn.commit()
            except sqlite3.Error:
                pass
            self.conn.close()
            self.conn = None

    @property
    def db(self) -> sqlite3.Connection:
        if self.conn is None:
            return self.connect()
        return self.conn

    # ------------------------------------------------------------- migrations
    def _migrate(self) -> None:
        version = int(self.db.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            raise DatabaseError(
                "База данных создана более новой версией программы "
                f"(схема {version}, поддерживается {SCHEMA_VERSION})."
            )
        if version == 0:
            schema = SCHEMA_PATH.read_text(encoding="utf-8")
            self.db.executescript(schema)
            self.db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            logger.info("Создана новая база данных: %s", self.path)
            return

        if version < 2:
            # Version 2 adds consumables for services. ALTER TABLE and table
            # creation are transactional in SQLite, so a failure leaves the
            # old schema version untouched.
            with self.transaction():
                columns = {
                    str(row["name"])
                    for row in self.db.execute("PRAGMA table_info(items)").fetchall()
                }
                if "is_consumable" not in columns:
                    self.db.execute(
                        "ALTER TABLE items ADD COLUMN is_consumable INTEGER NOT NULL DEFAULT 0"
                    )
                self.db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS service_consumables (
                        service_item_id     INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
                        consumable_item_id  INTEGER NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
                        qty                 INTEGER NOT NULL CHECK (qty > 0),
                        PRIMARY KEY (service_item_id, consumable_item_id),
                        CHECK (service_item_id <> consumable_item_id)
                    )
                    """
                )
                self.db.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_service_consumables_consumable
                    ON service_consumables(consumable_item_id)
                    """
                )
                self.db.execute("PRAGMA user_version = 2")
            logger.info("База данных обновлена до схемы 2: расходники услуг")

    def _seed(self) -> None:
        with self.transaction():
            methods = self.db.execute("SELECT COUNT(*) FROM payment_methods").fetchone()[0]
            if not methods:
                self.db.executemany(
                    "INSERT INTO payment_methods(name, kind, affects_cash, sort_order) "
                    "VALUES (?, ?, ?, ?)",
                    DEFAULT_PAYMENT_METHODS,
                )
            lists = self.db.execute("SELECT COUNT(*) FROM price_lists").fetchone()[0]
            if not lists:
                cursor = self.db.execute(
                    "INSERT INTO price_lists(name, is_active) VALUES ('Основной', 1)"
                )
                self._set_setting_raw("active_price_list_id", str(cursor.lastrowid))
            for key, value in DEFAULT_SETTINGS.items():
                self.db.execute(
                    "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, value)
                )

    # -------------------------------------------------------------- utilities
    def _set_setting_raw(self, key: str, value: str) -> None:
        self.db.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a write transaction atomically.

        Nested calls use SAVEPOINTs so service composition stays safe.
        """
        conn = self.db
        if conn.in_transaction:
            self._savepoint_counter += 1
            name = f"sp_{self._savepoint_counter}"
            conn.execute(f"SAVEPOINT {name}")
            try:
                yield conn
            except BaseException:
                conn.execute(f"ROLLBACK TO {name}")
                conn.execute(f"RELEASE {name}")
                raise
            else:
                conn.execute(f"RELEASE {name}")
            return

        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.rollback()
            raise
        else:
            conn.commit()

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        return self.db.execute(sql, params)

    def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> sqlite3.Cursor:
        return self.db.executemany(sql, seq)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return list(self.db.execute(sql, params).fetchall())

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        return self.db.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Sequence[Any] = (), default: Any = 0) -> Any:
        row = self.db.execute(sql, params).fetchone()
        if row is None:
            return default
        value = row[0]
        return default if value is None else value

    # ---------------------------------------------------------------- integrity
    def quick_check(self) -> tuple[bool, str]:
        try:
            rows = self.db.execute("PRAGMA quick_check").fetchall()
        except sqlite3.Error as exc:
            return False, str(exc)
        messages = [str(row[0]) for row in rows]
        ok = len(messages) == 1 and messages[0] == "ok"
        return ok, "\n".join(messages)

    def integrity_check(self) -> tuple[bool, str]:
        try:
            rows = self.db.execute("PRAGMA integrity_check").fetchall()
        except sqlite3.Error as exc:
            return False, str(exc)
        messages = [str(row[0]) for row in rows]
        ok = len(messages) == 1 and messages[0] == "ok"
        return ok, "\n".join(messages)

    def table_count(self, table: str) -> int:
        allowed = {
            "users",
            "categories",
            "items",
            "sales",
            "shifts",
            "payment_methods",
            "stock_movements",
        }
        if table not in allowed:
            raise ValueError(table)
        return int(self.scalar(f"SELECT COUNT(*) FROM {table}"))

    @property
    def schema_version(self) -> int:
        return int(self.scalar("PRAGMA user_version", default=0))

    # ------------------------------------------------------------------ backup
    def backup(self, tag: str = "auto") -> Path | None:
        """Create an atomic, consistent database snapshot."""
        conn = self.db
        if conn.in_transaction:
            logger.warning("Пропуск резервной копии: открыта транзакция")
            return None
        safe_tag = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in tag)[:40]
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = self.backup_dir / f"pos-{stamp}-{safe_tag}.db"
        tmp = dest.with_suffix(".db.tmp")
        try:
            target = sqlite3.connect(str(tmp))
            try:
                conn.backup(target)
            finally:
                target.close()
            os.replace(tmp, dest)
            self._prune_backups()
            logger.info("Создана резервная копия: %s", dest)
            return dest
        except (sqlite3.Error, OSError) as exc:
            logger.error("Не удалось создать резервную копию: %s", exc)
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return None

    def _prune_backups(self) -> None:
        try:
            keep = int(self.scalar("SELECT value FROM settings WHERE key='backup_keep'", default=20))
        except (TypeError, ValueError):
            keep = 20
        keep = max(3, min(keep, 200))
        files = sorted(
            self.backup_dir.glob("pos-*.db"), key=lambda p: p.name, reverse=True
        )
        for old in files[keep:]:
            try:
                old.unlink()
            except OSError:
                pass

    def latest_backup(self) -> Path | None:
        files = sorted(self.backup_dir.glob("pos-*.db"), key=lambda p: p.name, reverse=True)
        return files[0] if files else None
