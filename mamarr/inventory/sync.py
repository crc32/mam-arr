import re
from typing import Optional

from mamarr.abs.client import AudiobookshelfError, abs_client
from mamarr.config import settings
from mamarr.db import get_db, utc_now
from mamarr.format_filter import dedup_key, normalize_text
from mamarr.inventory.ownership import title_author_key
from mamarr.qbit.client import QBittorrentError, qbit_client


def _series_key(name: str) -> str:
    return normalize_text(name)


def _parse_qbit_name(name: str) -> dict:
    """Best-effort parse of torrent display name into title/author."""
    title = name.strip()
    author = ""
    narrator = ""

    by_match = re.match(r"^(?P<title>.+?)\s+by\s+(?P<author>.+)$", title, re.I)
    if by_match:
        title = by_match.group("title").strip()
        rest = by_match.group("author").strip()
        if " - " in rest:
            author, narrator = [p.strip() for p in rest.split(" - ", 1)]
        else:
            author = rest

    return {"title": title, "author": author, "narrator": narrator}


def _upsert_library_item(
    conn,
    *,
    source: str,
    external_id: str,
    title: str,
    author: str,
    narrator: str,
    series: str,
    series_sequence: Optional[float],
    asin: Optional[str],
    isbn: Optional[str],
    confidence: str,
) -> None:
    conn.execute(
        """
        INSERT INTO library_items
            (source, external_id, title, author, narrator, series, series_sequence,
             asin, isbn, title_key, title_author_key, series_key, confidence, synced_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, external_id) DO UPDATE SET
            title = excluded.title,
            author = excluded.author,
            narrator = excluded.narrator,
            series = excluded.series,
            series_sequence = excluded.series_sequence,
            asin = excluded.asin,
            isbn = excluded.isbn,
            title_key = excluded.title_key,
            title_author_key = excluded.title_author_key,
            series_key = excluded.series_key,
            confidence = excluded.confidence,
            synced_at = excluded.synced_at
        """,
        (
            source,
            external_id,
            title,
            author or "",
            narrator or "",
            series or "",
            series_sequence,
            asin,
            isbn,
            dedup_key(title, author or "", narrator or ""),
            title_author_key(title, author or ""),
            _series_key(series) if series else None,
            confidence,
            utc_now(),
        ),
    )


def _sync_audiobookshelf(conn) -> dict:
    if not settings.audiobookshelf_url or not settings.audiobookshelf_token:
        return {"status": "skipped", "reason": "Audiobookshelf not configured"}

    try:
        items = abs_client.iter_library_items()
    except AudiobookshelfError as exc:
        return {"status": "error", "source": "audiobookshelf", "error": str(exc)}

    seen_ids: set[str] = set()
    count = 0
    for raw in items:
        parsed = abs_client.parse_item(raw)
        if not parsed or not parsed["external_id"]:
            continue
        seen_ids.add(parsed["external_id"])
        _upsert_library_item(
            conn,
            source="audiobookshelf",
            external_id=parsed["external_id"],
            title=parsed["title"],
            author=parsed["author"],
            narrator=parsed["narrator"],
            series=parsed["series"],
            series_sequence=parsed["series_sequence"],
            asin=parsed["asin"],
            isbn=parsed["isbn"],
            confidence="high",
        )
        count += 1

    if seen_ids:
        placeholders = ",".join("?" for _ in seen_ids)
        conn.execute(
            f"DELETE FROM library_items WHERE source = 'audiobookshelf' AND external_id NOT IN ({placeholders})",
            list(seen_ids),
        )

    return {"status": "ok", "source": "audiobookshelf", "count": count}


