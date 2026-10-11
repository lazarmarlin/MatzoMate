"""
database.py — thread-safe SQLite wrapper for Matzo Mate.

Each thread gets its own connection via threading.local(), which avoids
the "SQLite objects created in a thread can only be used in that same thread"
error that occurs when asyncio/Flask worker threads share a single connection.
"""

import sqlite3
import threading
import time
import os
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "products.db")
try:
    CACHE_TTL_DAYS = int(os.getenv("CACHE_TTL_DAYS", "30"))
except ValueError:
    CACHE_TTL_DAYS = 30
    logger.warning("CACHE_TTL_DAYS env var is not an integer, defaulting to 30")

_local = threading.local()


def _conn():
    """Return a per-thread SQLite connection, creating it if needed."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
        _conn_init(_local.conn)
    return _local.conn


def _conn_init(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS products (
            barcode     TEXT PRIMARY KEY,
            name        TEXT,
            ingredients TEXT,
            url         TEXT,
            source      TEXT,
            created_at  INTEGER DEFAULT (strftime('%s','now')),
            updated_at  INTEGER DEFAULT (strftime('%s','now'))
        )
    """)
    conn.commit()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def findProduct(barcode):
    row = _conn().execute(
        "SELECT * FROM products WHERE barcode = ?", (str(barcode),)
    ).fetchone()
    if not row:
        return None
    return {
        "product_name": row["name"],
        "ingredients":  row["ingredients"].split("||") if row["ingredients"] else [],
        "url":          row["url"],
        "source":       "cache",
        "cached_at":    row["updated_at"],
    }


def addProduct(barcode, name, ingredients, url, source=""):
    ingredient_str = "||".join(str(i) for i in ingredients)
    now = int(time.time())
    _conn().execute("""
        INSERT INTO products (barcode, name, ingredients, url, source, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(barcode) DO UPDATE SET
            name       = excluded.name,
            ingredients= excluded.ingredients,
            url        = excluded.url,
            source     = excluded.source,
            updated_at = excluded.updated_at
    """, (str(barcode), name, ingredient_str, url, source, now, now))
    _conn().commit()


def deleteProduct(barcode):
    _conn().execute("DELETE FROM products WHERE barcode = ?", (str(barcode),))
    _conn().commit()


def isExpired(barcode):
    row = _conn().execute(
        "SELECT updated_at FROM products WHERE barcode = ?", (str(barcode),)
    ).fetchone()
    if not row:
        return True
    age_days = (time.time() - row["updated_at"]) / 86400
    return age_days > CACHE_TTL_DAYS
