import json
from contextlib import asynccontextmanager
from typing import Literal, Optional

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from pydantic import AnyHttpUrl

from mamarr.auth import build_token_verifier
from mamarr.config import settings
from mamarr.covers import find_cover
from mamarr.db import init_db
from mamarr.favorites import (
    add_series_favorite,
    check_series_updates,
    list_series_favorites,
    list_tracked_series,
    remove_series_favorite,
    search_with_format_filter,
    set_series_auto_follow,
)
from mamarr.history import list_history, record_download
from mamarr.inventory.ownership import check_ownership
from mamarr.inventory.sync import get_library_stats, list_owned_books, sync_library_inventory
from mamarr.mam.client import get_mam_stats, get_torrent_details
from mamarr.mam.bonus import (
    MamBonusError,
    buy_upload_credit,
    convert_all_bonus_to_upload_credit,
    get_bonus_points,
)
from mamarr.notifications import send_download_notification
from mamarr.preferences import (
    get_all_preferences,
    get_format_preference,
    get_ownership_filter_mode,
    set_format_preference,
    set_ownership_filter_mode,
)
from mamarr.qbit.client import QBittorrentError, qbit_client
from mamarr.scheduler import start_scheduler, stop_scheduler
from mamarr.watchlist import (
    add_watchlist_entry,
    download_watchlist_entry,
    list_watchlist,
    poll_watchlist,
    remove_watchlist_entry,
    search_openlibrary,
)


