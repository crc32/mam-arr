from typing import Optional

import requests

from mamarr.db import get_db, utc_now


def cache_get_cover(title: str, author: str) -> Optional[str]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT cover_url FROM covers WHERE title = ? AND IFNULL(author,'') = ?",
            (title, author or ""),
        ).fetchone()
    if row and row["cover_url"]:
        url = row["cover_url"]
        return url.replace("http://", "https://") if url.startswith("http://") else url
    return None


def cache_set_cover(title: str, author: str, cover_url: Optional[str]) -> None:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO covers (title, author, cover_url, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(title, author) DO UPDATE SET
                cover_url = excluded.cover_url,
                updated_at = excluded.updated_at
            """,
            (title, author or "", cover_url, utc_now()),
        )
        conn.commit()


def find_cover(title: str, author: str) -> Optional[str]:
    title = (title or "").strip()
    author = (author or "").strip()
    if not title:
        return None

    cached = cache_get_cover(title, author)
    if cached:
        return cached

    query = f"{title} {author} audiobook".strip()

    try:
        response = requests.get(
            "https://itunes.apple.com/search",
            params={"term": query, "media": "audiobook", "limit": 1},
            timeout=5,
        )
        if response.ok:
            data = response.json()
            if data.get("resultCount"):
                art = data["results"][0].get("artworkUrl100") or data["results"][0].get("artworkUrl60")
                if art:
                    cover_url = art.replace("100x100", "600x600").replace("60x60", "600x600")
                    if cover_url.startswith("http://"):
                        cover_url = "https://" + cover_url[len("http://") :]
                    cache_set_cover(title, author, cover_url)
                    return cover_url
    except Exception:
        pass

    try:
        response = requests.get(
            "https://www.googleapis.com/books/v1/volumes",
            params={"q": query, "maxResults": 1},
            timeout=5,
        )
        if response.ok:
            data = response.json()
            if data.get("items"):
                links = data["items"][0]["volumeInfo"].get("imageLinks", {})
                cover_url = links.get("thumbnail") or links.get("smallThumbnail")
                if cover_url:
                    if cover_url.startswith("http://"):
                        cover_url = "https://" + cover_url[len("http://") :]
                    cache_set_cover(title, author, cover_url)
                    return cover_url
    except Exception:
        pass

    try:
        response = requests.get(
            "https://openlibrary.org/search.json",
            params={"title": title},
            timeout=5,
        )
        if response.ok:
            docs = response.json().get("docs", [])
            if docs and docs[0].get("cover_i"):
                cover_url = f"https://covers.openlibrary.org/b/id/{docs[0]['cover_i']}-L.jpg"
                cache_set_cover(title, author, cover_url)
                return cover_url
    except Exception:
        pass

    cache_set_cover(title, author, None)
    return None
