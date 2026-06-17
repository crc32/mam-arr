from typing import Optional

from mamarr.db import get_db, utc_now


def record_download(
    torrent_id: str,
    title: str,
    author: str,
    narrator: str,
    size: str,
    cover_url: Optional[str],
    filetypes: str = "",
) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO downloads (torrent_id, title, author, narrator, size, cover_url, filetypes, added_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(torrent_id) DO UPDATE SET
                title = excluded.title,
                author = excluded.author,
                narrator = excluded.narrator,
                size = excluded.size,
                cover_url = excluded.cover_url,
                filetypes = excluded.filetypes,
                added_at = excluded.added_at
            """,
            (
                str(torrent_id),
                title,
                author,
                narrator,
                size,
                cover_url,
                filetypes,
                utc_now(),
            ),
        )
        conn.commit()


def get_downloaded_ids() -> set[str]:
    with get_db() as conn:
        rows = conn.execute("SELECT torrent_id FROM downloads").fetchall()
    return {row["torrent_id"] for row in rows}


def list_history(limit: int = 50) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, torrent_id, title, author, narrator, size, cover_url, filetypes, added_at
            FROM downloads
            ORDER BY added_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