def create_mcp_server(*, require_http_auth: bool = False) -> FastMCP:
    auth_settings = None
    token_verifier = None

    if require_http_auth:
        if not settings.mcp_auth_token:
            raise RuntimeError("MCP_AUTH_TOKEN must be set for HTTP transport")
        token_verifier = build_token_verifier(settings.mcp_auth_token)
        server_url = settings.mcp_server_url.rstrip("/")
        auth_settings = AuthSettings(
            issuer_url=AnyHttpUrl(server_url),
            resource_server_url=AnyHttpUrl(server_url),
            required_scopes=["mcp:read", "mcp:write"],
        )

    @asynccontextmanager
    async def lifespan(_app: FastMCP):
        init_db()
        if settings.audiobookshelf_url or settings.qbittorrent_url:
            try:
                sync_library_inventory()
            except Exception:
                pass
        start_scheduler()
        yield
        stop_scheduler()

    mcp = FastMCP(
        name="MAMArr",
        instructions=(
            "MyAnonamouse audiobook search and download service. "
            "Search MAM for audiobooks, sync owned library from Audiobookshelf and qBittorrent, "
            "manage series tracking and OpenLibrary watchlists, "
            "set audio format preferences (m4a/mp3/none), and send torrents to a remote qBittorrent seedbox."
        ),
        host=settings.host,
        port=settings.port,
        lifespan=lifespan,
        auth=auth_settings,
        token_verifier=token_verifier,
    )

    # ── Search & download ───────────────────────────────────────────────────

    @mcp.tool()
    def search_audiobooks(
        query: str,
        field: Literal["title", "author", "series", "narrator"] = "title",
    ) -> str:
        """Search MyAnonamouse for audiobooks. Results respect format and ownership preferences."""
        if not settings.mam_cookie:
            return json.dumps({"error": "MAM_COOKIE is not configured"})
        try:
            results = search_with_format_filter(query, field=field)
            return json.dumps(
                {
                    "query": query,
                    "field": field,
                    "format_preference": get_format_preference(),
                    "ownership_filter": get_ownership_filter_mode(),
                    "count": len(results),
                    "results": results,
                },
                indent=2,
            )
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    @mcp.tool()
    def download_audiobook(
        torrent_id: int,
        title: Optional[str] = None,
        force: bool = False,
    ) -> str:
        """Download an audiobook torrent from MAM and add it to the configured qBittorrent seedbox."""
        try:
            torrent_data = get_torrent_details(torrent_id) or {}
            resolved_title = title or torrent_data.get("title") or torrent_data.get("name") or ""
            author = torrent_data.get("author") or ""
            narrator = torrent_data.get("narrator") or ""
            size = str(torrent_data.get("size") or "")
            filetypes = torrent_data.get("filetypes") or torrent_data.get("filetype") or ""
            cover = find_cover(resolved_title, author)

            if not force:
                ownership = check_ownership(resolved_title, author, narrator)
                if ownership.owned:
                    return json.dumps(
                        {
                            "error": "Already owned in library",
                            "ownership": ownership.to_dict(),
                            "hint": "Pass force=true to download anyway",
                        },
                        indent=2,
                    )
            qbit_client.add_from_mam(torrent_id, filetypes=filetypes)
            record_download(
                str(torrent_id),
                resolved_title,
                author,
                narrator,
                size,
                cover,
                filetypes,
            )
            send_download_notification(resolved_title, torrent_id)
            return json.dumps(
                {
                    "status": "ok",
                    "torrent_id": torrent_id,
                    "title": resolved_title,
                    "author": author,
                    "filetypes": filetypes,
                },
                indent=2,
            )
        except QBittorrentError as exc:
            return json.dumps({"error": str(exc)})
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    @mcp.tool()
    def get_download_history(limit: int = 50) -> str:
        """Return recent audiobook downloads sent to qBittorrent."""
        items = list_history(limit=min(limit, 200))
        return json.dumps({"count": len(items), "items": items}, indent=2)

    @mcp.tool()
    def get_mam_account_stats() -> str:
        """Return MyAnonamouse upload/download ratio and bonus points."""
        stats = get_mam_stats()
        if not stats:
            return json.dumps({"error": "Could not fetch MAM stats — check MAM_COOKIE"})
        return json.dumps(stats, indent=2)

    @mcp.tool()
    def get_mam_bonus_points() -> str:
        """Return current MyAnonamouse bonus points balance."""
        try:
            points = get_bonus_points()
            return json.dumps({"bonus_points": points}, indent=2)
        except MamBonusError as exc:
            return json.dumps({"error": str(exc)})

    @mcp.tool()
    def convert_bonus_points_to_upload_credit() -> str:
        """
        Convert all affordable bonus points into upload credit via the MAM bonus store.
        Uses amount='Max Affordable ' (minimum purchase 50 GiB).
        """
        try:
            result = convert_all_bonus_to_upload_credit()
            # Trim raw API response from tool output
            result.pop("response", None)
            return json.dumps(result, indent=2)
        except MamBonusError as exc:
            return json.dumps({"error": str(exc)})

    @mcp.tool()
    def buy_upload_credit_with_bonus_points(amount_gb: int) -> str:
        """
        Buy a specific amount of upload credit (GiB) with bonus points.
        amount_gb must be an integer >= 50.
        """
        try:
            result = buy_upload_credit(amount_gb)
            result.pop("response", None)
            return json.dumps(result, indent=2)
        except MamBonusError as exc:
            return json.dumps({"error": str(exc)})

    # ── Format preference ─────────────────────────────────────────────────────

    @mcp.tool()
    def set_audio_format_preference(
        preference: Literal["m4a", "mp3", "none"],
    ) -> str:
        """
        Set preferred audio format for search results.
        m4a includes m4b. When set, only the preferred format is returned unless
        only the other format exists for a given title+author+narrator.
        """
        saved = set_format_preference(preference)
        return json.dumps({"audio_format": saved}, indent=2)

    @mcp.tool()
    def get_audio_format_preference() -> str:
        """Get the current audio format and ownership filter preferences."""
        return json.dumps(get_all_preferences(), indent=2)

    @mcp.tool()
    def set_ownership_filter(
        mode: Literal["hide", "mark", "allow"],
    ) -> str:
        """
        Control how owned library items appear in search and series updates.
        hide: exclude owned books (default)
        mark: include but flag already_owned
        allow: no ownership filtering
        """
        saved = set_ownership_filter_mode(mode)
        return json.dumps({"ownership_filter": saved}, indent=2)

    # ── Library inventory ─────────────────────────────────────────────────────

    @mcp.tool()
    def sync_library_inventory_tool() -> str:
        """Sync owned audiobooks from Audiobookshelf and qBittorrent into the local inventory."""
        try:
            result = sync_library_inventory()
            return json.dumps(result, indent=2)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    @mcp.tool()
    def list_owned_books_tool(limit: int = 100, source: Optional[str] = None) -> str:
        """List audiobooks in the synced library inventory (Audiobookshelf + qBittorrent)."""
        items = list_owned_books(limit=min(limit, 500), source=source)
        return json.dumps({"count": len(items), "items": items}, indent=2)

    @mcp.tool()
    def get_library_stats_tool() -> str:
        """Return library inventory statistics and last sync time."""
        return json.dumps(get_library_stats(), indent=2)

    # ── Series tracking ───────────────────────────────────────────────────────

    @mcp.tool()
    def add_series_favorite(series_name: str) -> str:
        """Favorite a book series. New books in the series can be queried via get_series_updates."""
        try:
            result = add_series_favorite(series_name)
            return json.dumps(result, indent=2)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

    @mcp.tool()
    def remove_series_favorite(series_name: str) -> str:
        """Remove a series from favorites."""
        removed = remove_series_favorite(series_name)
        if not removed:
            return json.dumps({"error": "Series not found in favorites"})
        return json.dumps({"status": "removed", "series": series_name}, indent=2)

    @mcp.tool()
    def list_series_favorites_tool() -> str:
        """List all favorited audiobook series."""
        favorites = list_series_favorites()
        return json.dumps({"count": len(favorites), "favorites": favorites}, indent=2)

    @mcp.tool()
    def list_tracked_series_tool() -> str:
        """List all tracked series (manual favorites and series discovered from your library)."""
        series = list_tracked_series()
        return json.dumps({"count": len(series), "series": series}, indent=2)

    @mcp.tool()
    def set_series_auto_follow_tool(series_name: str, auto_follow: bool = True) -> str:
        """Enable or disable automatic MAM polling for a tracked series."""
        updated = set_series_auto_follow(series_name, auto_follow)
        if not updated:
            return json.dumps({"error": "Series not found"})
        return json.dumps({"status": "ok", "series": series_name, "auto_follow": auto_follow}, indent=2)

    @mcp.tool()
    def get_series_updates(series_name: Optional[str] = None) -> str:
        """
        Check tracked series for new MAM audiobooks not seen before.
        Includes manual favorites and series auto-discovered from your library.
        Owned books are excluded per ownership_filter preference.
        """
        try:
            result = check_series_updates(series_name=series_name, mark_seen=True)
            return json.dumps(result, indent=2)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    # ── OpenLibrary watchlist ─────────────────────────────────────────────────

    @mcp.tool()
    def search_openlibrary_books(query: str) -> str:
        """Search OpenLibrary for books to add to the watchlist."""
        try:
            results = search_openlibrary(query)
            return json.dumps({"count": len(results), "results": results}, indent=2)
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    @mcp.tool()
    def list_watchlist_entries() -> str:
        """List OpenLibrary watchlist entries and their MAM match status."""
        items = list_watchlist()
        return json.dumps(
            {
                "count": len(items),
                "found_count": sum(1 for i in items if i.get("mam_found")),
                "items": items,
            },
            indent=2,
        )

    @mcp.tool()
    def add_watchlist_book(
        ol_key: str,
        title: str,
        author: Optional[str] = None,
        ol_cover_url: Optional[str] = None,
        first_publish_year: Optional[str] = None,
        series: Optional[str] = None,
    ) -> str:
        """Add an OpenLibrary book to the watchlist for automatic MAM polling."""
        try:
            result = add_watchlist_entry(
                ol_key=ol_key,
                title=title,
                author=author,
                ol_cover_url=ol_cover_url,
                first_publish_year=first_publish_year,
                series=series,
            )
            return json.dumps(result, indent=2)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})

    @mcp.tool()
    def remove_watchlist_book(entry_id: int) -> str:
        """Remove a book from the OpenLibrary watchlist."""
        removed = remove_watchlist_entry(entry_id)
        if not removed:
            return json.dumps({"error": "Watchlist entry not found"})
        return json.dumps({"status": "removed", "id": entry_id}, indent=2)

    @mcp.tool()
    def poll_watchlist_now(auto_download: bool = True) -> str:
        """Manually poll MAM for watchlist matches. Optionally auto-download to qBittorrent."""
        result = poll_watchlist(auto_download=auto_download)
        return json.dumps(result, indent=2)

    @mcp.tool()
    def download_watchlist_book(entry_id: int) -> str:
        """Download a watchlist entry that has been found on MAM."""
        try:
            result = download_watchlist_entry(entry_id)
            return json.dumps(result, indent=2)
        except ValueError as exc:
            return json.dumps({"error": str(exc)})
        except QBittorrentError as exc:
            return json.dumps({"error": str(exc)})

    # ── Resources ─────────────────────────────────────────────────────────────

    @mcp.resource("mamarr://preferences")
    def preferences_resource() -> str:
        """Current audio format and service preferences."""
        return json.dumps(get_all_preferences(), indent=2)

    @mcp.resource("mamarr://favorites")
    def favorites_resource() -> str:
        """All tracked audiobook series."""
        return json.dumps(list_tracked_series(), indent=2)

    @mcp.resource("mamarr://library")
    def library_resource() -> str:
        """Synced library inventory summary."""
        stats = get_library_stats()
        items = list_owned_books(limit=50)
        return json.dumps({"stats": stats, "sample": items}, indent=2)

    @mcp.resource("mamarr://watchlist")
    def watchlist_resource() -> str:
        """OpenLibrary watchlist entries."""
        return json.dumps(list_watchlist(), indent=2)

    @mcp.resource("mamarr://history")
    def history_resource() -> str:
        """Recent download history."""
        return json.dumps(list_history(limit=100), indent=2)

    @mcp.custom_route("/health", methods=["GET"])
    async def health_check(_request):
        from starlette.responses import JSONResponse

        return JSONResponse({"status": "ok", "service": "MAMArr MCP"})

    return mcp
