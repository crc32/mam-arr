import time
from typing import Any, Optional

import requests

from mamarr.config import settings

SESSION_MAX_AGE_SECONDS = 3600


class QBittorrentError(Exception):
    pass


class QBittorrentClient:
    """Remote qBittorrent Web API client (seedbox-compatible)."""

    def __init__(
        self,
        base_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        savepath: str | None = None,
        session_max_age_seconds: int = SESSION_MAX_AGE_SECONDS,
    ):
        self.base_url = (base_url or settings.qbittorrent_url).rstrip("/")
        self.username = username or settings.qbittorrent_user
        self.password = password or settings.qbittorrent_pass
        self.savepath = savepath or settings.qbittorrent_savepath
        self.session_max_age_seconds = session_max_age_seconds
        self._cookies: requests.cookies.RequestsCookieJar | None = None
        self._logged_in_at: float | None = None

    def _ensure_configured(self) -> None:
        if not self.base_url:
            raise QBittorrentError("QBITTORRENT_URL is not configured")
        if not self.username or not self.password:
            raise QBittorrentError("QBITTORRENT_USER and QBITTORRENT_PASS are required")

    def _api_headers(self) -> dict[str, str]:
        return {"Referer": f"{self.base_url}/"}

    def _session_expired(self) -> bool:
        if self._cookies is None or self._logged_in_at is None:
            return True
        return (time.monotonic() - self._logged_in_at) >= self.session_max_age_seconds

    def _clear_session(self) -> None:
        self._cookies = None
        self._logged_in_at = None

    def login(self, *, force: bool = False) -> requests.cookies.RequestsCookieJar:
        if not force and not self._session_expired() and self._cookies is not None:
            return self._cookies

        self._ensure_configured()
        response = requests.post(
            f"{self.base_url}/api/v2/auth/login",
            data={"username": self.username, "password": self.password},
            headers=self._api_headers(),
            timeout=15,
        )
        if not response.ok:
            self._clear_session()
            raise QBittorrentError(f"qBittorrent login failed: HTTP {response.status_code}")

        self._cookies = response.cookies
        self._logged_in_at = time.monotonic()
        return self._cookies

    def _cookies_or_login(self) -> requests.cookies.RequestsCookieJar:
        if self._session_expired():
            return self.login(force=True)
        assert self._cookies is not None
        return self._cookies

    def _request(
        self,
        method: str,
        path: str,
        *,
        retry_auth: bool = True,
        error_prefix: str,
        timeout: float = 30,
        **kwargs: Any,
    ) -> requests.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Referer", f"{self.base_url}/")

        def do_request(cookies: requests.cookies.RequestsCookieJar) -> requests.Response:
            return requests.request(
                method,
                f"{self.base_url}{path}",
                cookies=cookies,
                headers=headers,
                timeout=timeout,
                **kwargs,
            )

        response = do_request(self._cookies_or_login())
        if response.status_code == 403 and retry_auth:
            response = do_request(self.login(force=True))

        if not response.ok:
            raise QBittorrentError(f"{error_prefix}: HTTP {response.status_code}")
        return response

    @staticmethod
    def build_tags(filetypes: str) -> str:
        tags = ["audiobooks", "MaM Do Not Delete"]
        if filetypes:
            raw = [t.strip().lower() for t in filetypes.split(",") if t.strip()]
            tags.extend(t for t in raw if t != "m4b")
        return ",".join(tags)

    def add_torrent(
        self,
        torrent_bytes: bytes,
        tid: int,
        filetypes: str = "",
        category: str = "mamarr",
    ) -> None:
        self._request(
            "POST",
            "/api/v2/torrents/add",
            error_prefix="qBittorrent add failed",
            files={"torrents": (f"{tid}.torrent", torrent_bytes)},
            data={
                "savepath": self.savepath,
                "autoTMM": "false",
                "category": category,
                "tags": self.build_tags(filetypes),
            },
        )

    def add_from_mam(self, tid: int, filetypes: str = "", use_freeleech_wedge: bool = False) -> None:
        from mamarr.mam.client import download_torrent_file

        torrent_bytes = download_torrent_file(tid, use_freeleech_wedge=use_freeleech_wedge)
        self.add_torrent(torrent_bytes, tid, filetypes=filetypes)

    def list_torrents(self, category: str | None = None, tag: str | None = None) -> list[dict]:
        params: dict[str, str] = {}
        if category:
            params["category"] = category
        if tag:
            params["tag"] = tag
        response = self._request(
            "GET",
            "/api/v2/torrents/info",
            error_prefix="qBittorrent list failed",
            params=params,
        )
        return response.json()

    def list_inventory_torrents(self) -> list[dict]:
        """Return audiobook torrents in qBittorrent (pipeline inventory)."""
        category = settings.qbittorrent_inventory_category
        tag = settings.qbittorrent_inventory_tag
        try:
            if category:
                torrents = self.list_torrents(category=category)
                if torrents:
                    return torrents
        except QBittorrentError:
            pass

        all_torrents = self.list_torrents()
        filtered = []
        for tor in all_torrents:
            tags = (tor.get("tags") or "").lower()
            cat = (tor.get("category") or "").lower()
            if tag and tag.lower() in tags:
                filtered.append(tor)
            elif category and cat == category.lower():
                filtered.append(tor)
        return filtered


qbit_client = QBittorrentClient()
