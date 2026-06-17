from typing import Optional

from mamarr.covers import find_cover
from mamarr.db import get_db, utc_now
from mamarr.format_filter import apply_format_preference, normalize_text
from mamarr.history import get_downloaded_ids
from mamarr.inventory.ownership import filter_results_by_ownership
from mamarr.mam.client import search_mam
from mamarr.notifications import send_series_update_notification
from mamarr.preferences import get_format_preference, get_ownership_filter_mode


def _series_key(name: str) -> str:
    return normalize_text(name)


def list_tracked_series(manual_only: bool = False) -> list[dict]:
    with get_db() as conn:
        if manual_only:
            rows = conn.execute(
                """
                SELECT id, series_key, display_name, origin, auto_follow,
                       owned_book_count, last_checked_at, created_at
                FROM tracked_series
                WHERE origin IN ('manual', 'both')
                ORDER BY display_name ASC
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, series_key, display_name, origin, auto_follow,
                       owned_book_count, last_checked_at, created_at
                FROM tracked_series
                ORDER BY display_name ASC
                """
            ).fetchall()
    return [dict(row) for row in rows]


def list_series_favorites() -> list[dict]:
    """Backward-compatible alias: manual and both-origin series."""
    return list_tracked_series(manual_only=True)


def add_series_favorite(series_name: str) -> dict:
    key = _series_key(series_name)
    if not key:
        raise ValueError("Series name is required")

    with get_db() as conn:
        existing = conn.execute(
            "SELECT id, origin FROM tracked_series WHERE series_key = ?",
            (key,),
        ).fetchone()
        if existing:
            origin = existing["origin"]
            new_origin = "both" if origin == "library" else "manual"
            conn.execute(
                """
                UPDATE tracked_series
                SET display_name = ?, origin = ?, auto_follow = 1
                WHERE series_key = ?
                """,
                (series_name.strip(), new_origin, key),
            )
            conn.commit()
            return {"status": "updated", "id": existing["id"], "series": series_name.strip()}

        conn.execute(
            """
            INSERT INTO tracked_series
                (series_key, display_name, origin, auto_follow, owned_book_count, created_at)
            VALUES (?, ?, 'manual', 1, 0, ?)
            """,
            (key, series_name.strip(), utc_now()),
        )
        conn.commit()
        fav_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    return {"status": "added", "id": fav_id, "series": series_name.strip()}


def remove_series_favorite(series_name: str) -> bool:
    key = _series_key(series_name)
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id, origin FROM tracked_series WHERE series_key = ?",
            (key,),
        ).fetchone()
        if not existing:
            return False

        if existing["origin"] == "library":
            conn.execute(
                "UPDATE tracked_series SET auto_follow = 0 WHERE series_key = ?",
                (key,),
            )
        elif existing["origin"] == "both":
            conn.execute(
                "UPDATE tracked_series SET origin = 'library', auto_follow = 0 WHERE series_key = ?",
                (key,),
            )
        else:
            conn.execute("DELETE FROM tracked_series WHERE series_key = ?", (key,))
        conn.commit()
        return True


def set_series_auto_follow(series_name: str, auto_follow: bool) -> bool:
    key = _series_key(series_name)
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE tracked_series SET auto_follow = ? WHERE series_key = ?",
            (1 if auto_follow else 0, key),
        )
        conn.commit()
        return cur.rowcount > 0


def _normalize_torrent(item: dict, downloaded_ids: set[str]) -> dict:
    tid = str(item.get("id", ""))
    title = item.get("title") or item.get("name") or ""
    author = item.get("author") or ""
    return {
        "id": item.get("id"),
        "title": title,
        "author": author,
        "series": item.get("series") or "",
        "narrator": item.get("narrator") or "",
        "size": item.get("size"),
        "seeders": item.get("seeders"),
        "filetypes": item.get("filetype") or item.get("filetypes") or "",
        "asin": item.get("asin") or item.get("asin_id") or None,
        "free": item.get("free") == "1",
        "vip": item.get("vip") == "1",
        "already_downloaded": tid in downloaded_ids,
    }


def _search_series_on_mam(series_name: str) -> list[dict]:
    from mamarr.config import settings

    if not settings.mam_cookie:
        return []
    raw = search_mam(series_name, field="series", perpage=50)
    downloaded_ids = get_downloaded_ids()
    results = [_normalize_torrent(item, downloaded_ids) for item in raw]
    results = apply_format_preference(results, get_format_preference())
    return filter_results_by_ownership(results, get_ownership_filter_mode())


def check_series_updates(series_name: Optional[str] = None, mark_seen: bool = True) -> dict:
    with get_db() as conn:
        if series_name:
            key = _series_key(series_name)
            tracked = conn.execute(
                "SELECT * FROM tracked_series WHERE series_key = ? AND auto_follow = 1",
                (key,),
            ).fetchall()
            if not tracked:
                raise ValueError("Series not tracked or auto-follow disabled")
        else:
            tracked = conn.execute(
                "SELECT * FROM tracked_series WHERE auto_follow = 1 ORDER BY display_name"
            ).fetchall()

    all_new: list[dict] = []
    per_series: dict[str, list[dict]] = {}

    for entry in tracked:
        entry_id = entry["id"]
        display = entry["display_name"]
        mam_results = _search_series_on_mam(display)

        with get_db() as conn:
            seen_rows = conn.execute(
                "SELECT torrent_id FROM series_seen_torrents WHERE tracked_series_id = ?",
                (entry_id,),
            ).fetchall()
        seen_ids = {row["torrent_id"] for row in seen_rows}

        new_for_series: list[dict] = []
        for item in mam_results:
            tid = str(item.get("id", ""))
            if not tid:
                continue
            is_new = tid not in seen_ids
            item["is_new"] = is_new
            item["tracked_series"] = display
            item["series_origin"] = entry["origin"]
            if is_new:
                new_for_series.append(item)
                all_new.append(item)

            if mark_seen:
                with get_db() as conn:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO series_seen_torrents
                            (tracked_series_id, torrent_id, title, author, narrator, filetypes, first_seen_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            entry_id,
                            tid,
                            item.get("title"),
                            item.get("author"),
                            item.get("narrator"),
                            item.get("filetypes"),
                            utc_now(),
                        ),
                    )
                    conn.commit()

        if new_for_series:
            per_series[display] = new_for_series
            send_series_update_notification(display, [i["title"] for i in new_for_series])

        with get_db() as conn:
            conn.execute(
                "UPDATE tracked_series SET last_checked_at = ? WHERE id = ?",
                (utc_now(), entry_id),
            )
            conn.commit()

    return {
        "status": "ok",
        "series_checked": len(tracked),
        "new_count": len(all_new),
        "new_books": all_new,
        "by_series": {name: books for name, books in per_series.items()},
    }


def poll_all_series_favorites() -> dict:
    return check_series_updates(series_name=None, mark_seen=True)


def search_with_format_filter(query: str, field: str = "title") -> list[dict]:
    raw = search_mam(query, field=field)
    downloaded_ids = get_downloaded_ids()
    results = []
    for item in raw:
        normalized = _normalize_torrent(item, downloaded_ids)
        try:
            normalized["cover"] = find_cover(normalized["title"], normalized["author"])
        except Exception:
            normalized["cover"] = None
        results.append(normalized)
    results = apply_format_preference(results, get_format_preference())
    return filter_results_by_ownership(results, get_ownership_filter_mode())
