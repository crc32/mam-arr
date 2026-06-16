import re
from typing import Literal

AudioFormatPreference = Literal["m4a", "mp3", "none"]


def normalize_text(value: str) -> str:
    text = (value or "").lower().strip()
    text = re.sub(r"\s+", " ", text)
    return text


def dedup_key(title: str, author: str, narrator: str) -> str:
    """Group format variants; separate authors and re-recordings by narrator."""
    return "|".join(
        normalize_text(part) for part in (title, author, narrator)
    )


def parse_filetypes(filetypes: str) -> set[str]:
    return {t.strip().lower() for t in (filetypes or "").split(",") if t.strip()}


def has_format(filetypes: str, preference: AudioFormatPreference) -> bool:
    if preference == "none":
        return True
    types = parse_filetypes(filetypes)
    if preference == "m4a":
        return bool(types & {"m4a", "m4b"})
    return preference in types


def apply_format_preference(
    results: list[dict],
    preference: AudioFormatPreference,
) -> list[dict]:
    if preference == "none" or not results:
        return results

    groups: dict[str, list[dict]] = {}
    for item in results:
        key = dedup_key(
            item.get("title") or "",
            item.get("author") or "",
            item.get("narrator") or "",
        )
        groups.setdefault(key, []).append(item)

    filtered: list[dict] = []
    for group in groups.values():
        preferred = [r for r in group if has_format(r.get("filetypes") or "", preference)]
        if preferred:
            filtered.extend(preferred)
        else:
            filtered.extend(group)

    return filtered