def _sync_qbittorrent(conn) -> dict:
    if not settings.qbittorrent_url:
        return {"status": "skipped", "reason": "qBittorrent not configured"}

    try:
        torrents = qbit_client.list_inventory_torrents()
    except QBittorrentError as exc:
        return {"status": "error", "source": "qbittorrent", "error": str(exc)}

    seen_hashes: set[str] = set()
    count = 0
    for tor in torrents:
        info_hash = tor.get("hash") or ""
        if not info_hash:
            continue
        seen_hashes.add(info_hash)
        parsed = _parse_qbit_name(tor.get("name") or "")
        _upsert_library_item(
            conn,
            source="qbittorrent",
            external_id=info_hash,
            title=parsed["title"],
            author=parsed["author"],
            narrator=parsed["narrator"],
            series="",
            series_sequence=None,
            asin=None,
            isbn=None,
            confidence="medium",
        )
        count += 1

    if seen_hashes:
        placeholders = ",".join("?" for _ in seen_hashes)
        conn.execute(
            f"DELETE FROM library_items WHERE source = 'qbittorrent' AND external_id NOT IN ({placeholders})",
            list(seen_hashes),
        )
    else:
        conn.execute("DELETE FROM library_items WHERE source = 'qbittorrent'")

    return {"status": "ok", "source": "qbittorrent", "count": count}


def _refresh_tracked_series_from_library(conn) -> int:
    rows = conn.execute(
        """
        SELECT series_key, MIN(series) AS display_name, COUNT(*) AS owned_count
        FROM library_items
        WHERE series_key IS NOT NULL AND series_key != ''
        GROUP BY series_key
        """
    ).fetchall()

    updated = 0
    for row in rows:
        series_key = row["series_key"]
        display = row["display_name"] or series_key
        owned_count = row["owned_count"]

        existing = conn.execute(
            "SELECT id, origin FROM tracked_series WHERE series_key = ?",
            (series_key,),
        ).fetchone()

        if existing:
            origin = existing["origin"]
            if origin == "manual":
                new_origin = "both"
            else:
                new_origin = origin if origin else "library"
            conn.execute(
                """
                UPDATE tracked_series
                SET display_name = ?, origin = ?, owned_book_count = ?, auto_follow = 1
                WHERE series_key = ?
                """,
                (display, new_origin, owned_count, series_key),
            )
        else:
            conn.execute(
                """
                INSERT INTO tracked_series
                    (series_key, display_name, origin, auto_follow, owned_book_count, created_at)
                VALUES (?, ?, 'library', 1, ?, ?)
                """,
                (series_key, display, owned_count, utc_now()),
            )
        updated += 1

    return updated


def sync_library_inventory() -> dict:
    with get_db() as conn:
        abs_result = _sync_audiobookshelf(conn)
        qbit_result = _sync_qbittorrent(conn)
        series_count = _refresh_tracked_series_from_library(conn)
        conn.execute(
            """
            INSERT INTO library_sync_state (key, value) VALUES ('last_sync_at', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (utc_now(),),
        )
        conn.commit()

    total_items = 0
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM library_items").fetchone()
        total_items = row["c"] if row else 0

    return {
        "status": "ok",
        "audiobookshelf": abs_result,
        "qbittorrent": qbit_result,
        "tracked_series_updated": series_count,
        "total_library_items": total_items,
        "synced_at": utc_now(),
    }


def list_owned_books(limit: int = 100, source: str | None = None) -> list[dict]:
    query = """
        SELECT source, external_id, title, author, narrator, series, series_sequence,
               asin, isbn, confidence, synced_at
        FROM library_items
    """
    params: list = []
    if source:
        query += " WHERE source = ?"
        params.append(source)
    query += " ORDER BY title ASC LIMIT ?"
    params.append(limit)

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_library_stats() -> dict:
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM library_items").fetchone()["c"]
        by_source = conn.execute(
            "SELECT source, COUNT(*) AS c FROM library_items GROUP BY source"
        ).fetchall()
        last_sync = conn.execute(
            "SELECT value FROM library_sync_state WHERE key = 'last_sync_at'"
        ).fetchone()
        tracked = conn.execute(
            "SELECT COUNT(*) AS c FROM tracked_series WHERE auto_follow = 1"
        ).fetchone()["c"]

    return {
        "total_items": total,
        "by_source": {row["source"]: row["c"] for row in by_source},
        "tracked_series_count": tracked,
        "last_sync_at": last_sync["value"] if last_sync else None,
        "audiobookshelf_configured": bool(settings.audiobookshelf_url and settings.audiobookshelf_token),
        "qbittorrent_configured": bool(settings.qbittorrent_url),
    }
