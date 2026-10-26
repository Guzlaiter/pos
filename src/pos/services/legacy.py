"""Import data from a previous POS database (SQLite or CSV).

The importer is intentionally conservative: it maps source columns to
target fields, previews the result, upserts by SKU/name and records a
report in ``import_jobs``.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

from ..database import Database
from ..money import format_money, parse_bool, parse_int, parse_money
from .errors import ImportError_

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------- source
@dataclass(frozen=True)
class TableInfo:
    name: str
    columns: list[str]
    row_count: int
    kind: str = "sqlite"


class LegacySource:
    """Read-only access to a legacy SQLite database or CSV file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if not self.path.is_file():
            raise ImportError_("Файл не найден")
        suffix = self.path.suffix.casefold()
        if suffix in {".db", ".sqlite", ".sqlite3"}:
            self.kind = "sqlite"
        elif suffix in {".csv", ".txt"}:
            self.kind = "csv"
        else:
            raise ImportError_(
                "Поддерживаются базы SQLite (*.db, *.sqlite, *.sqlite3) и файлы CSV"
            )
        self._tables: list[TableInfo] | None = None

    # ------------------------------------------------------------------ tables
    def tables(self) -> list[TableInfo]:
        if self._tables is not None:
            return self._tables
        if self.kind == "csv":
            columns, rows = self._read_csv(limit=0)
            self._tables = [
                TableInfo(self.path.stem, columns, len(rows), "csv")
            ]
            return self._tables
        try:
            conn = self._connect()
        except sqlite3.Error as exc:
            raise ImportError_(f"Не удалось открыть базу: {exc}") from exc
        try:
            rows = conn.execute(
                "SELECT name, type FROM sqlite_master "
                "WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            ).fetchall()
            tables: list[TableInfo] = []
            for row in rows:
                name = str(row["name"])
                columns = self._columns(conn, name)
                if not columns:
                    continue
                try:
                    count = int(
                        conn.execute(f"SELECT COUNT(*) FROM {_quote_ident(name)}").fetchone()[0]
                    )
                except sqlite3.Error:
                    count = 0
                tables.append(TableInfo(name, columns, count, "sqlite"))
            self._tables = tables
            return tables
        finally:
            conn.close()

    @staticmethod
    def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
        try:
            rows = conn.execute(f"PRAGMA table_info({_quote_ident(table)})").fetchall()
            return [str(row["name"]) for row in rows]
        except sqlite3.Error:
            return []

    def _connect(self) -> sqlite3.Connection:
        path = str(self.path.resolve()).replace("\\", "/")
        uri = f"file:{quote(path, safe='/:')}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # -------------------------------------------------------------------- read
    def read_rows(self, table: str, limit: int | None = None) -> list[dict[str, Any]]:
        if self.kind == "csv":
            columns, rows = self._read_csv(limit=limit)
            return rows
        conn = self._connect()
        try:
            sql = f"SELECT * FROM {_quote_ident(table)}"
            if limit:
                sql += f" LIMIT {int(limit)}"
            rows = conn.execute(sql).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            raise ImportError_(f"Не удалось прочитать таблицу «{table}»: {exc}") from exc
        finally:
            conn.close()

    def columns(self, table: str) -> list[str]:
        for info in self.tables():
            if info.name == table:
                return info.columns
        raise ImportError_("Таблица не найдена")

    def _read_csv(self, limit: int | None = None) -> tuple[list[str], list[dict[str, Any]]]:
        text = None
        for encoding in ("utf-8-sig", "cp1251", "utf-16"):
            try:
                text = self.path.read_text(encoding=encoding)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ImportError_("Не удалось определить кодировку CSV")
        sample = text[:8192]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = ";" if sample.count(";") >= sample.count(",") else ","
        reader = csv.reader(text.splitlines(), delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration:
            return [], []
        columns = [h.strip() or f"col{i + 1}" for i, h in enumerate(header)]
        rows: list[dict[str, Any]] = []
        for values in reader:
            if not any(str(v).strip() for v in values):
                continue
            row = {columns[i]: values[i] if i < len(values) else "" for i in range(len(columns))}
            rows.append(row)
            if limit and len(rows) >= limit:
                break
        return columns, rows


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# ------------------------------------------------------------------- mappings
@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    required: bool = False
    constants: tuple[tuple[str, str], ...] = ()
    default: str = ""


@dataclass(frozen=True)
class TargetSpec:
    key: str
    label: str
    fields: tuple[FieldSpec, ...]


_KIND_CONSTANTS = (
    ("Товар", "@product"),
    ("Услуга", "@service"),
    ("Любой", "@any"),
)
_YES_NO = (("Да", "@yes"), ("Нет", "@no"))
_AUTO_STOCK = (("Автоматически (товар — да)", "@auto"), ("Да", "@yes"), ("Нет", "@no"))
_PAYMENT_KINDS = (
    ("Наличные", "@cash"),
    ("QR-код", "@qr"),
    ("Перевод", "@transfer"),
    ("Терминал", "@terminal"),
    ("Другое", "@other"),
)

TARGETS: dict[str, TargetSpec] = {
    "category": TargetSpec(
        "category",
        "Категории",
        (
            FieldSpec("name", "Название", True),
            FieldSpec("kind", "Тип категории", False, _KIND_CONSTANTS, "@any"),
            FieldSpec("sort_order", "Порядок сортировки", False, default="0"),
        ),
    ),
    "item": TargetSpec(
        "item",
        "Товары и услуги",
        (
            FieldSpec("name", "Название", True),
            FieldSpec("sku", "Артикул", False),
            FieldSpec("kind", "Тип позиции", False, _KIND_CONSTANTS, "@product"),
            FieldSpec("category", "Категория", False),
            FieldSpec("price", "Цена продажи", False, default="0"),
            FieldSpec("cost", "Себестоимость", False, default="0"),
            FieldSpec("unit", "Единица", False, default="шт"),
            FieldSpec("stock", "Остаток", False),
            FieldSpec("track_stock", "Складской учёт", False, _AUTO_STOCK, "@auto"),
            FieldSpec("active", "Активна", False, _YES_NO, "@yes"),
        ),
    ),
    "payment": TargetSpec(
        "payment",
        "Способы оплаты",
        (
            FieldSpec("name", "Название", True),
            FieldSpec("kind", "Тип", False, _PAYMENT_KINDS, "@other"),
            FieldSpec("affects_cash", "Учитывать в кассе", False, _YES_NO, "@no"),
            FieldSpec("sort_order", "Порядок сортировки", False, default="0"),
            FieldSpec("active", "Активен", False, _YES_NO, "@yes"),
        ),
    ),
}

FIELD_SYNONYMS: dict[tuple[str, str], tuple[str, ...]] = {
    ("category", "name"): ("название", "наименование", "name", "title", "категория", "группа"),
    ("category", "kind"): ("тип", "вид", "type", "kind"),
    ("category", "sort_order"): ("порядок", "сортировка", "sort", "order"),
    ("item", "name"): ("название", "наименование", "name", "title", "товар", "услуга", "позиция"),
    ("item", "sku"): ("артикул", "sku", "код", "code", "штрихкод", "barcode"),
    ("item", "kind"): ("тип", "вид", "type", "kind", "категория товара"),
    ("item", "category"): ("категория", "группа", "category", "group", "раздел"),
    ("item", "price"): ("цена", "price", "стоимость", "розница", "sale_price", "цена продажи"),
    ("item", "cost"): ("себестоимость", "cost", "закупка", "закупочная", "purchase_price"),
    ("item", "unit"): ("единица", "ед", "unit", "ед.изм", "единица измерения", "measure"),
    ("item", "stock"): ("остаток", "количество", "кол-во", "qty", "quantity", "stock", "склад"),
    ("item", "track_stock"): ("склад", "учет", "track_stock", "stock"),
    ("item", "active"): ("актив", "active", "активен", "в продаже"),
    ("payment", "name"): ("название", "наименование", "name", "способ", "оплата"),
    ("payment", "kind"): ("тип", "вид", "type", "kind"),
    ("payment", "affects_cash"): ("касса", "наличные", "cash", "affects_cash"),
    ("payment", "sort_order"): ("порядок", "сортировка", "sort", "order"),
    ("payment", "active"): ("актив", "active", "активен"),
}


def target_spec(target: str) -> TargetSpec:
    try:
        return TARGETS[target]
    except KeyError as exc:
        raise ImportError_("Неизвестный тип импорта") from exc


def field_label(target: str, key: str) -> str:
    for spec in target_spec(target).fields:
        if spec.key == key:
            return spec.label
    return key


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]+", "", str(text).casefold())


def suggest_mapping(target: str, columns: Iterable[str]) -> dict[str, str]:
    """Pre-fill mapping by matching Russian/English column names."""
    spec = target_spec(target)
    normalized = {_norm(column): column for column in columns}
    mapping: dict[str, str] = {}
    used: set[str] = set()

    # First pass: exact (normalized) matches for every field. Doing this
    # before fuzzy matching prevents a generic synonym such as
    # "категория товара" from stealing the "Категория" column from the
    # dedicated category field.
    for field in spec.fields:
        for synonym in FIELD_SYNONYMS.get((target, field.key), ()):
            norm_syn = _norm(synonym)
            column = normalized.get(norm_syn)
            if column is not None and column not in used:
                mapping[field.key] = f"col:{column}"
                used.add(column)
                break

    # Second pass: tolerant substring matching for the remaining fields.
    for field in spec.fields:
        if field.key in mapping:
            continue
        synonyms = FIELD_SYNONYMS.get((target, field.key), ())
        match: str | None = None
        for synonym in synonyms:
            norm_syn = _norm(synonym)
            for norm_col, column in normalized.items():
                if column in used:
                    continue
                if len(norm_syn) >= 3 and (
                    norm_syn in norm_col or norm_col in norm_syn
                ):
                    match = column
                    break
            if match:
                break
        if match:
            mapping[field.key] = f"col:{match}"
            used.add(match)

    for field in spec.fields:
        if field.key not in mapping and field.default:
            mapping[field.key] = field.default
    # Required fields must not silently fall back to constants.
    for field in spec.fields:
        if field.required:
            mapping.setdefault(field.key, "")
    return mapping


def guess_target(table_name: str) -> str:
    name = _norm(table_name)
    if any(word in name for word in ("категор", "category", "групп", "group")):
        return "category"
    if any(word in name for word in ("оплат", "payment", "pay")):
        return "payment"
    if any(word in name for word in ("товар", "услуг", "product", "service", "item", "номенклат")):
        return "item"
    return ""


def mapping_to_json(mapping: dict[str, str]) -> str:
    return json.dumps(mapping, ensure_ascii=False, sort_keys=True)


# --------------------------------------------------------------------- import
@dataclass
class ImportOptions:
    price_units: str = "rub"  # "rub" | "cents"
    update_existing: bool = True
    import_stock: bool = True


@dataclass
class ImportResult:
    target: str
    table: str
    created: int = 0
    updated: int = 0
    skipped: int = 0
    stock_updated: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.created + self.updated + self.skipped

    def summary(self) -> str:
        parts = [
            f"создано: {self.created}",
            f"обновлено: {self.updated}",
            f"пропущено: {self.skipped}",
        ]
        if self.stock_updated:
            parts.append(f"остатки: {self.stock_updated}")
        if self.errors:
            parts.append(f"ошибок: {len(self.errors)}")
        return ", ".join(parts)


_ITEM_KIND_MAP = {
    "товар": "product",
    "товары": "product",
    "product": "product",
    "goods": "product",
    "услуга": "service",
    "услуги": "service",
    "service": "service",
    "work": "service",
    "работа": "service",
}
_PAYMENT_KIND_MAP = {
    "наличные": "cash",
    "наличка": "cash",
    "cash": "cash",
    "qr": "qr",
    "qr-код": "qr",
    "qr код": "qr",
    "перевод": "transfer",
    "transfer": "transfer",
    "терминал": "terminal",
    "terminal": "terminal",
    "карта": "terminal",
    "card": "terminal",
    "другое": "other",
    "other": "other",
}


def _source_value(row: dict[str, Any], mapping: dict[str, str], key: str) -> Any:
    raw = mapping.get(key, "")
    if not raw:
        return None
    if raw.startswith("col:"):
        return row.get(raw[4:])
    return raw  # constant, e.g. @product


def _as_constant(value: str) -> str:
    return value[1:] if value.startswith("@") else value


class LegacyImportService:
    def __init__(self, db: Database):
        self.db = db

    # ----------------------------------------------------------------- preview
    def map_row(
        self,
        target: str,
        row: dict[str, Any],
        mapping: dict[str, str],
        options: ImportOptions,
    ) -> dict[str, Any]:
        spec = target_spec(target)
        result: dict[str, Any] = {}
        raw_kind = _source_value(row, mapping, "kind")
        if target == "item":
            kind = _ITEM_KIND_MAP.get(str(raw_kind or "").strip().casefold(), "product")
            result["kind"] = kind
        elif target == "category":
            value = str(raw_kind or "").strip().casefold()
            result["kind"] = value if value in {"any", "product", "service"} else "any"
        elif target == "payment":
            value = str(raw_kind or "").strip().casefold()
            result["kind"] = _PAYMENT_KIND_MAP.get(value, "other")

        for field_spec in spec.fields:
            if field_spec.key == "kind":
                continue
            key = field_spec.key
            raw = _source_value(row, mapping, key)
            if key == "name":
                result[key] = str(raw if raw is not None else "").strip()
            elif key in {"price", "cost"}:
                try:
                    result[key] = parse_money(raw, units=options.price_units)
                except ValueError:
                    result[key] = 0
            elif key == "stock":
                try:
                    result[key] = parse_int(raw) if raw not in (None, "") else None
                except ValueError:
                    result[key] = None
            elif key == "unit":
                result[key] = (str(raw).strip() if raw is not None else "") or "шт"
            elif key == "category":
                result[key] = (str(raw).strip() if raw is not None else "") or None
            elif key == "sort_order":
                try:
                    result[key] = parse_int(raw) if raw not in (None, "") else 0
                except ValueError:
                    result[key] = 0
            elif key == "track_stock":
                value = _as_constant(str(raw)) if raw else "auto"
                result[key] = (
                    result.get("kind") == "product"
                    if value == "auto"
                    else parse_bool(value, True)
                )
            elif key == "affects_cash":
                value = _as_constant(str(raw)) if raw else "no"
                result[key] = result["kind"] == "cash" if value == "auto" else parse_bool(value, False)
            elif key == "active":
                result[key] = parse_bool(_as_constant(str(raw)) if raw else "yes", True)
            else:
                result[key] = str(raw).strip() if raw is not None else ""
        return result

    def preview(
        self,
        target: str,
        rows: list[dict[str, Any]],
        mapping: dict[str, str],
        options: ImportOptions,
    ) -> tuple[list[str], list[list[str]]]:
        spec = target_spec(target)
        headers = [f.label for f in spec.fields if not (target == "item" and f.key == "kind")]
        if target == "item":
            headers = ["Название", "Артикул", "Тип", "Категория", "Цена", "Себестоимость", "Ед.", "Остаток", "Склад", "Активна"]
        lines: list[list[str]] = []
        for row in rows:
            data = self.map_row(target, row, mapping, options)
            if target == "item":
                lines.append(
                    [
                        data.get("name", ""),
                        data.get("sku", ""),
                        "Услуга" if data.get("kind") == "service" else "Товар",
                        data.get("category") or "",
                        format_money(data.get("price", 0), with_currency=False),
                        format_money(data.get("cost", 0), with_currency=False),
                        data.get("unit", ""),
                        "" if data.get("stock") is None else str(data.get("stock")),
                        "да" if data.get("track_stock") else "нет",
                        "да" if data.get("active") else "нет",
                    ]
                )
            else:
                lines.append([str(data.get(f.key, "")) for f in spec.fields])
        return headers, lines

    # ------------------------------------------------------------------ import
    def import_table(
        self,
        source: LegacySource,
        table: str,
        target: str,
        mapping: dict[str, str],
        options: ImportOptions,
        user_id: int | None,
    ) -> ImportResult:
        spec = target_spec(target)
        if not mapping.get("name"):
            raise ImportError_("Не сопоставлено обязательное поле «Название»")
        rows = source.read_rows(table)
        if not rows:
            raise ImportError_("В выбранной таблице нет строк")
        result = ImportResult(target=target, table=table)
        # A safety snapshot before writing anything.
        self.db.backup(tag="before-import")
        try:
            with self.db.transaction():
                if target == "category":
                    self._import_categories(rows, mapping, options, result)
                elif target == "item":
                    self._import_items(rows, mapping, options, result, user_id)
                elif target == "payment":
                    self._import_payments(rows, mapping, options, result)
                else:
                    raise ImportError_("Неизвестный тип импорта")
        except sqlite3.Error as exc:
            logger.exception("Ошибка импорта")
            raise ImportError_(f"Импорт прерван, изменения отменены: {exc}") from exc

        with self.db.transaction():
            self.db.execute(
                """
                INSERT INTO import_jobs(source_path, table_name, target,
                                        mapping_json, result_json, status, user_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(source.path),
                    table,
                    target,
                    mapping_to_json(mapping),
                    json.dumps(
                        {
                            "created": result.created,
                            "updated": result.updated,
                            "skipped": result.skipped,
                            "stock_updated": result.stock_updated,
                            "errors": result.errors[:200],
                        },
                        ensure_ascii=False,
                    ),
                    "done" if not result.errors else "done-with-errors",
                    user_id,
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
        return result

    def _import_categories(
        self,
        rows: list[dict[str, Any]],
        mapping: dict[str, str],
        options: ImportOptions,
        result: ImportResult,
    ) -> None:
        existing = {
            str(row["name"]).casefold(): int(row["id"])
            for row in self.db.query("SELECT id, name FROM categories")
        }
        for index, row in enumerate(rows, start=2):
            try:
                with self.db.transaction():
                    data = self.map_row("category", row, mapping, options)
                    name = data["name"]
                    if not name:
                        result.skipped += 1
                        continue
                    key = name.casefold()
                    if key in existing:
                        if options.update_existing:
                            self.db.execute(
                                "UPDATE categories SET kind=?, sort_order=? WHERE id=?",
                                (data["kind"], data["sort_order"], existing[key]),
                            )
                            result.updated += 1
                        else:
                            result.skipped += 1
                    else:
                        cursor = self.db.execute(
                            "INSERT INTO categories(name, kind, sort_order, is_active) "
                            "VALUES (?, ?, ?, 1)",
                            (name, data["kind"], data["sort_order"]),
                        )
                        existing[key] = int(cursor.lastrowid)
                        result.created += 1
            except (sqlite3.Error, ValueError) as exc:
                result.errors.append(f"Строка {index}: {exc}")

    def _import_items(
        self,
        rows: list[dict[str, Any]],
        mapping: dict[str, str],
        options: ImportOptions,
        result: ImportResult,
        user_id: int | None,
    ) -> None:
        categories = {
            str(row["name"]).casefold(): int(row["id"])
            for row in self.db.query("SELECT id, name FROM categories")
        }
        items_by_sku = {
            str(row["sku"]).casefold(): int(row["id"])
            for row in self.db.query("SELECT id, sku FROM items WHERE sku IS NOT NULL")
        }
        items_by_name = {
            (str(row["name"]).casefold(), str(row["kind"])): int(row["id"])
            for row in self.db.query("SELECT id, name, kind FROM items")
        }
        stock_cache = {
            int(row["item_id"]): int(row["qty"])
            for row in self.db.query("SELECT item_id, qty FROM item_stock")
        }

        for index, row in enumerate(rows, start=2):
            try:
                with self.db.transaction():
                    data = self.map_row("item", row, mapping, options)
                    name = data["name"]
                    if not name:
                        result.skipped += 1
                        continue
                    kind = data["kind"]
                    sku = (data.get("sku") or "").strip() or None
                    category_id = self._resolve_category(
                        data.get("category"), categories, result
                    )
                    track_stock = bool(data.get("track_stock")) and kind == "product"
                    price = max(0, int(data.get("price", 0)))
                    cost = max(0, int(data.get("cost", 0)))
                    existing_id: int | None = None
                    if sku and sku.casefold() in items_by_sku:
                        existing_id = items_by_sku[sku.casefold()]
                    else:
                        existing_id = items_by_name.get((name.casefold(), kind))

                    if existing_id is not None:
                        if not options.update_existing:
                            result.skipped += 1
                            continue
                        self.db.execute(
                            """
                            UPDATE items
                            SET sku=COALESCE(?, sku), name=?, category_id=?, price=?, cost=?,
                                unit=?, track_stock=?, is_active=?,
                                updated_at=datetime('now', 'localtime')
                            WHERE id=?
                            """,
                            (
                                sku,
                                name,
                                category_id,
                                price,
                                cost,
                                data.get("unit") or "шт",
                                int(track_stock),
                                int(bool(data.get("active", True))),
                                existing_id,
                            ),
                        )
                        item_id = existing_id
                        result.updated += 1
                    else:
                        cursor = self.db.execute(
                            """
                            INSERT INTO items(sku, name, kind, category_id, price, cost, unit,
                                              track_stock, is_active, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                            """,
                            (
                                sku,
                                name,
                                kind,
                                category_id,
                                price,
                                cost,
                                data.get("unit") or "шт",
                                int(track_stock),
                                int(bool(data.get("active", True))),
                            ),
                        )
                        item_id = int(cursor.lastrowid)
                        result.created += 1
                        items_by_name[(name.casefold(), kind)] = item_id
                        if sku:
                            items_by_sku[sku.casefold()] = item_id
                        stock_cache.setdefault(item_id, 0)

                    stock = data.get("stock")
                    if options.import_stock and stock is not None and track_stock:
                        target_qty = max(0, int(stock))
                        current = stock_cache.get(item_id, 0)
                        delta = target_qty - current
                        if delta:
                            self.db.execute(
                                """
                                INSERT INTO stock_movements(item_id, qty, kind, note,
                                                            user_id, created_at)
                                VALUES (?, ?, 'import', 'Импорт из старой базы', ?, ?)
                                """,
                                (
                                    item_id,
                                    delta,
                                    user_id,
                                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                ),
                            )
                            stock_cache[item_id] = target_qty
                            result.stock_updated += 1
            except (sqlite3.Error, ValueError) as exc:
                result.errors.append(f"Строка {index}: {exc}")

    def _resolve_category(
        self,
        name: str | None,
        categories: dict[str, int],
        result: ImportResult,
    ) -> int | None:
        if not name:
            return None
        key = name.casefold()
        if key in categories:
            return categories[key]
        cursor = self.db.execute(
            "INSERT INTO categories(name, kind, sort_order, is_active) VALUES (?, 'any', 0, 1)",
            (name,),
        )
        category_id = int(cursor.lastrowid)
        categories[key] = category_id
        result.created += 1
        return category_id

    def _import_payments(
        self,
        rows: list[dict[str, Any]],
        mapping: dict[str, str],
        options: ImportOptions,
        result: ImportResult,
    ) -> None:
        existing = {
            str(row["name"]).casefold(): int(row["id"])
            for row in self.db.query("SELECT id, name FROM payment_methods")
        }
        for index, row in enumerate(rows, start=2):
            try:
                with self.db.transaction():
                    data = self.map_row("payment", row, mapping, options)
                    name = data["name"]
                    if not name:
                        result.skipped += 1
                        continue
                    key = name.casefold()
                    if key in existing:
                        if options.update_existing:
                            self.db.execute(
                                """
                                UPDATE payment_methods
                                SET kind=?, affects_cash=?, sort_order=?, is_active=?
                                WHERE id=?
                                """,
                                (
                                    data["kind"],
                                    int(bool(data.get("affects_cash"))),
                                    data["sort_order"],
                                    int(bool(data.get("active", True))),
                                    existing[key],
                                ),
                            )
                            result.updated += 1
                        else:
                            result.skipped += 1
                    else:
                        self.db.execute(
                            """
                            INSERT INTO payment_methods(name, kind, affects_cash,
                                                        sort_order, is_active)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                name,
                                data["kind"],
                                int(bool(data.get("affects_cash"))),
                                data["sort_order"],
                                int(bool(data.get("active", True))),
                            ),
                        )
                        existing[key] = 1
                        result.created += 1
            except (sqlite3.Error, ValueError) as exc:
                result.errors.append(f"Строка {index}: {exc}")

    def jobs(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.db.query(
            "SELECT * FROM import_jobs ORDER BY id DESC LIMIT ?", (int(limit),)
        )
