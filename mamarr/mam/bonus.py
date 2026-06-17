import time
from typing import Any, Literal, Optional, Union

import requests

from mamarr.config import settings, normalise_mam_cookie
from mamarr.mam.client import mam_headers
from mamarr.mam.errors import MamBonusError


def get_bonus_points() -> int:
    from mamarr.mam.client import load_user_data

    data = load_user_data()
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


BONUS_HISTORY_TYPES = (
    "giftPoints",
    "giftWedge",
    "wedgePF",
    "wedgeGFL",
    "torrentThanks",
    "millionaires",
)


def get_bonus_history(
    types: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Return bonus point and wedge transaction history."""
    if not settings.mam_cookie:
        raise MamBonusError("MAM_COOKIE is not configured")

    selected = types or list(BONUS_HISTORY_TYPES)
    params = [("type[]", t) for t in selected]

    response = requests.get(
        f"{settings.mam_base}/json/userBonusHistory.php",
        params=params,
        headers=mam_headers(),
        timeout=20,
    )
    if response.status_code != 200:
        raise MamBonusError(f"userBonusHistory.php returned HTTP {response.status_code}")

    import json

    try:
        data = response.json()
    except json.JSONDecodeError as exc:
        raise MamBonusError(f"Invalid JSON from userBonusHistory.php: {response.text[:200]}") from exc

    if not isinstance(data, list):
        raise MamBonusError("Unexpected bonus history response format")
    return data
