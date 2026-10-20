"""Small, sanitized recovery records; failed content is never provider availability."""
from datetime import timedelta

FAILURE_KINDS = frozenset({"billing", "rate_limited", "network", "provider", "configuration"})


def failure_kind(value):
    return value if isinstance(value, str) and value in FAILURE_KINDS else None


def recovery_delay(cycle):
    # One probe after each cooldown, not another burst of rapid attempts.
    return timedelta(minutes=15 if cycle == 1 else 60 if cycle == 2 else 360)


def record(generation, reason, previous, now):
    cycle = min(3, int((previous or {}).get("cycle", 0)) + 1)
    return {"generation": generation, "reason": failure_kind(reason) or "provider",
            "cycle": cycle, "state": "waiting", "retry_at": (now + recovery_delay(cycle)).isoformat()}


def valid_record(value, generation):
    if (not isinstance(value, dict) or value.get("generation") != generation
            or value.get("state") not in {"waiting", "attempting"}
            or value.get("cycle") not in {1, 2, 3} or not failure_kind(value.get("reason"))):
        return None
    return value
