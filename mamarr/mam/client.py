from typing import Any, Optional

import requests

from mamarr.config import settings, normalise_mam_cookie
from mamarr.mam.errors import MamError


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


def _parse_json_response(raw_bytes: bytes) -> Any:
    import gzip
    import json

    try:
        return json.loads(raw_bytes)
    except Exception:
        return json.loads(gzip.decompress(raw_bytes))


def load_user_data(
    *,
    include_notifications: bool = False,
    include_client_stats: bool = False,
    include_snatch_summary: bool = False,
    pretty: bool = False,
) -> dict[str, Any]:
    """Load user data from jsonLoad.php with optional extra sections."""
    if not settings.mam_cookie:
        raise MamError("MAM_COOKIE is not configured")

    params: dict[str, str] = {}
    if include_notifications:
        params["notif"] = ""
    if include_client_stats:
        params["clientStats"] = ""
    if include_snatch_summary:
        params["snatch_summary"] = ""
    if pretty:
        params["pretty"] = ""

    response = requests.get(
        f"{settings.mam_base}/jsonLoad.php",
        params=params or None,
        headers=mam_headers(),
        timeout=15,
        allow_redirects=True,
    )
    if "login.php" in response.url or response.status_code != 200:
        raise MamError("MAM session invalid — check MAM_COOKIE")

    data = _parse_json_response(response.content)
    if not isinstance(data, dict) or not data.get("username"):
        raise MamError("Unexpected MAM account response")
    return data


def _parse_mam_response(raw_bytes: bytes) -> list[dict]:
    parsed = _parse_json_response(raw_bytes)
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
    start_number: int = 0,
    my_snatched_only: bool = False,
) -> list[dict]:
    if field not in {"title", "author", "series", "narrator"}:
        field = "title"

    perpage = max(5, min(perpage, 100))

    payload: dict[str, Any] = {
        "tor": {
            "text": query,
            "srchIn": [field],
            "searchType": "all",
            "searchIn": "torrents",
            "main_cat": ["13"],
            "browse_lang": ["1"],
            "perpage": perpage,
            "startNumber": str(start_number),
        },
        "thumbnail": "true",
        "description": "true",
    }
    if my_snatched_only:
        payload["my_snatched"] = ""

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


def search_mam_all(
    query: str,
    field: str = "title",
    perpage: int = 100,
    max_pages: int = 10,
    my_snatched_only: bool = False,
) -> list[dict]:
    """Fetch all pages of MAM search results up to max_pages."""
    all_results: list[dict] = []
    start = 0

    for _ in range(max_pages):
        page = search_mam(
            query,
            field=field,
            perpage=perpage,
            start_number=start,
            my_snatched_only=my_snatched_only,
        )
        if not page:
            break
        all_results.extend(page)
        if len(page) < perpage:
            break
        start += perpage

    return all_results


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


def download_torrent_file(tid: int, use_freeleech_wedge: bool = False) -> bytes:
    params: dict[str, Any] = {"tid": tid}
    if use_freeleech_wedge:
        params["fl"] = ""
    response = requests.get(
        f"{settings.mam_base}/tor/download.php",
        params=params,
        headers=mam_headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.content


def get_mam_stats() -> Optional[dict]:
    try:
        data = load_user_data()
        return {
            "username": data.get("username"),
            "upload": str(data.get("uploaded", "N/A")),
            "download": str(data.get("downloaded", "N/A")),
            "ratio": str(data.get("ratio", "N/A")),
            "bonus_points": int(float(data["seedbonus"])) if data.get("seedbonus") is not None else None,
            "classname": data.get("classname"),
            "uid": data.get("uid"),
        }
    except MamError:
        return None
