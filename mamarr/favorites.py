from typing import Optional

from mamarr.covers import find_cover
from mamarr.db import get_db, utc_now
from mamarr.format_filter import apply_format_preference, normalize_text
from mamarr.history import get_downloaded_ids
from mamarr.inventory.ownership import filter_results_by_ownership
from mamarr.inventory.format_swap import find_potential_swaps, load_seen_torrent_ids
from mamarr.inventory.series_gaps import find_missing_series_books, load_seen_book_keys, mam_book_identity_key
from mamarr.mam.client import search_mam, search_mam_all
from mamarr.notifications import send_series_swap_notification, send_series_update_notification
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


def _fetch_series_mam_results(series_name: str) -> list[dict]:
    from mamarr.config import settings

    if not settings.mam_cookie:
        return []
    raw = search_mam_all(series_name, field="series", perpage=100)
    downloaded_ids = get_downloaded_ids()
    return [_normalize_torrent(item, downloaded_ids) for item in raw]


def _search_series_on_mam(series_name: str) -> list[dict]:
    return apply_format_preference(_fetch_series_mam_results(series_name), get_format_preference())


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

    all_missing: list[dict] = []
    all_new_uploads: list[dict] = []
    all_potential_swaps: list[dict] = []
    all_new_swaps: list[dict] = []
    per_series: dict[str, dict[str, list[dict]]] = {}

    for entry in tracked:
        entry_id = entry["id"]
        display = entry["display_name"]
        series_key = entry["series_key"]
        raw_results = _fetch_series_mam_results(display)
        mam_results = apply_format_preference(raw_results, get_format_preference())

        seen_book_keys = load_seen_book_keys(entry_id, display)
        seen_torrent_ids = load_seen_torrent_ids(entry_id)

        missing_for_series = find_missing_series_books(
            mam_results,
            series_key=series_key,
            series_name=display,
        )

        swaps_for_series = find_potential_swaps(
            raw_results,
            series_key=series_key,
            series_name=display,
        )

        new_uploads_for_series: list[dict] = []
        for item in missing_for_series:
            tid = str(item.get("id", ""))
            if not tid:
                continue
            book_key = item.get("book_identity_key") or mam_book_identity_key(item, display)
            item["book_identity_key"] = book_key
            item["is_missing"] = True
            item["is_new_upload"] = book_key not in seen_book_keys
            item["tracked_series"] = display
            item["series_origin"] = entry["origin"]
            item["torrent_id"] = tid
            all_missing.append(item)
            if item["is_new_upload"]:
                new_uploads_for_series.append(item)
                all_new_uploads.append(item)

        new_swaps_for_series: list[dict] = []
        for item in swaps_for_series:
            tid = str(item.get("id", ""))
            if not tid:
                continue
            item["tracked_series"] = display
            item["series_origin"] = entry["origin"]
            item["torrent_id"] = tid
            item["is_new_swap"] = tid not in seen_torrent_ids
            all_potential_swaps.append(item)
            if item["is_new_swap"]:
                new_swaps_for_series.append(item)
                all_new_swaps.append(item)

        if mark_seen:
            with get_db() as conn:
                for item in raw_results:
                    tid = str(item.get("id", ""))
                    if not tid:
                        continue
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

        if missing_for_series or swaps_for_series:
            per_series[display] = {
                "missing": missing_for_series,
                "new_uploads": new_uploads_for_series,
                "potential_swaps": swaps_for_series,
                "new_swaps": new_swaps_for_series,
            }
        if new_uploads_for_series:
            send_series_update_notification(display, [i["title"] for i in new_uploads_for_series])
        if new_swaps_for_series:
            send_series_swap_notification(display, [i["title"] for i in new_swaps_for_series])

        with get_db() as conn:
            conn.execute(
                "UPDATE tracked_series SET last_checked_at = ? WHERE id = ?",
                (utc_now(), entry_id),
            )
            conn.commit()

    return {
        "status": "ok",
        "series_checked": len(tracked),
        "missing_count": len(all_missing),
        "missing_books": all_missing,
        "new_upload_count": len(all_new_uploads),
        "new_uploads": all_new_uploads,
        "potential_swap_count": len(all_potential_swaps),
        "potential_swaps": all_potential_swaps,
        "new_swap_count": len(all_new_swaps),
        "new_swaps": all_new_swaps,
        "new_count": len(all_missing),
        "new_books": all_missing,
        "by_series": per_series,
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
