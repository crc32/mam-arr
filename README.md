# MAMArr MCP

MyAnonamouse audiobook search and download service exposed as a **Model Context Protocol (MCP)** server. Use it with Hermes, OpenClaw, Claude Desktop, Claude Code, and other MCP-aware clients.

Search MAM for audiobooks, sync your **Audiobookshelf + qBittorrent library** to avoid duplicates, auto-track **series from owned books**, maintain an **OpenLibrary watchlist**, set **audio format preferences** (M4A/M4B, MP3, or none), and send torrents to a **remote qBittorrent seedbox**.

No web UI. No Docker required.

---

## Features

- **MCP tools** for search, download, library sync, series tracking, watchlist, and preferences
- **Library inventory** — sync owned books from Audiobookshelf + qBittorrent pipeline
- **Duplicate prevention** — owned books hidden from search/updates; download blocked unless `force=true`
- **Remote qBittorrent** — works with seedboxes over HTTPS
- **Series tracking** — manual favorites plus auto-discovery from your library
- **Format preference** — prefer M4A/M4B or MP3; falls back when only the other format exists
- **OpenLibrary watchlist** — watch for books not yet on MAM, with background polling
- **HTTP bearer auth** for network deployments
- **Direct HTTPS** via TLS cert/key or reverse-proxy termination

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/crc32/mam-arr.git
cd mam-arr
uv sync
cp env.example .env   # edit with your credentials
```

Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

### 2. Configure

Copy `env.example` to `.env` and fill in your credentials:

```bash
cp env.example .env
```

Required for search/download:

| Variable | Description |
|----------|-------------|
| `MAM_COOKIE` | Your MAM `mam_id` session cookie |
| `QBITTORRENT_URL` | qBittorrent Web UI URL (e.g. `https://seedbox.example.com/qbittorrent`) |
| `QBITTORRENT_USER` | qBittorrent username |
| `QBITTORRENT_PASS` | qBittorrent password |
| `QBITTORRENT_SAVEPATH` | Save path on the seedbox |

Optional for library inventory (recommended):

| Variable | Description |
|----------|-------------|
| `AUDIOBOOKSHELF_URL` | Audiobookshelf server URL |
| `AUDIOBOOKSHELF_TOKEN` | API token from ABS Settings → Users |
| `AUDIOBOOKSHELF_LIBRARY_ID` | Optional; auto-detects first book library |
| `QBITTORRENT_INVENTORY_CATEGORY` | qBit category for owned torrents (default: `mamarr`) |
| `QBITTORRENT_INVENTORY_TAG` | qBit tag fallback for owned torrents (default: `audiobooks`) |
| `LIBRARY_SYNC_HOURS` | How often to refresh inventory (default: 12) |

Required for HTTP transport:

| Variable | Description |
|----------|-------------|
| `MCP_AUTH_TOKEN` | Bearer token clients must send |
| `MCP_SERVER_URL` | Public URL of this server (e.g. `https://mamarr.example.com`) |

### 3. Run

**Local MCP client (stdio):**

```bash
uv run python -m mamarr --transport stdio
```

**Network MCP (Streamable HTTP):**

```bash
uv run python -m mamarr --transport streamable-http --host 0.0.0.0 --port 8000
```

**Direct HTTPS:**

```bash
uv run python -m mamarr --transport streamable-http \
  --host 0.0.0.0 --port 8443 \
  --ssl-cert /path/to/fullchain.pem \
  --ssl-key /path/to/privkey.pem
```

Or set `SSL_CERT_FILE` and `SSL_KEY_FILE` in `.env`.

Health check: `GET /health` → `{"status":"ok"}`

MCP endpoint: `POST /mcp` with header `Authorization: Bearer <MCP_AUTH_TOKEN>`

---

## systemd user service (recommended for servers)

Run MAMArr as a persistent user-level service with uv:

```bash
./scripts/install-systemd-user-service.sh
systemctl --user enable --now mamarr-mcp.service
```

The installer writes `~/.config/systemd/user/mamarr-mcp.service`, runs `uv sync`, and substitutes your repo path and `uv` binary.

**Useful commands:**

```bash
systemctl --user status mamarr-mcp.service
journalctl --user -u mamarr-mcp.service -f
systemctl --user restart mamarr-mcp.service
```

**Run at boot without a login session:**

```bash
loginctl enable-linger "$USER"
```

The service reads `.env` from the repo root (`EnvironmentFile`) and starts with `--transport streamable-http`. Set `HOST`, `PORT`, `MCP_AUTH_TOKEN`, and optional `SSL_CERT_FILE` / `SSL_KEY_FILE` in `.env`.

---

## MCP Client Configuration

### Claude Desktop / local stdio

