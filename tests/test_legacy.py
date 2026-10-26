from __future__ import annotations

import csv
import sqlite3

import pytest

from pos.services.errors import ImportError_
from pos.services.legacy import (
    ImportOptions,
    LegacySource,
    guess_target,
    suggest_mapping,
)


def _make_source(path):
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE "Товары" (
                id INTEGER PRIMARY KEY,
                "Наименование" TEXT NOT NULL,
                "Артикул" TEXT,
                "Тип" TEXT,
                "Категория" TEXT,
                "Цена" REAL,
                "Себестоимость" REAL,
                "Остаток" INTEGER
            )
            """
        )
        conn.executemany(
            'INSERT INTO "Товары" '
            '("Наименование","Артикул","Тип","Категория","Цена","Себестоимость","Остаток") '
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("Кофе", "C-1", "Товар", "Напитки", 150.0, 60.0, 10),
                ("Чай", "T-1", "Товар", "Напитки", 100.0, 40.0, 5),
                ("Доставка", "D-1", "Услуга", "Услуги", 300.0, 100.0, None),
            ],
        )
        conn.execute(
            """
            CREATE TABLE "Оплата" (
                id INTEGER PRIMARY KEY,
                "Название" TEXT,
                "Тип" TEXT,
                "Касса" TEXT,
                "Порядок" INTEGER
            )
            """
        )
        conn.executemany(
            'INSERT INTO "Оплата" ("Название","Тип","Касса","Порядок") VALUES (?, ?, ?, ?)',
            [("Банковская карта", "карта", "нет", 50)],
        )
        conn.commit()
    finally:
        conn.close()


def test_source_inspection_and_automapping(tmp_path):
    path = tmp_path / "old.db"
    _make_source(path)

    source = LegacySource(path)
    tables = {table.name: table for table in source.tables()}
    assert set(tables) == {"Товары", "Оплата"}
    assert tables["Товары"].row_count == 3
    assert "Наименование" in tables["Товары"].columns

    assert guess_target("Товары") == "item"
    assert guess_target("Оплата") == "payment"
    assert guess_target("Категории") == "category"

    mapping = suggest_mapping("item", tables["Товары"].columns)
    assert mapping["name"] == "col:Наименование"
    assert mapping["sku"] == "col:Артикул"
    assert mapping["kind"] == "col:Тип"
    assert mapping["category"] == "col:Категория"
    assert mapping["price"] == "col:Цена"
    assert mapping["cost"] == "col:Себестоимость"
    assert mapping["stock"] == "col:Остаток"

    payments = suggest_mapping("payment", tables["Оплата"].columns)
    assert payments["name"] == "col:Название"
    assert payments["kind"] == "col:Тип"
    assert payments["affects_cash"] == "col:Касса"
    assert payments["sort_order"] == "col:Порядок"


def test_preview_maps_values(tmp_path, ctx):
    path = tmp_path / "old.db"
    _make_source(path)
    source = LegacySource(path)
    options = ImportOptions()
    mapping = suggest_mapping("item", source.columns("Товары"))
    rows = source.read_rows("Товары", limit=3)

    headers, lines = ctx.legacy.preview("item", rows, mapping, options)
    assert len(headers) == 10
    assert len(lines) == 3
    coffee = next(line for line in lines if line[0] == "Кофе")
    assert coffee[1] == "C-1"
    assert coffee[2] == "Товар"
    assert coffee[3] == "Напитки"
    assert coffee[4] == "150,00"
    assert coffee[5] == "60,00"
    assert coffee[7] == "10"
    assert coffee[8] == "да"


def test_import_items_categories_and_stock_then_update(tmp_path, ctx, admin):
    path = tmp_path / "old.db"
    _make_source(path)
    source = LegacySource(path)
    mapping = suggest_mapping("item", source.columns("Товары"))

    result = ctx.legacy.import_table(
        source, "Товары", "item", mapping, ImportOptions(), admin.id
    )
    assert result.errors == []
    assert result.created == 5  # three items + two categories
    assert result.stock_updated == 2  # service has no stock

    items = {row["name"]: row for row in ctx.db.query("SELECT * FROM items")}
    assert set(items) == {"Кофе", "Чай", "Доставка"}
    coffee = items["Кофе"]
    assert coffee["price"] == 15000
    assert coffee["cost"] == 6000
    assert coffee["kind"] == "product"
    assert ctx.catalog.stock_balance(coffee["id"]) == 10
    delivery = items["Доставка"]
    assert delivery["kind"] == "service"
    assert not delivery["track_stock"]

    category = ctx.db.query_one("SELECT * FROM categories WHERE name='Напитки'")
    assert category is not None
    assert coffee["category_id"] == category["id"]

    movements = ctx.db.query(
        "SELECT * FROM stock_movements WHERE item_id=? ORDER BY id", (coffee["id"],)
    )
    assert len(movements) == 1
    assert movements[0]["kind"] == "import"
    assert movements[0]["qty"] == 10
    assert movements[0]["user_id"] == admin.id

    jobs = ctx.legacy.jobs()
    assert len(jobs) == 1
    assert jobs[0]["target"] == "item"
    assert jobs[0]["status"] == "done"

    # A repeated import must update instead of duplicating, and only adjust
    # stock when the source quantity actually changed.
    conn = sqlite3.connect(path)
    conn.execute('UPDATE "Товары" SET "Цена"=175 WHERE "Наименование"=\'Кофе\'')
    conn.commit()
    conn.close()
    updated = ctx.legacy.import_table(
        source, "Товары", "item", mapping, ImportOptions(), admin.id
    )
    assert updated.created == 0
    assert updated.updated == 3
    assert updated.stock_updated == 0
    coffee = ctx.db.query_one("SELECT * FROM items WHERE name='Кофе'")
    assert coffee["price"] == 17500
    assert ctx.db.scalar("SELECT COUNT(*) FROM items") == 3

    skipped = ctx.legacy.import_table(
        source,
        "Товары",
        "item",
        mapping,
        ImportOptions(update_existing=False),
        admin.id,
    )
    assert skipped.created == 0
    assert skipped.skipped == 3


def test_import_payment_methods(tmp_path, ctx):
    path = tmp_path / "old.db"
    _make_source(path)
    source = LegacySource(path)
    mapping = suggest_mapping("payment", source.columns("Оплата"))

    result = ctx.legacy.import_table(
        source, "Оплата", "payment", mapping, ImportOptions(), None
    )
    assert result.errors == []
    assert result.created == 1
    method = next(
        method for method in ctx.payments.list_methods() if method.name == "Банковская карта"
    )
    assert method.kind == "terminal"
    assert method.affects_cash is False


def test_csv_import(tmp_path, ctx, admin):
    path = tmp_path / "price.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(["Название", "Цена", "Остаток", "Категория"])
        writer.writerow(["Сок", "120,50", "7", "Напитки"])
        writer.writerow(["Вода", "80", "3", "Напитки"])

    source = LegacySource(path)
    assert source.kind == "csv"
    table = source.tables()[0]
    assert table.name == "price"
    assert table.row_count == 2

    mapping = suggest_mapping("item", table.columns)
    result = ctx.legacy.import_table(
        source, table.name, "item", mapping, ImportOptions(), admin.id
    )
    assert result.errors == []
    assert result.created == 3  # two items + category
    item = ctx.db.query_one("SELECT * FROM items WHERE name='Сок'")
    assert item["price"] == 12050
    assert ctx.catalog.stock_balance(item["id"]) == 7


def test_missing_file_and_required_mapping(tmp_path, ctx):
    with pytest.raises(ImportError_):
        LegacySource(tmp_path / "missing.db")

    path = tmp_path / "old.db"
    _make_source(path)
    source = LegacySource(path)
    with pytest.raises(ImportError_):
        ctx.legacy.import_table(
            source,
            "Товары",
            "item",
            {"name": ""},
            ImportOptions(),
            None,
        )
