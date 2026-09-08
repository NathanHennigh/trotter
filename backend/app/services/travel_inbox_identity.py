"""Identify people to retain alongside a mailbox owner's personal itinerary.

This is a pure projection of one booking observation. It neither looks up other
accounts nor equates different passenger spellings. Ambiguous people remain an
unassigned record so the underlying flight can be reviewed without guessing.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any, Literal, TypedDict

from .passenger_identity import names_match


class RetainedPassenger(TypedDict):
    passenger_name: str | None
    passenger_key: str | None
    reason: Literal["other_traveler", "companion", "unassigned"]


_TITLES = {"mr", "mrs", "ms", "miss", "dr", "prof", "mstr"}
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}
_MAX_PASSENGER_IDENTITY_LENGTH = 255
_PLACEHOLDERS = {
    "unknown", "unassigned", "unnamed", "none", "null", "n/a", "na", "tbd",
    "passenger name", "traveler name", "traveller name", "first name", "last name",
    "full name", "no name", "not provided", "not available", "name unavailable",
    "unknown passenger", "unknown traveler", "unknown person", "unassigned passenger",
}


def _field(value: Any, key: str, default: Any = None) -> Any:
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


def _display_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    name = " ".join(unicodedata.normalize("NFC", value).split())
    return name if name and name.casefold() not in _PLACEHOLDERS else None


def _name_key(name: str) -> str:
    # Deliberately preserve punctuation, accents, word order, titles and middle
    # names. These keys group identical display names, not inferred people.
    return unicodedata.normalize("NFC", name).casefold()


def _name_words(name: str) -> list[str]:
    words = re.findall(r"[^\W\d_]+", name.casefold(), re.UNICODE)
    words = [word for word in words if word not in _TITLES]
    while words and words[-1] in _SUFFIXES:
        words.pop()
    return words


def _has_full_name(name: str) -> bool:
    # A labeled name with a full given and family name can be retained. Initials
    # such as A. Avery or AVERY/A cannot identify a distinct person. Middle
    # initials remain allowed when both outer names are explicit.
    if any(char.isdigit() for char in name) or any(char in name for char in "@<>:=;|?"):
        return False
    words = _name_words(name)
    return len(words) >= 2 and len(words[0]) > 1 and len(words[-1]) > 1


def _unassigned() -> RetainedPassenger:
    return {"passenger_name": None, "passenger_key": None, "reason": "unassigned"}


def retained_passengers(observation: Any, user: Any) -> list[RetainedPassenger]:
    """Return safely named companions/other travelers and one ambiguity marker.

    Only explicit, applicable traveler evidence can supply a name. Scalar or
    list-only legacy names are retained in the source observation but cannot
    establish a person here. User-decision observations are handled separately
    by the caller, which can link them to their original named observations.
    """
    facts = _field(observation, "facts", {})
    facts = facts if isinstance(facts, Mapping) else {}
    if "user_decision" in facts:
        return []

    ownership = _field(observation, "ownership", facts.get("ownership", "unknown"))
    if ownership not in {"self", "other"}:
        return [_unassigned()]

    raw_aliases = _field(user, "travel_name_aliases", [])
    aliases = raw_aliases if isinstance(raw_aliases, (list, tuple)) else []
    candidates = [name for value in [_field(user, "name"), *aliases]
                  if (name := _display_name(value)) and "@" not in name]
    raw_evidence = facts.get("passenger_evidence")
    if isinstance(raw_evidence, Mapping):
        evidence = [raw_evidence]
    elif isinstance(raw_evidence, list):
        evidence = raw_evidence
    else:
        evidence = []

    retained: list[RetainedPassenger] = []
    seen: set[str] = set()
    uncertain = False
    reason = "companion" if ownership == "self" else "other_traveler"
    for item in evidence:
        if not isinstance(item, Mapping) or item.get("role") != "traveler":
            continue
        if item.get("scope_ambiguous"):
            uncertain = True
            continue
        if item.get("applies") is not True:
            # Evidence for a different booking in the same message must not
            # manufacture a traveler or an ambiguity on this flight.
            continue
        name = _display_name(item.get("name"))
        if not name or not _has_full_name(name):
            uncertain = True
            continue
        key = _name_key(name)
        # Both persisted identity fields have a 255-character limit. Casefold
        # can expand Unicode characters, so a valid display length is not enough.
        # Keep the original evidence in the ledger and retain an unnamed item.
        if len(name) > _MAX_PASSENGER_IDENTITY_LENGTH or len(key) > _MAX_PASSENGER_IDENTITY_LENGTH:
            uncertain = True
            continue
        if not candidates:
            uncertain = True
            continue
        words = _name_words(name)
        if any(names_match(name, candidate) and _has_full_name(candidate)
               and sorted(words) == sorted(_name_words(candidate)) for candidate in candidates):
            continue
        # An approved initial or a partial compound surname can still resemble
        # the owner, but is not sufficient to label a different person.
        if any(names_match(name, candidate)
               or (set(words) < set(_name_words(candidate)))
               or (set(_name_words(candidate)) < set(words))
               for candidate in candidates):
            uncertain = True
            continue
        if key not in seen:
            retained.append({"passenger_name": name, "passenger_key": key, "reason": reason})
            seen.add(key)

    # OTHER with only owner-name evidence is contradictory rather than an empty
    # result. SELF with an explicit owner-only manifest legitimately has no one
    # to retain in the non-personal travel inbox.
    if uncertain or (ownership == "other" and not retained):
        retained.append(_unassigned())
    return retained