```json
{
  "mcpServers": {
    "mamarr": {
      "command": "python",
      "args": ["-m", "mamarr", "--transport", "stdio"],
      "env": {
        "MAM_COOKIE": "your_cookie",
        "QBITTORRENT_URL": "https://your-seedbox/qbittorrent",
        "QBITTORRENT_USER": "admin",
        "QBITTORRENT_PASS": "password",
        "QBITTORRENT_SAVEPATH": "/audiobooks"
      }
    }
  }
}
```

### Remote HTTP (Hermes, OpenClaw, etc.)

Configure your client to connect to:

```
https://your-host.example.com/mcp
```

With authentication:

```
Authorization: Bearer <MCP_AUTH_TOKEN>
```

---

## MCP Tools

| Tool | Description |
|------|-------------|
| `search_audiobooks` | Search MAM; applies format + ownership filters |
| `download_audiobook` | Send a torrent to qBittorrent (`force=true` to override ownership) |
| `get_download_history` | List recent downloads |
| `get_mam_account_stats` | MAM upload/download ratio |
| `sync_library_inventory_tool` | Refresh owned books from ABS + qBittorrent |
| `list_owned_books_tool` | List synced library inventory |
| `get_library_stats_tool` | Inventory counts and last sync time |
| `set_audio_format_preference` | Set `m4a`, `mp3`, or `none` |
| `set_ownership_filter` | Set `hide`, `mark`, or `allow` for owned books in results |
| `get_audio_format_preference` | Read current preferences |
| `add_series_favorite` | Manually favorite a series |
| `remove_series_favorite` | Remove manual follow (library series become auto_follow=0) |
| `list_series_favorites_tool` | List manual favorites |
| `list_tracked_series_tool` | List all tracked series (manual + library-derived) |
| `set_series_auto_follow_tool` | Enable/disable MAM polling for a series |
| `get_series_updates` | Find new unowned books in tracked series |
| `search_openlibrary_books` | Browse OpenLibrary to add to watchlist |
| `list_watchlist_entries` | List watchlist with MAM match status |
| `add_watchlist_book` | Add an OpenLibrary book to watchlist |
| `remove_watchlist_book` | Remove a watchlist entry |
| `poll_watchlist_now` | Manually poll MAM for watchlist matches |
| `download_watchlist_book` | Download a found watchlist entry |

## MCP Resources

| URI | Content |
|-----|---------|
| `mamarr://preferences` | Format and ownership preferences |
| `mamarr://library` | Library inventory stats + sample |
| `mamarr://favorites` | Tracked series list |
| `mamarr://watchlist` | OpenLibrary watchlist |
| `mamarr://history` | Download history |

---

## Format Preference

When preference is `m4a` or `mp3`:

1. Results are grouped by **title + author + narrator** (separates re-recordings and same-title collisions).
2. If the preferred format exists, only that version is returned.
3. If only the non-preferred format exists, that version is returned as fallback.

`m4b` is treated as `m4a`.

Set via tool or it persists in SQLite:

```
set_audio_format_preference(preference="m4a")
```

---

## Library Inventory

MAMArr syncs owned audiobooks from two sources:

1. **Audiobookshelf** — canonical metadata (title, author, narrator, series, ASIN)
2. **qBittorrent** — pipeline inventory (torrents in `mamarr` category or `audiobooks` tag)

After sync, series found in your library are auto-tracked for new MAM releases.

**Ownership matching** (in order): ASIN → ISBN → title+author+narrator → title+author

**Default behavior:** owned books are hidden from search and series updates. Downloads are blocked unless `force=true`.

```
sync_library_inventory_tool()
list_owned_books_tool(limit=50)
set_ownership_filter(mode="hide")   # hide | mark | allow
```

Background sync runs every `LIBRARY_SYNC_HOURS` (default 12).

---

## Series Tracking

Manual favorites plus series auto-discovered from your library:

```
add_series_favorite(series_name="The Expanse")
list_tracked_series_tool()
get_series_updates()
set_series_auto_follow_tool(series_name="The Expanse", auto_follow=true)
```

Background polling runs every `SERIES_FAVORITES_POLL_HOURS` (default 6).

---

## Project Layout

```
mamarr/
├── __main__.py          # CLI entry point
├── server.py            # FastMCP tools and resources
├── config.py            # Environment settings
├── db.py                # SQLite schema
├── mam/client.py        # MAM API
├── abs/client.py        # Audiobookshelf API
├── inventory/           # Library sync + ownership matching
├── qbit/client.py       # qBittorrent API (remote seedbox)
├── favorites.py         # Series tracking
├── watchlist.py         # OpenLibrary watchlist
├── format_filter.py     # M4A/MP3 preference logic
├── covers.py            # Cover art lookup
├── history.py           # Download history
├── preferences.py       # Saved preferences
├── scheduler.py         # Background polling
└── auth.py              # Bearer token verification
```

---

## Legacy Web App

The previous React + Docker web interface remains in `frontend/` and `backend/` for reference but is no longer the primary interface. Use the MCP service instead.

---

## License

MIT
