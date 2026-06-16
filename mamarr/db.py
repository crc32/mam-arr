import datetime
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from mamarr.config import settings


def init_db() -> None:
    db_path = settings.db_path
    parent = db_path.rsplit("/", 1)[0] if "/" in db_path else "."
    if parent:
        import os

        os.makedirs(parent, exist_ok=True)

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS covers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT,
            cover_url TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(title, author)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            torrent_id TEXT NOT NULL UNIQUE,
            title TEXT,
            author TEXT,
            narrator TEXT,
            size TEXT,
            cover_url TEXT,
            filetypes TEXT,
            added_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS watchlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ol_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            author TEXT,
            ol_cover_url TEXT,
            first_publish_year TEXT,
            series TEXT,
            mam_found INTEGER NOT NULL DEFAULT 0,
            mam_torrent_id TEXT,
            mam_title TEXT,
            last_checked TEXT,
            added_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS series_favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_key TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            last_checked_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS series_seen_torrents (
            series_favorite_id INTEGER NOT NULL,
            torrent_id TEXT NOT NULL,
            title TEXT,
            author TEXT,
            narrator TEXT,
            filetypes TEXT,
            first_seen_at TEXT NOT NULL,
            PRIMARY KEY (series_favorite_id, torrent_id),
            FOREIGN KEY (series_favorite_id) REFERENCES series_favorites(id) ON DELETE CASCADE
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS preferences (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(settings.db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def utc_now() -> str:
    return datetime.datetime.utcnow().isoformat()
