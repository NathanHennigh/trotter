"""Explicit account cohort for staged flight-import authority.

Every feature has its own master switch. The shared cohort is empty by default;
enabling a switch alone never opts every account into new recovery behavior.
Read on each call so removing an account or switching off takes effect without
retaining a cached decision. This gate never deletes already recovered records.
"""
from __future__ import annotations

import os
import re


ALLOWLIST_ENV = "FLIGHT_IMPORT_RECOVERY_USER_IDS"
FEATURE_FLAGS = frozenset({
    "BOOKING_STRICT_ENRICHMENT_ENABLED",
    "CARRIER_TRAVEL_CORROBORATION_ENABLED",
    "BOOKING_LEG_RECONCILIATION_ENABLED",
    "BOOKING_CONTEXTUAL_TRIP_GROUPING_ENABLED",
})
_MAX_USER_ID = 2**63 - 1


def enabled(flag: str, user_id: int | None) -> bool:
    """Require an explicit master switch and a wholly valid account allowlist.

    ``*`` alone is the only all-account opt-in. Empty entries, zero/negative IDs,
    mixed wildcards and other malformed tokens disable the entire cohort rather
    than partially accepting a potentially mistyped production setting.
    """
    if flag not in FEATURE_FLAGS or type(user_id) is not int or not 0 < user_id <= _MAX_USER_ID:
        return False
    if os.getenv(flag, "false").strip().lower() not in {"1", "true"}:
        return False
    raw = os.getenv(ALLOWLIST_ENV, "").strip()
    if raw == "*":
        return True
    if not raw:
        return False
    ids = set()
    for token in raw.split(","):
        token = token.strip()
        if not re.fullmatch(r"[1-9][0-9]{0,18}", token):
            return False
        value = int(token)
        if value > _MAX_USER_ID:
            return False
        ids.add(value)
    return user_id in ids
