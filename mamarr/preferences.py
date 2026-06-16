from typing import Literal, Optional

from mamarr.db import get_db, utc_now
from mamarr.format_filter import AudioFormatPreference

PREFERENCE_KEY = "audio_format"
DEFAULT_PREFERENCE: AudioFormatPreference = "none"


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


def get_all_preferences() -> dict:
    return {"audio_format": get_format_preference()}
