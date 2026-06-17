from typing import Optional

import requests

from mamarr.covers import find_cover
from mamarr.db import get_db, utc_now
from mamarr.history import record_download
from mamarr.inventory.ownership import check_ownership
from mamarr.mam.client import get_torrent_details, search_mam
from mamarr.notifications import send_watchlist_notification
from mamarr.qbit.client import QBittorrentClient, qbit_client


def search_openlibrary(query: str, limit: int = 20) -> list[dict]:
    if not query or len(query.strip()) < 2:
        return []
    response = requests.get(
        "https://openlibrary.org/search.json",
        params={
            "q": query.strip(),
            "fields": "key,title,author_name,cover_i,first_publish_year,series,subject",
            "limit": limit,
        },
        timeout=10,
        headers={"User-Agent": "MAMArr-MCP/2.0 (audiobook manager)"},
    )
    response.raise_for_status()
    results = []
    for doc in response.json().get("docs", [])[:limit]:
        cover_i = doc.get("cover_i")
        authors = doc.get("author_name") or []
        series_list = doc.get("series") or []
        results.append(
            {
                "ol_key": doc.get("key", ""),
                "title": doc.get("title", ""),
                "author": authors[0] if authors else None,
                "ol_cover_url": (
                    f"https://covers.openlibrary.org/b/id/{cover_i}-M.jpg" if cover_i else None
                ),
                "first_publish_year": str(doc.get("first_publish_year", "")) or None,
                "series": series_list[0] if series_list else None,
            }
        )
    return results


def list_watchlist() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, ol_key, title, author, ol_cover_url, first_publish_year, series,
                   mam_found, mam_torrent_id, mam_title, last_checked, added_at
            FROM watchlist
            ORDER BY mam_found DESC, added_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def add_watchlist_entry(
    ol_key: str,
    title: str,
    author: Optional[str] = None,
    ol_cover_url: Optional[str] = None,
    first_publish_year: Optional[str] = None,
    series: Optional[str] = None,
) -> dict:
    with get_db() as conn:
        try:
            conn.execute(
                """
                INSERT INTO watchlist
                    (ol_key, title, author, ol_cover_url, first_publish_year, series, added_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (ol_key, title, author, ol_cover_url, first_publish_year, series, utc_now()),
            )
            conn.commit()
            entry_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        except Exception as exc:
            if "UNIQUE" in str(exc):
                raise ValueError("Already in watchlist") from exc
            raise
    return {"status": "added", "id": entry_id}


def remove_watchlist_entry(entry_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM watchlist WHERE id = ?", (entry_id,))
        conn.commit()
        return cur.rowcount > 0


def _title_match(watch_title: str, mam_title: str) -> bool:
    a = watch_title.lower().strip()
    b = mam_title.lower().strip()
    return a in b or b in a


def poll_watchlist(auto_download: bool = True) -> dict:
    """Search MAM for unwatched watchlist entries."""
    from mamarr.config import settings

    if not settings.mam_cookie:
        return {"status": "skipped", "reason": "MAM_COOKIE not configured"}

    with get_db() as conn:
        entries = conn.execute("SELECT * FROM watchlist WHERE mam_found = 0").fetchall()

    found = 0
    downloaded = 0
    qbit = qbit_client if auto_download and settings.qbittorrent_url else None

    for entry in entries:
        title = entry["title"]
        author = entry["author"] or ""
        try:
            data = search_mam(title, field="title", perpage=5)
            match = None
            for item in data:
                mam_title = item.get("title") or item.get("name") or ""
                if _title_match(title, mam_title):
                    match = item
                    break

            with get_db() as conn:
                if match:
                    mam_tid = int(match.get("id", 0))
                    mam_title = match.get("title") or match.get("name") or title
                    found += 1
                    success = False
                    if qbit and mam_tid:
                        ownership = check_ownership(
                            mam_title,
                            author,
                            match.get("narrator") or "",
                        )
                        if ownership.owned:
                            conn.execute(
                                """
                                UPDATE watchlist
                                SET mam_found = 1, mam_torrent_id = ?, mam_title = ?,
                                    last_checked = ?
                                WHERE id = ?
                                """,
                                (str(mam_tid), mam_title, utc_now(), entry["id"]),
                            )
                            conn.commit()
                            continue
                        try:
                            filetypes = match.get("filetype") or match.get("filetypes") or ""
                            qbit.add_from_mam(mam_tid, filetypes=filetypes)
                            record_download(
                                str(mam_tid),
                                mam_title,
                                author,
                                match.get("narrator") or "",
                                str(match.get("size") or ""),
                                entry["ol_cover_url"] or find_cover(mam_title, author),
                                filetypes,
                            )
                            conn.execute("DELETE FROM watchlist WHERE id = ?", (entry["id"],))
                            success = True
                            downloaded += 1
                        except Exception:
                            conn.execute(
                                """
                                UPDATE watchlist
                                SET mam_found = 1, mam_torrent_id = ?, mam_title = ?, last_checked = ?
                                WHERE id = ?
                                """,
                                (str(mam_tid), mam_title, utc_now(), entry["id"]),
                            )
                    else:
                        conn.execute(
                            """
                            UPDATE watchlist
                            SET mam_found = 1, mam_torrent_id = ?, mam_title = ?, last_checked = ?
                            WHERE id = ?
                            """,
                            (str(mam_tid), mam_title, utc_now(), entry["id"]),
                        )
                    conn.commit()
                    send_watchlist_notification(title, author, str(mam_tid), auto_downloaded=success)
                else:
                    conn.execute(
                        "UPDATE watchlist SET last_checked = ? WHERE id = ?",
                        (utc_now(), entry["id"]),
                    )
                    conn.commit()
        except Exception:
            continue

    return {
        "status": "ok",
        "checked": len(entries),
        "found": found,
        "downloaded": downloaded,
    }


def download_watchlist_entry(entry_id: int) -> dict:
    with get_db() as conn:
        entry = conn.execute("SELECT * FROM watchlist WHERE id = ?", (entry_id,)).fetchone()
    if not entry:
        raise ValueError("Watchlist entry not found")
    if not entry["mam_found"] or not entry["mam_torrent_id"]:
        raise ValueError("Book not yet found on MAM")

    tid = int(entry["mam_torrent_id"])
    torrent_data = get_torrent_details(tid) or {}
    title = entry["mam_title"] or entry["title"]
    author = entry["author"] or torrent_data.get("author") or ""
    narrator = torrent_data.get("narrator") or ""

    ownership = check_ownership(title, author, narrator)
    if ownership.owned:
        raise ValueError(
            f"Already owned ({ownership.match_type} via {ownership.source})"
        )
    size = str(torrent_data.get("size") or "")
    filetypes = torrent_data.get("filetypes") or torrent_data.get("filetype") or ""
    cover = entry["ol_cover_url"] or find_cover(title, author)

    qbit_client.add_from_mam(tid, filetypes=filetypes)
    record_download(str(tid), title, author, narrator, size, cover, filetypes)

    with get_db() as conn:
        conn.execute("DELETE FROM watchlist WHERE id = ?", (entry_id,))
        conn.commit()

    return {"status": "ok", "torrent_id": tid, "title": title}
