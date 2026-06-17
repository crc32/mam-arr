from typing import Optional

import requests

from mamarr.config import settings


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
    ):
        self.base_url = (base_url or settings.qbittorrent_url).rstrip("/")
        self.username = username or settings.qbittorrent_user
        self.password = password or settings.qbittorrent_pass
        self.savepath = savepath or settings.qbittorrent_savepath
        self._cookies: requests.cookies.RequestsCookieJar | None = None

    def _ensure_configured(self) -> None:
        if not self.base_url:
            raise QBittorrentError("QBITTORRENT_URL is not configured")
        if not self.username or not self.password:
            raise QBittorrentError("QBITTORRENT_USER and QBITTORRENT_PASS are required")

    def login(self) -> requests.cookies.RequestsCookieJar:
        self._ensure_configured()
        response = requests.post(
            f"{self.base_url}/api/v2/auth/login",
            data={"username": self.username, "password": self.password},
            timeout=15,
        )
        if not response.ok:
            raise QBittorrentError(f"qBittorrent login failed: HTTP {response.status_code}")
        self._cookies = response.cookies
        return self._cookies

    def _cookies_or_login(self) -> requests.cookies.RequestsCookieJar:
        if self._cookies is None:
            return self.login()
        return self._cookies

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
        cookies = self._cookies_or_login()
        response = requests.post(
            f"{self.base_url}/api/v2/torrents/add",
            files={"torrents": (f"{tid}.torrent", torrent_bytes)},
            data={
                "savepath": self.savepath,
                "autoTMM": "false",
                "category": category,
                "tags": self.build_tags(filetypes),
            },
            cookies=cookies,
            timeout=30,
        )
        if not response.ok:
            raise QBittorrentError(f"qBittorrent add failed: HTTP {response.status_code}")

    def add_from_mam(self, tid: int, filetypes: str = "", use_freeleech_wedge: bool = False) -> None:
        from mamarr.mam.client import download_torrent_file

        torrent_bytes = download_torrent_file(tid, use_freeleech_wedge=use_freeleech_wedge)
        self.add_torrent(torrent_bytes, tid, filetypes=filetypes)

    def list_torrents(self, category: str | None = None, tag: str | None = None) -> list[dict]:
        cookies = self._cookies_or_login()
        params: dict[str, str] = {}
        if category:
            params["category"] = category
        if tag:
            params["tag"] = tag
        response = requests.get(
            f"{self.base_url}/api/v2/torrents/info",
            params=params,
            cookies=cookies,
            timeout=30,
        )
        if not response.ok:
            raise QBittorrentError(f"qBittorrent list failed: HTTP {response.status_code}")
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
