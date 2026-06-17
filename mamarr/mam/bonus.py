import time
from typing import Any, Literal, Optional, Union

import requests

from mamarr.config import settings, normalise_mam_cookie
from mamarr.mam.client import mam_headers


class MamBonusError(Exception):
    pass


def _load_account_json() -> dict[str, Any]:
    if not settings.mam_cookie:
        raise MamBonusError("MAM_COOKIE is not configured")

    response = requests.get(
        f"{settings.mam_base}/jsonLoad.php",
        headers=mam_headers(),
        timeout=15,
        allow_redirects=True,
    )
    if "login.php" in response.url or response.status_code != 200:
        raise MamBonusError("MAM session invalid — check MAM_COOKIE")

    import gzip
    import json

    raw = response.content
    try:
        data = json.loads(raw)
    except Exception:
        data = json.loads(gzip.decompress(raw))

    if not data.get("username"):
        raise MamBonusError("Unexpected MAM account response")
    return data


def get_bonus_points() -> int:
    data = _load_account_json()
    seedbonus = data.get("seedbonus")
    if seedbonus is None:
        raise MamBonusError("Bonus points not found in MAM account response")
    return int(float(seedbonus))


def buy_upload_credit(amount: Union[int, Literal["max"]]) -> dict[str, Any]:
    """
    Purchase upload credit from the MAM bonus points store.

    amount: integer >= 50 (GiB), or "max" for all affordable points
            (API string "Max Affordable " including trailing space).
    """
    if isinstance(amount, int):
        if amount < 50:
            raise MamBonusError("Minimum upload purchase is 50 GiB")
        amount_param: Union[int, str] = amount
    else:
        amount_param = "Max Affordable "

    params = {
        "spendtype": "upload",
        "amount": amount_param,
        "_": int(time.time() * 1000),
    }

    response = requests.get(
        f"{settings.mam_base}/json/bonusBuy.php",
        params=params,
        headers=mam_headers(referer=f"{settings.mam_base}/store.php"),
        timeout=20,
    )
    if response.status_code != 200:
        raise MamBonusError(f"bonusBuy.php returned HTTP {response.status_code}")

    import json

    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        raise MamBonusError(f"Invalid JSON from bonusBuy.php: {response.text[:200]}") from exc

    if data.get("error"):
        raise MamBonusError(str(data["error"]))

    success = data.get("success")
    if success is False:
        message = data.get("message") or data.get("msg") or "Bonus purchase failed"
        raise MamBonusError(str(message))

    new_points: Optional[int] = None
    if "seedbonus" in data:
        new_points = int(float(data["seedbonus"]))

    return {
        "status": "ok",
        "spendtype": "upload",
        "amount_requested": amount_param,
        "bonus_points_remaining": new_points,
        "response": data,
    }


def convert_all_bonus_to_upload_credit() -> dict[str, Any]:
    """Spend all affordable bonus points on upload credit (Max Affordable)."""
    points_before = get_bonus_points()
    if points_before < 50 * 500:  # rough minimum cost for 50 GiB; API enforces precisely
        raise MamBonusError(
            f"Insufficient bonus points ({points_before}) to buy minimum 50 GiB upload credit"
        )

    result = buy_upload_credit("max")
    result["bonus_points_before"] = points_before
    if result.get("bonus_points_remaining") is not None:
        result["bonus_points_spent"] = points_before - result["bonus_points_remaining"]
    return result
