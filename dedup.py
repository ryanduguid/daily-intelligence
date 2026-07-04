import sqlite3
import os
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Where to store the "already sent" URL history. Point this at a persistent
# volume in production (e.g. SQLITE_PATH=/data/digest.db on a mounted disk).
DB_PATH = os.environ.get("SQLITE_PATH", "digest.db")


def _get_conn() -> sqlite3.Connection:
    parent = os.path.dirname(DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sent_items (
            url TEXT PRIMARY KEY,
            sent_at TEXT NOT NULL
        )"""
    )
    conn.commit()
    return conn


def is_duplicate(url: str) -> bool:
    if not url:
        return False
    conn = _get_conn()
    try:
        cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
        row = conn.execute(
            "SELECT 1 FROM sent_items WHERE url = ? AND sent_at > ?",
            (url, cutoff),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def is_duplicate_batch(urls: list[str]) -> set[str]:
    """Check multiple URLs at once. Returns the set of URLs that are duplicates."""
    urls = [u for u in urls if u]
    if not urls:
        return set()
    conn = _get_conn()
    try:
        cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
        placeholders = ",".join("?" for _ in urls)
        rows = conn.execute(
            f"SELECT url FROM sent_items WHERE url IN ({placeholders}) AND sent_at > ?",
            [*urls, cutoff],
        ).fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def mark_sent(urls: list[str]) -> None:
    if not urls:
        return
    conn = _get_conn()
    try:
        now = datetime.utcnow().isoformat()
        conn.executemany(
            "INSERT OR REPLACE INTO sent_items (url, sent_at) VALUES (?, ?)",
            [(u, now) for u in urls if u],
        )
        conn.commit()
    finally:
        conn.close()


def purge_old() -> None:
    conn = _get_conn()
    try:
        cutoff = (datetime.utcnow() - timedelta(days=30)).isoformat()
        conn.execute("DELETE FROM sent_items WHERE sent_at < ?", (cutoff,))
        conn.commit()
    finally:
        conn.close()
