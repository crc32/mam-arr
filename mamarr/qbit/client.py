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

    def add_from_mam(self, tid: int, filetypes: str = "") -> None:
        from mamarr.mam.client import download_torrent_file

        torrent_bytes = download_torrent_file(tid)
        self.add_torrent(torrent_bytes, tid, filetypes=filetypes)


qbit_client = QBittorrentClient()
