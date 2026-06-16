import os
from pathlib import Path

from dotenv import load_dotenv

_here = Path(__file__).resolve().parent
_root = _here.parent
ENV_PATH = _root / ".env"
if ENV_PATH.is_file():
    load_dotenv(ENV_PATH, override=True)
else:
    load_dotenv(override=True)


def normalise_mam_cookie(raw: str) -> str:
    if not raw:
        return ""
    raw = raw.strip()
    for prefix in ("mam_id=", "mam_id =", "MAM_ID=", "MAM_ID ="):
        if raw.startswith(prefix):
            return raw[len(prefix) :]
    return raw


class Settings:
    mam_cookie: str = normalise_mam_cookie(os.getenv("MAM_COOKIE", "") or "")
    mam_base: str = os.getenv("MAM_BASE", "https://www.myanonamouse.net")

    qbittorrent_url: str = (os.getenv("QBITTORRENT_URL") or "").rstrip("/")
    qbittorrent_user: str = os.getenv("QBITTORRENT_USER", "")
    qbittorrent_pass: str = os.getenv("QBITTORRENT_PASS", "")
    qbittorrent_savepath: str = os.getenv("QBITTORRENT_SAVEPATH", "/media/audiobooks")

    mcp_auth_token: str = os.getenv("MCP_AUTH_TOKEN", "")
    mcp_server_url: str = os.getenv("MCP_SERVER_URL", "http://localhost:8000")

    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))
    ssl_cert_file: str | None = os.getenv("SSL_CERT_FILE") or None
    ssl_key_file: str | None = os.getenv("SSL_KEY_FILE") or None

    db_path: str = os.getenv("DB_PATH", str(_root / "data" / "app.db"))

    watchlist_poll_hours: int = int(os.getenv("WATCHLIST_POLL_HOURS", "6"))
    series_favorites_poll_hours: int = int(os.getenv("SERIES_FAVORITES_POLL_HOURS", "6"))

    discord_webhook: str = (os.getenv("DISCORD_WEBHOOK") or "").strip()


settings = Settings()
