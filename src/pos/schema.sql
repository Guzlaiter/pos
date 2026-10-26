-- POS database schema (version 2).
-- All money values are integer cents. Timestamps are local time strings
-- in the format 'YYYY-MM-DD HH:MM:SS'.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    full_name       TEXT NOT NULL DEFAULT '',
    role            TEXT NOT NULL CHECK (role IN ('admin', 'seller')),
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS user_permissions (
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    permission      TEXT NOT NULL,
    PRIMARY KEY (user_id, permission)
);

CREATE TABLE IF NOT EXISTS categories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    kind            TEXT NOT NULL DEFAULT 'any' CHECK (kind IN ('product', 'service', 'any')),
    sort_order      INTEGER NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sku             TEXT UNIQUE,
    name            TEXT NOT NULL,
    kind            TEXT NOT NULL CHECK (kind IN ('product', 'service')),
    category_id     INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    price           INTEGER NOT NULL DEFAULT 0 CHECK (price >= 0),
    cost            INTEGER NOT NULL DEFAULT 0 CHECK (cost >= 0),
    unit            TEXT NOT NULL DEFAULT 'шт',
    track_stock     INTEGER NOT NULL DEFAULT 1,
    is_consumable   INTEGER NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_category ON items(category_id);
CREATE INDEX IF NOT EXISTS idx_items_active ON items(is_active);

-- Materials consumed by services. One consumable can be shared by any
-- number of services; qty is how much one unit of the service consumes.
CREATE TABLE IF NOT EXISTS service_consumables (
    service_item_id     INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    consumable_item_id  INTEGER NOT NULL REFERENCES items(id) ON DELETE RESTRICT,
    qty                 INTEGER NOT NULL CHECK (qty > 0),
    PRIMARY KEY (service_item_id, consumable_item_id),
    CHECK (service_item_id <> consumable_item_id)
);

CREATE INDEX IF NOT EXISTS idx_service_consumables_consumable
    ON service_consumables(consumable_item_id);

CREATE TABLE IF NOT EXISTS payment_methods (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    kind            TEXT NOT NULL DEFAULT 'other'
                    CHECK (kind IN ('cash', 'qr', 'transfer', 'terminal', 'other')),
    affects_cash    INTEGER NOT NULL DEFAULT 0,
    is_active       INTEGER NOT NULL DEFAULT 1,
    sort_order      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS price_lists (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    is_active       INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS price_list_items (
    price_list_id   INTEGER NOT NULL REFERENCES price_lists(id) ON DELETE CASCADE,
    item_id         INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    price           INTEGER NOT NULL CHECK (price >= 0),
    PRIMARY KEY (price_list_id, item_id)
);

CREATE TABLE IF NOT EXISTS shifts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER NOT NULL REFERENCES users(id),
    opened_at           TEXT NOT NULL,
    closed_at           TEXT,
    status              TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    opening_cash        INTEGER NOT NULL DEFAULT 0 CHECK (opening_cash >= 0),
    closing_cash        INTEGER,
    expected_cash       INTEGER,
    cash_difference     INTEGER,
    closed_by_user_id   INTEGER REFERENCES users(id),
    note                TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_shift_one_open_per_user
    ON shifts(user_id) WHERE status = 'open';
CREATE INDEX IF NOT EXISTS idx_shifts_status ON shifts(status);
CREATE INDEX IF NOT EXISTS idx_shifts_opened ON shifts(opened_at);

CREATE TABLE IF NOT EXISTS shift_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    shift_id        INTEGER NOT NULL REFERENCES shifts(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL,
    details         TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_shift_events_shift ON shift_events(shift_id);

CREATE TABLE IF NOT EXISTS sales (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    number          TEXT NOT NULL UNIQUE,
    shift_id        INTEGER NOT NULL REFERENCES shifts(id),
    user_id         INTEGER NOT NULL REFERENCES users(id),
    status          TEXT NOT NULL DEFAULT 'completed'
                    CHECK (status IN ('completed', 'voided')),
    subtotal        INTEGER NOT NULL CHECK (subtotal >= 0),
    discount        INTEGER NOT NULL DEFAULT 0 CHECK (discount >= 0),
    total           INTEGER NOT NULL CHECK (total >= 0),
    note            TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sales_shift ON sales(shift_id);
CREATE INDEX IF NOT EXISTS idx_sales_created ON sales(created_at);
CREATE INDEX IF NOT EXISTS idx_sales_user ON sales(user_id);

CREATE TABLE IF NOT EXISTS sale_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id         INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    item_id         INTEGER REFERENCES items(id),
    name_snapshot   TEXT NOT NULL,
    kind            TEXT NOT NULL,
    qty             INTEGER NOT NULL CHECK (qty > 0),
    unit_price      INTEGER NOT NULL CHECK (unit_price >= 0),
    cost            INTEGER NOT NULL DEFAULT 0,
    line_total      INTEGER NOT NULL CHECK (line_total >= 0)
);

CREATE INDEX IF NOT EXISTS idx_sale_items_sale ON sale_items(sale_id);
CREATE INDEX IF NOT EXISTS idx_sale_items_item ON sale_items(item_id);

CREATE TABLE IF NOT EXISTS sale_payments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sale_id         INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
    method_id       INTEGER REFERENCES payment_methods(id),
    method_name     TEXT NOT NULL,
    method_kind     TEXT NOT NULL,
    affects_cash    INTEGER NOT NULL DEFAULT 0,
    amount          INTEGER NOT NULL CHECK (amount > 0),
    reference       TEXT
);

CREATE INDEX IF NOT EXISTS idx_sale_payments_sale ON sale_payments(sale_id);

CREATE TABLE IF NOT EXISTS stock_movements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    qty             INTEGER NOT NULL,
    kind            TEXT NOT NULL,
    ref_type        TEXT,
    ref_id          INTEGER,
    note            TEXT,
    user_id         INTEGER REFERENCES users(id),
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_stock_item ON stock_movements(item_id);
CREATE INDEX IF NOT EXISTS idx_stock_created ON stock_movements(created_at);

CREATE VIEW IF NOT EXISTS item_stock AS
SELECT i.id AS item_id, COALESCE(SUM(m.qty), 0) AS qty
FROM items i
LEFT JOIN stock_movements m ON m.item_id = i.id
GROUP BY i.id;

CREATE TABLE IF NOT EXISTS settings (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path     TEXT NOT NULL,
    table_name      TEXT NOT NULL,
    target          TEXT NOT NULL,
    mapping_json    TEXT NOT NULL,
    result_json     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'done',
    user_id         INTEGER REFERENCES users(id),
    created_at      TEXT NOT NULL
);
