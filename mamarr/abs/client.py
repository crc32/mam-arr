from typing import Any, Optional

import requests

from mamarr.config import settings


class AudiobookshelfError(Exception):
    pass


class AudiobookshelfClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        library_id: str | None = None,
    ):
        self.base_url = (base_url or settings.audiobookshelf_url).rstrip("/")
        self.token = token or settings.audiobookshelf_token
        self.library_id = library_id or settings.audiobookshelf_library_id

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _ensure_configured(self) -> None:
        if not self.base_url or not self.token:
            raise AudiobookshelfError("AUDIOBOOKSHELF_URL and AUDIOBOOKSHELF_TOKEN are required")

    def _get(self, path: str, params: dict | None = None) -> Any:
        self._ensure_configured()
        response = requests.get(
            f"{self.base_url}{path}",
            headers=self._headers(),
            params=params or {},
            timeout=60,
        )
        if not response.ok:
            raise AudiobookshelfError(f"Audiobookshelf request failed: HTTP {response.status_code}")
        return response.json()

    def list_libraries(self) -> list[dict]:
        data = self._get("/api/libraries")
        if isinstance(data, list):
            return data
        return data.get("libraries", [])

    def resolve_library_id(self) -> str:
        if self.library_id:
            return self.library_id
        libraries = self.list_libraries()
        for lib in libraries:
            if lib.get("mediaType") == "book":
                return lib["id"]
        if libraries:
            return libraries[0]["id"]
        raise AudiobookshelfError("No Audiobookshelf libraries found")

    def iter_library_items(self, library_id: str | None = None) -> list[dict]:
        lib_id = library_id or self.resolve_library_id()
        page = 0
        limit = 100
        all_items: list[dict] = []

        while True:
            data = self._get(
                f"/api/libraries/{lib_id}/items",
                params={
                    "limit": limit,
                    "page": page,
                    "minified": 0,
                    "collapseseries": 0,
                    "sort": "media.metadata.title",
                },
            )
            results = data.get("results", [])
            all_items.extend(results)
            total = data.get("total", len(results))
            if len(all_items) >= total or not results:
                break
            page += 1

        return all_items

    def iter_library_series(self, library_id: str | None = None) -> list[dict]:
        lib_id = library_id or self.resolve_library_id()
        page = 0
        limit = 100
        all_series: list[dict] = []

        while True:
            data = self._get(
                f"/api/libraries/{lib_id}/series",
                params={"limit": limit, "page": page},
            )
            results = data.get("results", [])
            all_series.extend(results)
            total = data.get("total", len(results))
            if len(all_series) >= total or not results:
                break
            page += 1

        return all_series

    @staticmethod
    def _series_entries(metadata: dict) -> list[dict]:
        raw = metadata.get("series")
        if isinstance(raw, dict):
            return [raw]
        if isinstance(raw, list):
            return [entry for entry in raw if isinstance(entry, dict)]
        return []

    @staticmethod
    def parse_series(raw: dict) -> Optional[dict]:
        name = (raw.get("name") or "").strip()
        series_id = str(raw.get("id") or "").strip()
        if not name or not series_id:
            return None

        books = raw.get("books") or []
        book_ids = [str(book.get("id")) for book in books if book.get("id")]
        return {
            "abs_series_id": series_id,
            "name": name,
            "book_ids": book_ids,
            "num_books": len(book_ids),
        }

    @staticmethod
    def parse_item(raw: dict) -> Optional[dict]:
        media = raw.get("media") or {}
        metadata = media.get("metadata") or {}
        title = (metadata.get("title") or "").strip()
        if not title:
            return None

        author = metadata.get("authorName") or ""
        if not author and metadata.get("authors"):
            names = [a.get("name", "") for a in metadata["authors"] if a.get("name")]
            author = names[0] if names else ""

        narrator = metadata.get("narratorName") or ""
        if not narrator and metadata.get("narrators"):
            narrator = metadata["narrators"][0] if metadata["narrators"] else ""

        series = metadata.get("seriesName") or ""
        sequence: Optional[float] = None
        abs_series_id: Optional[str] = None
        series_entries = AudiobookshelfClient._series_entries(metadata)
        if series_entries:
            first = series_entries[0]
            series = series or first.get("name") or ""
            abs_series_id = str(first.get("id") or "").strip() or None
            seq_raw = first.get("sequence")
            if seq_raw is not None:
                try:
                    sequence = float(seq_raw)
                except (TypeError, ValueError):
                    pass

        return {
            "external_id": str(raw.get("id") or ""),
            "title": title,
            "author": author or "",
            "narrator": narrator or "",
            "series": series or "",
            "series_sequence": sequence,
            "abs_series_id": abs_series_id,
            "asin": (metadata.get("asin") or "").strip() or None,
            "isbn": (metadata.get("isbn") or "").strip() or None,
        }


abs_client = AudiobookshelfClient()
