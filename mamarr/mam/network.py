from typing import Any, Optional

import requests

from mamarr.config import settings, normalise_mam_cookie
from mamarr.mam.client import mam_headers
from mamarr.mam.errors import MamError


def _seedbox_headers() -> dict[str, str]:
    cookie = settings.mam_dynamic_seedbox_cookie or settings.mam_cookie
    base = settings.mam_seedbox_base.rstrip("/")
    return {
        **mam_headers(referer=f"{base}/"),
        "Cookie": f"mam_id={normalise_mam_cookie(cookie)}" if cookie else "",
    }


def get_ip_info(host: Optional[str] = None) -> dict[str, Any]:
    """
    Return IP, ASN, and AS organization as seen by MAM.
    Rate limit: 1 request per minute.
    """
    base = (host or settings.mam_base).rstrip("/")
    response = requests.get(
        f"{base}/json/jsonIp.php",
        headers=mam_headers(),
        timeout=15,
    )
    if response.status_code != 200:
        raise MamError(f"jsonIp.php returned HTTP {response.status_code}")

    try:
        data = response.json()
    except Exception as exc:
        raise MamError(f"Invalid JSON from jsonIp.php: {response.text[:200]}") from exc

    return {
        "ip": data.get("ip"),
        "ASN": data.get("ASN") or data.get("asn"),
        "AS": data.get("AS"),
        "time": data.get("time"),
        "host": base,
    }


def update_dynamic_seedbox_ip() -> dict[str, Any]:
    """
    Register the current egress IP as your dynamic seedbox address.

    Requires an IP- or ASN-locked API session cookie (configured separately from
    your normal browser session in MAM Security preferences).
    Rate limit: once per hour (rolling).
    """
    cookie = settings.mam_dynamic_seedbox_cookie or settings.mam_cookie
    if not cookie:
        raise MamError("MAM_DYNAMIC_SEEDBOX_COOKIE or MAM_COOKIE is required")

    base = settings.mam_seedbox_base.rstrip("/")
    response = requests.get(
        f"{base}/json/dynamicSeedbox.php",
        headers=_seedbox_headers(),
        timeout=20,
    )

    try:
        data = response.json()
    except Exception as exc:
        raise MamError(
            f"Invalid JSON from dynamicSeedbox.php (HTTP {response.status_code}): "
            f"{response.text[:200]}"
        ) from exc

    success = data.get("Success", data.get("success"))
    msg = data.get("msg") or data.get("message") or ""

    if response.status_code == 429:
        raise MamError(f"Rate limited: {msg or 'Last change too recent'}")
    if response.status_code == 403 or success is False:
        raise MamError(msg or f"dynamicSeedbox.php failed (HTTP {response.status_code})")

    return {
        "status": "ok",
        "message": msg,
        "ip": data.get("ip"),
        "ASN": data.get("ASN") or data.get("asn"),
        "AS": data.get("AS"),
        "http_status": response.status_code,
    }
