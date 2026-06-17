import re
from typing import Optional

from mamarr.db import get_db
from mamarr.format_filter import dedup_key, normalize_text
from mamarr.inventory.ownership import check_ownership, title_author_key


def mam_book_identity_key(item: dict, series_name: str) -> str:
    return series_book_key(
        item.get("title") or "",
        item.get("author") or "",
        series_name,
    )


def normalize_series_title(title: str, series_name: str = "") -> str:
    """Normalize a book title within a series for fuzzy comparison."""
    text = normalize_text(title)
    if series_name:
        series_norm = normalize_text(series_name)
        for prefix in (f"{series_norm}:", f"{series_norm} -", f"{series_norm} "):
            if text.startswith(prefix):
                text = text[len(prefix) :].strip()
                break
    text = re.sub(r"^(?:book\s*)?\d+\s*[-.:)]\s*", "", text)
    text = re.sub(r"^\d+\s+", "", text)
    return text.strip()


def series_book_key(title: str, author: str, series_name: str = "") -> str:
    """Canonical identity for a book within a series (ignores encoding/torrent)."""
    return "|".join((normalize_series_title(title, series_name), normalize_text(author)))


def load_seen_book_keys(tracked_series_id: int, series_name: str) -> set[str]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT title, author
            FROM series_seen_torrents
            WHERE tracked_series_id = ?
            """,
            (tracked_series_id,),
        ).fetchall()
    return {
        series_book_key(row["title"] or "", row["author"] or "", series_name)
        for row in rows
    }


def get_owned_books_for_series(series_key: str) -> list[dict]:
    if not series_key:
        return []

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT title, author, narrator, asin, isbn, title_key, title_author_key, series
            FROM library_items
            WHERE series_key = ?
            """,
            (series_key,),
        ).fetchall()
    return [dict(row) for row in rows]


def _matches_owned_book(
    *,
    title: str,
    author: str,
    narrator: str,
    asin: Optional[str],
    isbn: Optional[str],
    series_name: str,
    owned: dict,
) -> bool:
    owned_title = owned.get("title") or ""
    owned_author = owned.get("author") or ""
    owned_narrator = owned.get("narrator") or ""

    if asin and owned.get("asin") and normalize_text(asin) == normalize_text(owned["asin"]):
        return True
    if isbn and owned.get("isbn") and normalize_text(isbn) == normalize_text(owned["isbn"]):
        return True

    if dedup_key(title, author, narrator) == owned.get("title_key"):
        return True

    if title_author_key(title, author) == owned.get("title_author_key"):
        return True

    item_title = normalize_series_title(title, series_name)
    owned_title_norm = normalize_series_title(owned_title, series_name)
    if item_title and owned_title_norm and item_title == owned_title_norm:
        if not author or not owned_author:
            return True
        if normalize_text(author) == normalize_text(owned_author):
            return True
        if title_author_key(title, author) == title_author_key(owned_title, owned_author):
            return True

    return False


def is_book_owned_for_series(
    item: dict,
    series_name: str,
    owned_books: list[dict],
) -> bool:
    title = item.get("title") or ""
    author = item.get("author") or ""
    narrator = item.get("narrator") or ""
    asin = item.get("asin")
    isbn = item.get("isbn")

    ownership = check_ownership(
        title=title,
        author=author,
        narrator=narrator,
        asin=asin,
        isbn=isbn,
    )
    if ownership.owned:
        return True

    for owned in owned_books:
        if _matches_owned_book(
            title=title,
            author=author,
            narrator=narrator,
            asin=asin,
            isbn=isbn,
            series_name=series_name,
            owned=owned,
        ):
            return True

    return False


def find_missing_series_books(
    mam_results: list[dict],
    *,
    series_key: str,
    series_name: str,
) -> list[dict]:
    owned_books = get_owned_books_for_series(series_key)
    missing: list[dict] = []
    seen_titles: set[str] = set()

    for item in mam_results:
        if is_book_owned_for_series(item, series_name, owned_books):
            continue

        identity_key = mam_book_identity_key(item, series_name)
        if identity_key in seen_titles:
            continue
        seen_titles.add(identity_key)
        item["book_identity_key"] = identity_key
        missing.append(item)

    return missing
