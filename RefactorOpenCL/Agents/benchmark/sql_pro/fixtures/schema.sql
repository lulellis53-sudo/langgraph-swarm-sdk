-- E-commerce schema for sql-pro benchmark cases (SQLite).
PRAGMA foreign_keys = ON;

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    country TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE orders (
    order_id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers (customer_id),
    order_date TEXT NOT NULL,
    total REAL NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'completed', 'cancelled'))
);

CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders (order_id),
    quantity INTEGER NOT NULL CHECK (quantity > 0)
);
