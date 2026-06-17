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
        CREATE TABLE IF NOT EXISTS tracked_series (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            series_key TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            origin TEXT NOT NULL DEFAULT 'manual',
            auto_follow INTEGER NOT NULL DEFAULT 1,
            owned_book_count INTEGER NOT NULL DEFAULT 0,
            last_checked_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS series_seen_torrents (
            tracked_series_id INTEGER NOT NULL,
            torrent_id TEXT NOT NULL,
            title TEXT,
            author TEXT,
            narrator TEXT,
            filetypes TEXT,
            first_seen_at TEXT NOT NULL,
            PRIMARY KEY (tracked_series_id, torrent_id),
            FOREIGN KEY (tracked_series_id) REFERENCES tracked_series(id) ON DELETE CASCADE
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS library_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            external_id TEXT NOT NULL,
            title TEXT NOT NULL,
            author TEXT,
            narrator TEXT,
            series TEXT,
            series_sequence REAL,
            asin TEXT,
            isbn TEXT,
            title_key TEXT NOT NULL,
            title_author_key TEXT NOT NULL,
            series_key TEXT,
            confidence TEXT NOT NULL DEFAULT 'high',
            synced_at TEXT NOT NULL,
            UNIQUE(source, external_id)
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

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS library_sync_state (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    _migrate_series_favorites(cur)
    _migrate_library_items_columns(cur)

    conn.commit()
    conn.close()


def _migrate_library_items_columns(cur: sqlite3.Cursor) -> None:
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='library_items'"
    )
    if not cur.fetchone():
        return
    cur.execute("PRAGMA table_info(library_items)")
    columns = {col[1] for col in cur.fetchall()}
    if "title_author_key" not in columns:
        cur.execute("ALTER TABLE library_items ADD COLUMN title_author_key TEXT NOT NULL DEFAULT ''")
    if "abs_series_id" not in columns:
        cur.execute("ALTER TABLE library_items ADD COLUMN abs_series_id TEXT")


def _migrate_series_favorites(cur: sqlite3.Cursor) -> None:
    """Migrate legacy series_favorites table to tracked_series."""
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='series_favorites'"
    )
    if not cur.fetchone():
        return

    cur.execute(
        """
        INSERT OR IGNORE INTO tracked_series
            (id, series_key, display_name, origin, auto_follow, owned_book_count,
             last_checked_at, created_at)
        SELECT id, series_key, display_name, 'manual', 1, 0, last_checked_at, created_at
        FROM series_favorites
        """
    )

    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='series_seen_torrents'"
    )
    row = cur.fetchone()
    if row:
        cur.execute("PRAGMA table_info(series_seen_torrents)")
        columns = {col[1] for col in cur.fetchall()}
        if "series_favorite_id" in columns and "tracked_series_id" not in columns:
            cur.execute(
                """
                CREATE TABLE series_seen_torrents_new (
                    tracked_series_id INTEGER NOT NULL,
                    torrent_id TEXT NOT NULL,
                    title TEXT,
                    author TEXT,
                    narrator TEXT,
                    filetypes TEXT,
                    first_seen_at TEXT NOT NULL,
                    PRIMARY KEY (tracked_series_id, torrent_id),
                    FOREIGN KEY (tracked_series_id) REFERENCES tracked_series(id) ON DELETE CASCADE
                )
                """
            )
            cur.execute(
                """
                INSERT OR IGNORE INTO series_seen_torrents_new
                    (tracked_series_id, torrent_id, title, author, narrator, filetypes, first_seen_at)
                SELECT series_favorite_id, torrent_id, title, author, narrator, filetypes, first_seen_at
                FROM series_seen_torrents
                """
            )
            cur.execute("DROP TABLE series_seen_torrents")
            cur.execute("ALTER TABLE series_seen_torrents_new RENAME TO series_seen_torrents")


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
