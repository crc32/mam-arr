from typing import Literal

from mamarr.db import get_db, utc_now
from mamarr.format_filter import AudioFormatPreference

PREFERENCE_KEY = "audio_format"
OWNERSHIP_FILTER_KEY = "ownership_filter"
DEFAULT_PREFERENCE: AudioFormatPreference = "none"
DEFAULT_OWNERSHIP_FILTER: Literal["hide", "mark", "allow"] = "hide"


def get_format_preference() -> AudioFormatPreference:
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM preferences WHERE key = ?",
            (PREFERENCE_KEY,),
        ).fetchone()
    if not row:
        return DEFAULT_PREFERENCE
    value = row["value"]
    if value in {"m4a", "mp3", "none"}:
        return value
    return DEFAULT_PREFERENCE


def set_format_preference(preference: Literal["m4a", "mp3", "none"]) -> AudioFormatPreference:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO preferences (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (PREFERENCE_KEY, preference),
        )
        conn.commit()
    return preference


def get_ownership_filter_mode() -> Literal["hide", "mark", "allow"]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT value FROM preferences WHERE key = ?",
            (OWNERSHIP_FILTER_KEY,),
        ).fetchone()
    if not row:
        return DEFAULT_OWNERSHIP_FILTER
    value = row["value"]
    if value in {"hide", "mark", "allow"}:
        return value
    return DEFAULT_OWNERSHIP_FILTER


def set_ownership_filter_mode(mode: Literal["hide", "mark", "allow"]) -> str:
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO preferences (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (OWNERSHIP_FILTER_KEY, mode),
        )
        conn.commit()
    return mode


def get_all_preferences() -> dict:
    return {
        "audio_format": get_format_preference(),
        "ownership_filter": get_ownership_filter_mode(),
    }
