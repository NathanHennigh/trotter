"""Place aliases stated next to a saved name in the original caption.

No model guesses, translations or provider names become source evidence here.
"""
from __future__ import annotations

import re
import unicodedata


def _normal(value):
    value = unicodedata.normalize("NFKD", str(value or "")).casefold()
    return " ".join(re.sub(r"[^\w\s]", " ", "".join(c for c in value if not unicodedata.combining(c))).split())


def source_place_aliases(place_name: str | None, caption: str | None) -> list[str]:
    """Read at most two direct `Named place (local name)` pairs.

    Case/accents/punctuation can differ from the saved title. An alias must be
    directly attached to that title, not to another stop elsewhere in a reel.
    Practical annotations and instructions are not alternative identities.
    """
    wanted = _normal(place_name)
    if not wanted or not caption:
        return []
    source = str(caption)[:60_000]
    result, seen = [], {wanted}
    for match in re.finditer(r"\(([^()\n]{2,120})\)", source):
        preceding = _normal(source[max(0, match.start() - 400):match.start()])
        if preceding != wanted and not preceding.endswith(" " + wanted):
            continue
        alias = match.group(1).strip()
        normalized = _normal(alias)
        words = normalized.split()
        if not normalized or normalized in seen or not 1 <= len(words) <= 10:
            continue
        if (sum(char.isalpha() for char in normalized) < 3 or any(char.isdigit() for char in alias)
                or re.search(r"https?://|www\.|[@#=<>]|\b(?:not|formerly|closed|near|inside|behind|avoid|comment|click|link|free|entry|entrance|reservation|reservations|opening|hours|minute|minutes|km|tickets?|book|booking)\b", alias, re.IGNORECASE)):
            continue
        # A whole instruction/sentence is not a place label.
        if any(char in alias for char in ".!?;:"):
            continue
        seen.add(normalized)
        result.append(alias)
        if len(result) == 2:
            break
    return result


def caption_for_place(item) -> str | None:
    """Use retained source evidence without rewriting a venue's original caption."""
    source = getattr(item, "source_post", None)
    values = list(dict.fromkeys(str(value) for value in (getattr(source, "caption", None), item.caption) if value))
    return "\n".join(values)[:60_000] or None
