"""Route only enrolled accounts to the separately deployed parser worker."""
import os

from .flight_import_rollout import FEATURE_FLAGS, enabled


def route_parser_pilot(name, args, kwargs, options, task=None, **_):
    if name not in {"gmail.import", "app.tasks.gmail_history_tasks.scan_history_page"}:
        return None
    if os.environ.get("TROTTER_PARSER_PILOT_ROUTING") != "1":
        return None
    args, kwargs = args or (), kwargs or {}
    uid = kwargs.get("user_id", args[1] if len(args) > 1 else None)
    if any(enabled(flag, uid) for flag in FEATURE_FLAGS):
        return {"queue": "flight_parser_pilot"}
    return None
