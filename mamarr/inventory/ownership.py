from dataclasses import dataclass
from typing import Literal, Optional

from mamarr.db import get_db
from mamarr.format_filter import dedup_key, normalize_text

OwnershipMatchType = Literal["asin", "isbn", "title_author_narrator", "title_author", "none"]
OwnershipFilterMode = Literal["hide", "mark", "allow"]


@dataclass
class OwnershipResult:
    owned: bool
    match_type: OwnershipMatchType = "none"
    source: Optional[str] = None
    confidence: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "already_owned": self.owned,
            "ownership_match": self.match_type if self.owned else None,
            "ownership_source": self.source if self.owned else None,
            "ownership_confidence": self.confidence if self.owned else None,
        }


def title_author_key(title: str, author: str) -> str:
    return "|".join(normalize_text(part) for part in (title, author))


def check_ownership(
    title: str,
    author: str = "",
    narrator: str = "",
    asin: str | None = None,
    isbn: str | None = None,
) -> OwnershipResult:
    asin_norm = (asin or "").strip().upper()
    isbn_norm = (isbn or "").strip().replace("-", "")

    with get_db() as conn:
        if asin_norm:
            row = conn.execute(
                """
                SELECT source, confidence FROM library_items
                WHERE asin IS NOT NULL AND UPPER(asin) = ?
                LIMIT 1
                """,
                (asin_norm,),
            ).fetchone()
            if row:
                return OwnershipResult(True, "asin", row["source"], row["confidence"])

        if isbn_norm:
            row = conn.execute(
                """
                SELECT source, confidence FROM library_items
                WHERE isbn IS NOT NULL AND REPLACE(isbn, '-', '') = ?
                LIMIT 1
                """,
                (isbn_norm,),
            ).fetchone()
            if row:
                return OwnershipResult(True, "isbn", row["source"], row["confidence"])

        full_key = dedup_key(title, author, narrator)
        row = conn.execute(
            """
            SELECT source, confidence FROM library_items
            WHERE title_key = ?
            ORDER BY CASE confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END
            LIMIT 1
            """,
            (full_key,),
            ).fetchone()
        if row:
            return OwnershipResult(True, "title_author_narrator", row["source"], row["confidence"])

        partial = title_author_key(title, author)
        row = conn.execute(
            """
            SELECT source, confidence FROM library_items
            WHERE title_author_key = ?
            ORDER BY CASE confidence WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END
            LIMIT 1
            """,
            (partial,),
        ).fetchone()
        if row:
            return OwnershipResult(True, "title_author", row["source"], row["confidence"])

    return OwnershipResult(False)


def apply_ownership_to_result(item: dict) -> dict:
    ownership = check_ownership(
        title=item.get("title") or "",
        author=item.get("author") or "",
        narrator=item.get("narrator") or "",
        asin=item.get("asin"),
        isbn=item.get("isbn"),
    )
    item.update(ownership.to_dict())
    return item


def filter_results_by_ownership(results: list[dict], mode: OwnershipFilterMode) -> list[dict]:
    if mode == "allow":
        return [apply_ownership_to_result(dict(r)) for r in results]

    annotated = [apply_ownership_to_result(dict(r)) for r in results]
    if mode == "mark":
        return annotated
    return [r for r in annotated if not r.get("already_owned")]
