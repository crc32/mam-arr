# MAMArr MCP

MyAnonamouse audiobook search and download service exposed as a **Model Context Protocol (MCP)** server. Use it with Hermes, OpenClaw, Claude Desktop, Claude Code, and other MCP-aware clients.

Search MAM for audiobooks, manage **series favorites** (get notified about new books in a series), maintain an **OpenLibrary watchlist**, set **audio format preferences** (M4A/M4B, MP3, or none), and send torrents to a **remote qBittorrent seedbox**.

No web UI. No Docker required.

---

## Features

- **MCP tools** for search, download, favorites, watchlist, and preferences
- **Remote qBittorrent** — works with seedboxes over HTTPS
- **Series favorites** — track new audiobooks appearing in a series on MAM
- **Format preference** — prefer M4A/M4B or MP3; falls back when only the other format exists
- **OpenLibrary watchlist** — watch for books not yet on MAM, with background polling
- **HTTP bearer auth** for network deployments
- **Direct HTTPS** via TLS cert/key or reverse-proxy termination

---

## Quick Start

### 1. Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

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

Required for HTTP transport:

| Variable | Description |
|----------|-------------|
| `MCP_AUTH_TOKEN` | Bearer token clients must send |
| `MCP_SERVER_URL` | Public URL of this server (e.g. `https://mamarr.example.com`) |

### 3. Run

**Local MCP client (stdio):**

```bash
python -m mamarr --transport stdio
```

**Network MCP (Streamable HTTP):**

```bash
python -m mamarr --transport streamable-http --host 0.0.0.0 --port 8000
```

**Direct HTTPS:**

```bash
python -m mamarr --transport streamable-http \
  --host 0.0.0.0 --port 8443 \
  --ssl-cert /path/to/fullchain.pem \
  --ssl-key /path/to/privkey.pem
```

Or set `SSL_CERT_FILE` and `SSL_KEY_FILE` in `.env`.

Health check: `GET /health` → `{"status":"ok"}`

MCP endpoint: `POST /mcp` with header `Authorization: Bearer <MCP_AUTH_TOKEN>`

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
| `search_audiobooks` | Search MAM by title, author, series, or narrator |
| `download_audiobook` | Send a torrent to qBittorrent |
| `get_download_history` | List recent downloads |
| `get_mam_account_stats` | MAM upload/download ratio |
| `set_audio_format_preference` | Set `m4a`, `mp3`, or `none` |
| `get_audio_format_preference` | Read current format preference |
| `add_series_favorite` | Favorite a series for new-book tracking |
| `remove_series_favorite` | Remove a series favorite |
| `list_series_favorites_tool` | List all favorited series |
| `get_series_updates` | Find new books in favorited series |
| `search_openlibrary_books` | Browse OpenLibrary to add to watchlist |
| `list_watchlist_entries` | List watchlist with MAM match status |
| `add_watchlist_book` | Add an OpenLibrary book to watchlist |
| `remove_watchlist_book` | Remove a watchlist entry |
| `poll_watchlist_now` | Manually poll MAM for watchlist matches |
| `download_watchlist_book` | Download a found watchlist entry |

## MCP Resources

| URI | Content |
|-----|---------|
| `mamarr://preferences` | Audio format preference |
| `mamarr://favorites` | Series favorites list |
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

## Series Favorites

Favorite a series, then call `get_series_updates` to find new MAM torrents not seen before:

```
add_series_favorite(series_name="The Expanse")
get_series_updates()
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
├── qbit/client.py       # qBittorrent API (remote seedbox)
├── favorites.py         # Series favorites
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
