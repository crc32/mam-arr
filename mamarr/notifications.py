import requests

from mamarr.config import settings


def send_download_notification(title: str, torrent_id: int | str) -> None:
    if not settings.discord_webhook:
        return
    try:
        content = {
            "username": "MAMArr MCP",
            "embeds": [
                {
                    "title": "Audiobook sent to qBittorrent",
                    "description": f"**{title}**\nTorrent ID: `{torrent_id}`",
                    "color": 0xE91E63,
                }
            ],
        }
        requests.post(settings.discord_webhook, json=content, timeout=5)
    except Exception:
        pass


def send_series_update_notification(series_name: str, new_titles: list[str]) -> None:
    if not settings.discord_webhook or not new_titles:
        return
    try:
        lines = "\n".join(f"• {t}" for t in new_titles[:10])
        extra = f"\n…and {len(new_titles) - 10} more" if len(new_titles) > 10 else ""
        content = {
            "username": "MAMArr MCP",
            "embeds": [
                {
                    "title": f"New books in series: {series_name}",
                    "description": lines + extra,
                    "color": 0x10B981,
                }
            ],
        }
        requests.post(settings.discord_webhook, json=content, timeout=5)
    except Exception:
        pass


def send_watchlist_notification(title: str, author: str, mam_tid: str, auto_downloaded: bool) -> None:
    if not settings.discord_webhook:
        return
    try:
        if auto_downloaded:
            embed_title = "Watchlist book auto-downloaded"
            description = f"**{title}**" + (f" by {author}" if author else "") + "\n\nSent to qBittorrent."
            color = 0x10B981
        else:
            embed_title = "Watchlist match found"
            description = f"**{title}**" + (f" by {author}" if author else "") + "\n\nFound on MAM."
            color = 0xF59E0B

        content = {
            "username": "MAMArr MCP",
            "embeds": [
                {
                    "title": embed_title,
                    "description": description,
                    "color": color,
                    "footer": {"text": f"MAM torrent ID: {mam_tid}"},
                }
            ],
        }
        requests.post(settings.discord_webhook, json=content, timeout=5)
    except Exception:
        pass
