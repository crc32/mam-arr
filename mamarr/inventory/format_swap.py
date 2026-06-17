from mamarr.db import get_db
from mamarr.format_filter import has_m4_format, owned_is_mp3_only, parse_filetypes
from mamarr.inventory.ownership import title_author_key
from mamarr.inventory.series_gaps import (
    _matches_owned_book,
    get_owned_books_for_series,
    is_book_owned_for_series,
    mam_book_identity_key,
)


def load_seen_torrent_ids(tracked_series_id: int) -> set[str]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT torrent_id FROM series_seen_torrents WHERE tracked_series_id = ?",
            (tracked_series_id,),
        ).fetchall()
    return {row["torrent_id"] for row in rows}


def get_owned_formats_for_book(
    item: dict,
    series_name: str,
    owned_books: list[dict],
) -> set[str]:
    title = item.get("title") or ""
    author = item.get("author") or ""
    narrator = item.get("narrator") or ""
    formats: set[str] = set()

    with get_db() as conn:
        title_keys: set[str] = {title_author_key(title, author)}
        for owned in owned_books:
            if _matches_owned_book(
                title=title,
                author=author,
                narrator=narrator,
                asin=item.get("asin"),
                isbn=item.get("isbn"),
                series_name=series_name,
                owned=owned,
            ):
                if owned.get("title_key"):
                    title_keys.add(owned["title_key"])
                if owned.get("title_author_key"):
                    title_keys.add(owned["title_author_key"])

        for key in title_keys:
            rows = conn.execute(
                """
                SELECT filetypes FROM library_items
                WHERE (title_author_key = ? OR title_key = ?)
                  AND filetypes IS NOT NULL AND filetypes != ''
                """,
                (key, key),
            ).fetchall()
            for row in rows:
                formats |= parse_filetypes(row["filetypes"])

            rows = conn.execute(
                """
                SELECT filetypes FROM downloads
                WHERE title_author_key = ? AND filetypes IS NOT NULL AND filetypes != ''
                """,
                (key,),
            ).fetchall()
            for row in rows:
                formats |= parse_filetypes(row["filetypes"])

    return formats


def find_potential_swaps(
    mam_results: list[dict],
    *,
    series_key: str,
    series_name: str,
) -> list[dict]:
    owned_books = get_owned_books_for_series(series_key)
    swaps: list[dict] = []
    seen_books: set[str] = set()

    for item in mam_results:
        if not has_m4_format(item.get("filetypes") or ""):
            continue
        if not is_book_owned_for_series(item, series_name, owned_books):
            continue

        book_key = mam_book_identity_key(item, series_name)
        if book_key in seen_books:
            continue
        seen_books.add(book_key)

        owned_formats = get_owned_formats_for_book(item, series_name, owned_books)
        if not owned_is_mp3_only(owned_formats):
            continue

        enriched = dict(item)
        enriched["book_identity_key"] = book_key
        enriched["potential_swap"] = True
        enriched["owned_formats"] = sorted(owned_formats)
        enriched["upgrade_formats"] = sorted(parse_filetypes(item.get("filetypes") or "") & {"m4a", "m4b"})
        swaps.append(enriched)

    return swaps
