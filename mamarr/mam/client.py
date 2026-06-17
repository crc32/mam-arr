from typing import Optional

import requests

from mamarr.config import settings, normalise_mam_cookie


def mam_headers(referer: str | None = None) -> dict[str, str]:
    base = settings.mam_base or "https://www.myanonamouse.net"
    return {
        "Cookie": f"mam_id={normalise_mam_cookie(settings.mam_cookie)}" if settings.mam_cookie else "",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, */*",
        "Accept-Language": "en-GB,en;q=0.9",
        "Referer": referer or f"{base}/",
        "Origin": base,
    }


def _parse_mam_response(raw_bytes: bytes) -> list[dict]:
    import gzip
    import json

    try:
        parsed = json.loads(raw_bytes)
    except Exception:
        parsed = json.loads(gzip.decompress(raw_bytes))

    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        return (
            parsed.get("data")
            or parsed.get("torrents")
            or parsed.get("results")
            or []
        )
    return []


def search_mam(
    query: str,
    field: str = "title",
    perpage: int = 25,
) -> list[dict]:
    if field not in {"title", "author", "series", "narrator"}:
        field = "title"

    payload = {
        "tor": {
            "text": query,
            "srchIn": [field],
            "searchType": "all",
            "searchIn": "torrents",
            "main_cat": ["13"],
            "browse_lang": ["1"],
            "perpage": perpage,
        },
        "thumbnail": "true",
        "description": "true",
    }
    headers = {
        **mam_headers(),
        "Content-Type": "application/json",
    }
    response = requests.post(
        f"{settings.mam_base}/tor/js/loadSearchJSONbasic.php",
        json=payload,
        headers=headers,
        timeout=20,
    )
    response.raise_for_status()
    return _parse_mam_response(response.content)


def get_torrent_details(tid: int) -> Optional[dict]:
    payload = {
        "tor": {
            "searchType": "all",
            "searchIn": "torrents",
            "tid": str(tid),
            "main_cat": ["13"],
            "startNumber": "0",
            "perpage": 1,
        },
        "thumbnail": "true",
        "description": "true",
    }
    headers = {
        **mam_headers(),
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(
            f"{settings.mam_base}/tor/js/loadSearchJSONbasic.php",
            json=payload,
            headers=headers,
            timeout=15,
        )
        data = _parse_mam_response(response.content)
        return data[0] if data else None
    except Exception:
        return None


def download_torrent_file(tid: int) -> bytes:
    response = requests.get(
        f"{settings.mam_base}/tor/download.php?tid={tid}",
        headers=mam_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.content


def get_mam_stats() -> Optional[dict]:
    import gzip
    import json

    headers = mam_headers()
    try:
        response = requests.get(
            f"{settings.mam_base}/jsonLoad.php",
            headers=headers,
            timeout=15,
            allow_redirects=True,
        )
        if "login.php" in response.url or response.status_code != 200:
            return None
        raw = response.content
        try:
            data = json.loads(raw)
        except Exception:
            data = json.loads(gzip.decompress(raw))
        username = data.get("username")
        if not username:
            return None
        return {
            "username": username,
            "upload": str(data.get("uploaded", "N/A")),
            "download": str(data.get("downloaded", "N/A")),
            "ratio": str(data.get("ratio", "N/A")),
            "bonus_points": int(float(data["seedbonus"])) if data.get("seedbonus") is not None else None,
        }
    except Exception:
        return None
