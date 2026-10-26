from __future__ import annotations

import sqlite3

from pos.database import SCHEMA_VERSION, Database


def test_v1_database_is_migrated_for_service_consumables(paths):
    db = Database(paths.db_path, paths.backup_dir)
    db.connect()
    db.close()

    # Turn the freshly created v2 database into a realistic v1 database.
    conn = sqlite3.connect(str(paths.db_path))
    try:
        conn.execute(
            "INSERT INTO items(name, kind, price, cost) VALUES ('Старый товар', 'product', 100, 50)"
        )
        conn.execute("DROP TABLE service_consumables")
        conn.execute("ALTER TABLE items DROP COLUMN is_consumable")
        conn.execute("PRAGMA user_version=1")
        conn.commit()
    finally:
        conn.close()

    upgraded = Database(paths.db_path, paths.backup_dir)
    upgraded.connect()
    try:
        assert upgraded.schema_version == SCHEMA_VERSION == 2
        columns = {
            row["name"] for row in upgraded.query("PRAGMA table_info(items)")
        }
        assert "is_consumable" in columns
        assert upgraded.query_one(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='service_consumables'"
        )
        old = upgraded.query_one("SELECT * FROM items WHERE name='Старый товар'")
        assert old is not None
        assert old["is_consumable"] == 0
    finally:
        upgraded.close()
