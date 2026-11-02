"""Read-only, aggregate operational evidence for Gmail flight imports.

Never return free-form errors, subjects, sender addresses, passenger evidence,
provider message IDs, page tokens, or connection credentials. Unknown labels
remain unknown rather than being copied from untrusted persisted JSON.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re
from uuid import UUID

from sqlalchemy import or_, select

from ..models import BookingObservation, GmailHistoryState, Message, SyncJob


OWNERSHIP = frozenset({"passenger_identity_unresolved", "conflicting_latest_passenger", "ambiguous_matching_names"})
CONFLICTS = frozenset({"legacy_flight_identity_conflict", "document_leg_identity_conflict",
    "ambiguous_latest_evidence", "unresolved_source_chronology", "ambiguous_cancellation_time",
    "ambiguous_cancellation_scope", "unresolved_cancellation_scope", "legacy_booking_protected"})
REASONS = OWNERSHIP | CONFLICTS | frozenset({"strong_flight_evidence_but_no_segments",
    "partial_flight_evidence_but_no_segments", "weak_flight_evidence_but_candidate_query_matched",
    "ticket_attachment_needs_review", "ignored_nonflight_promo", "ancillary_existing_pnr",
    "cancellation_notice", "parsed_flights", "reconciled_flights", "carrier_support_examined"})
TEMPLATES = frozenset({"heuristic", "ics", "jsonld", "shape", "subject", "v5", "v6",
    "v5_ba_eticket", "v5_frontier_departing", "v5_southwest_sparse", "bilt", "philippines_etravel",
    "shape_airline_receipt_vertical_rows", "shape_alaska_trip_detail_blocks",
    "shape_allegiant_labeled_itinerary", "shape_allegiant_trip_detail_sections",
    "shape_boarding_pass_local_table", "shape_checkin_route_blocks", "shape_column_itinerary_table",
    "shape_compact_airline_flight_rows", "shape_dated_flight_cards", "shape_delta_receipt_table",
    "shape_eticket_flight_information_table", "shape_jetblue_compact_itinerary",
    "shape_labeled_depart_arrive_segments", "shape_labeled_route_time_blocks",
    "shape_lifemiles_flight_details", "shape_numbered_flight_cards", "shape_ota_multi_confirmation",
    "shape_ota_vertical_itinerary", "shape_pdf_ticket_itinerary", "shape_schedule_delay_table",
    "shape_southwest_itinerary_blocks", "shape_spirit_compact_itinerary", "shape_vertical_itinerary_rows",
    "shape_vertical_route_date_time_blocks"})
CARRIERS = frozenset("AA UA DL WN AS B6 NK F9 G4 SY BA AF LH KL IB AZ TK EK QR SQ CX NH JL KE MH TG CI OZ CA MU QF NZ AC WS VS ET SA MS RJ EY GF SV AI VN BR AY SK LO OS SN TP JU FR U2 VY PC HV W6 DY Z2 Y4 AM 5J PR 6E LX HA FI JQ AK TR VA AV CM LA UX EI RO SU UL OD BI WY KU PK G9 FZ".split())
HISTORY_ERRORS = frozenset({"gmail_connection_required", "history_fetch_failed", "history_worker_failed",
    "history_lease_expired", "history_page_failed", "history_discovery_failed", "history_enqueue_failed",
    "history_processing_failed", "gmail_fetch_failed", "import_failed", "retry_exhausted"})
JOB_STATES = frozenset({"pending", "running", "completed", "failed"})
HISTORY_STATES = frozenset({"pending", "queued", "running", "complete", "paused"})


def _dict(value):
    return value if isinstance(value, dict) else {}


def _label(value, allowed):
    return value if isinstance(value, str) and value in allowed else "unknown"


def _utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _seconds(start, end):
    start, end = _utc(start), _utc(end)
    if start is None or end is None or end < start:
        return None
    return round((end - start).total_seconds(), 3)


def _stamp(value):
    return _utc(value).isoformat() if value else None


def _job_reference(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return "opaque-" + sha256(str(value).encode()).hexdigest()[:16]


def _failure_category(value):
    if not value:
        return None
    value = str(value).casefold()
    if "reconnect gmail" in value or "gmail_connection_required" in value or "invalid_grant" in value:
        return "gmail_reconnect_required"
    if "some emails could not be checked" in value:
        return "message_fetch_failed"
    if "rate limit" in value or "ratelimit" in value or "quota" in value:
        return "provider_rate_limit"
    if "timeout" in value or "timed out" in value:
        return "timeout"
    return "other_failure"


def _carrier(number):
    if not isinstance(number, str):
        return None
    match = re.fullmatch(r"([A-Z0-9]{2})\s*\d{1,4}[A-Z]?", number.upper().strip())
    return match[1] if match and match[1] in CARRIERS else None


def _message_outcome(row):
    evidence = _dict(row.parse_evidence)
    status = getattr(row.status, "value", row.status)
    reason = _label(row.parse_error or evidence.get("reason"), REASONS)
    partial = _dict(evidence.get("partial_flight_evidence"))
    if status == "pending":
        outcome = "pending"
    elif row.ignored or status == "ignored":
        outcome = "ignored"
    elif status == "accepted" and (evidence.get("resolved") is True or not row.parse_error):
        outcome = "resolved"
    elif reason in OWNERSHIP:
        outcome = "ownership_review"
    elif reason in CONFLICTS:
        outcome = "identity_schedule_or_protection_review"
    elif reason == "ticket_attachment_needs_review":
        outcome = "attachment_review"
    elif reason == "partial_flight_evidence_but_no_segments" or partial.get("missing_fields"):
        outcome = "incomplete_evidence"
    elif reason == "strong_flight_evidence_but_no_segments":
        outcome = "unsupported_or_unrecognized_format"
    elif reason == "weak_flight_evidence_but_candidate_query_matched":
        outcome = "unconfirmed_candidate"
    else:
        outcome = "unclassified_review"
    template = _label(evidence.get("source"), TEMPLATES)
    if template == "unknown" and partial.get("provider") == "philippines_etravel":
        template = "philippines_etravel"
    carriers = set()
    partial_carrier = partial.get("carrier")
    if isinstance(partial_carrier, str) and partial_carrier in CARRIERS:
        carriers.add(partial_carrier)
    numbers = _dict(evidence.get("evidence_gate")).get("flight_numbers")
    for number in numbers if isinstance(numbers, list) else []:
        if code := _carrier(number):
            carriers.add(code)
    return outcome, reason, template, carriers


def build_scan_health(db, *, user_ids=None, now=None, lookback_hours=24,
                      stale_minutes=30, pending_minutes=15, max_jobs=50):
    """Inspect SQL state only. Message outcomes are cumulative, not job metrics."""
    if min(lookback_hours, stale_minutes, pending_minutes, max_jobs) <= 0:
        raise ValueError("Report limits must be positive")
    if user_ids is not None and (not user_ids or any(type(i) is not int or i <= 0 for i in user_ids)):
        raise ValueError("Select positive account IDs or explicitly select all accounts")
    user_ids = sorted(set(user_ids)) if user_ids is not None else None
    now = _utc(now or datetime.now(timezone.utc))
    cutoff = now - timedelta(hours=lookback_hours)

    def scoped(statement, model):
        return statement.where(model.user_id.in_(user_ids)) if user_ids is not None else statement

    job_query = scoped(select(SyncJob.id, SyncJob.user_id, SyncJob.state, SyncJob.started_at,
        SyncJob.updated_at, SyncJob.scanned_count, SyncJob.parsed_count, SyncJob.segment_count,
        SyncJob.error_message).where(or_(SyncJob.updated_at >= cutoff,
        SyncJob.state.in_(["pending", "running"]))), SyncJob)
    state_counts, warning_counts, failure_counts = Counter(), Counter(), Counter()
    spans = []
    job_details = []
    with db.no_autoflush:
        for row in db.execute(job_query).yield_per(500):
            state = _label(row.state, JOB_STATES)
            state_counts[state] += 1
            idle = _seconds(row.updated_at, now)
            warnings = []
            if idle is None:
                warnings.append("missing_or_future_update_timestamp")
            if state == "running" and idle is not None and idle >= stale_minutes * 60:
                warnings.append("suspected_stalled")
            if state == "pending" and idle is not None and idle >= pending_minutes * 60:
                warnings.append("pending_without_recent_update")
            span = _seconds(row.started_at, row.updated_at) if state in {"completed", "failed"} else None
            if state in {"completed", "failed"} and span is not None:
                spans.append(span)
            failure = _failure_category(row.error_message) if state == "failed" else None
            if failure:
                failure_counts[failure] += 1
            warning_counts.update(warnings)
            job_details.append({"job_ref": _job_reference(row.id), "user_id": row.user_id,
                "state": state, "recorded_start_at": _stamp(row.started_at), "last_update_at": _stamp(row.updated_at),
                "seconds_since_update": idle, "recorded_span_seconds": span,
                "elapsed_since_recorded_start_seconds": _seconds(row.started_at, now) if state == "running" else None,
                "scanned_count": row.scanned_count, "parsed_count": row.parsed_count,
                "inserted_segment_count": row.segment_count, "failure_category": failure, "warnings": warnings})
        job_details.sort(key=lambda r: (not bool(r['warnings']), r['state'] not in {'failed', 'pending', 'running'},
                                       -(r['seconds_since_update'] or 0), r['job_ref']))

        histories = []
        hq = scoped(select(GmailHistoryState.user_id, GmailHistoryState.state, GmailHistoryState.updated_at,
            GmailHistoryState.pending_message_ids, GmailHistoryState.attempts, GmailHistoryState.next_attempt_at,
            GmailHistoryState.lease_until, GmailHistoryState.error_code), GmailHistoryState)
        for row in db.execute(hq).yield_per(500):
            state = _label(row.state, HISTORY_STATES)
            lease_expired = state in {"running", "queued"} and row.lease_until is not None and _utc(row.lease_until) <= now
            histories.append({"user_id": row.user_id, "state": state,
                "pending_message_count": len(row.pending_message_ids) if isinstance(row.pending_message_ids, list) else None,
                "attempts": row.attempts, "last_update_at": _stamp(row.updated_at),
                "next_attempt_at": _stamp(row.next_attempt_at), "lease_until": _stamp(row.lease_until),
                "lease_expired": lease_expired,
                "error_category": _label(row.error_code, HISTORY_ERRORS) if row.error_code else None})

        # Structured observation numbers provide carrier context; no bodies,
        # passenger names, booking references or sender addresses are selected.
        carriers_by_source = defaultdict(set)
        oq = scoped(select(BookingObservation.user_id, BookingObservation.source_message_id,
                           BookingObservation.flight_number), BookingObservation)
        for row in db.execute(oq).yield_per(500):
            if code := _carrier(row.flight_number):
                carriers_by_source[(row.user_id, row.source_message_id)].add(code)
        outcomes, reasons, templates, carriers, versions = Counter(), Counter(), defaultdict(Counter), defaultdict(Counter), Counter()
        other_retained_messages = 0
        mq = scoped(select(Message.user_id, Message.provider_msg_id, Message.status, Message.ignored,
                           Message.parse_error, Message.parse_evidence, Message.parse_version), Message)
        for row in db.execute(mq).yield_per(500):
            outcome, reason, template, codes = _message_outcome(row)
            codes |= carriers_by_source.get((row.user_id, row.provider_msg_id), set())
            outcomes[outcome] += 1
            reasons[reason] += 1
            templates[template][outcome] += 1
            for code in codes or {"unknown"}:
                carriers[code][outcome] += 1
            version = row.parse_version if type(row.parse_version) is int and 0 <= row.parse_version <= 100000 else "unknown"
            versions[str(version)] += 1
            held_other = _dict(row.parse_evidence).get("held_other")
            if type(held_other) is int and held_other > 0:
                other_retained_messages += 1
    attention = bool(state_counts.get('failed') or warning_counts.get('suspected_stalled') or
                     warning_counts.get('pending_without_recent_update') or
                     any(h['lease_expired'] or h['state'] == 'paused' for h in histories))
    return {"schema_version": 1, "generated_at": _stamp(now),
        "scope": {"user_ids": user_ids, "job_updated_since": _stamp(cutoff), "all_active_jobs_included": True,
                  "message_scope": "all currently stored outcomes for selected accounts; not linked to jobs"},
        "attention_required": attention,
        "jobs": {"total": sum(state_counts.values()), "by_state": dict(sorted(state_counts.items())),
            "warnings": dict(sorted(warning_counts.items())), "failure_categories": dict(sorted(failure_counts.items())),
            "recorded_terminal_spans_seconds": {"count": len(spans), "min": min(spans) if spans else None,
                "max": max(spans) if spans else None, "mean": round(sum(spans) / len(spans), 3) if spans else None},
            "details_truncated": len(job_details) > max_jobs, "details": job_details[:max_jobs]},
        "history_checkpoints": sorted(histories, key=lambda r: r['user_id']),
        "messages": {"total": sum(outcomes.values()), "outcomes": dict(sorted(outcomes.items())),
            "reasons": dict(sorted(reasons.items())), "parser_versions": dict(sorted(versions.items())),
            "by_template": {k: dict(sorted(v.items())) for k, v in sorted(templates.items())},
            "by_carrier": {k: dict(sorted(v.items())) for k, v in sorted(carriers.items())},
            "messages_retaining_other_travelers": other_retained_messages},
        "limitations": [
            "SyncJob.started_at is initialized at creation and overwritten at worker start; exact queue wait is not persisted.",
            "Recorded terminal spans are updated_at minus started_at, not guaranteed worker runtimes (for example deferred history jobs).",
            "A stale progress timestamp indicates a suspected stall, not proof that a worker is dead.",
            "Pending jobs and history checkpoints are durable SQL state, not the Celery broker queue depth.",
            "Messages have no last-processed timestamp or job link; outcome counts are cumulative and cannot be attributed to a recent scan.",
            "Unsupported/unrecognized means strong flight evidence yielded no segments; it does not prove that the source contains a complete itinerary.",
            "Carrier counts are distinct carriers per message from stored structured evidence; multi-carrier messages appear more than once.",
            "Parser timings and tier counters exist only in task results/log output, not these SQL records; phase latency is unavailable."]}


def render_scan_health(report):
    lines = [f"Flight scan health — {report['generated_at']}",
             "Attention required: " + ("yes" if report['attention_required'] else "no"),
             f"Jobs: {report['jobs']['total']} " + json_counts(report['jobs']['by_state'])]
    for row in report['jobs']['details']:
        lines.append(f"  {row['job_ref']} account={row['user_id']} {row['state']} "
            f"idle={row['seconds_since_update']}s recorded-span={row['recorded_span_seconds']}s "
            f"scanned={row['scanned_count']} parsed={row['parsed_count']} new-segments={row['inserted_segment_count']} "
            f"{','.join(row['warnings']) or row['failure_category'] or ''}".rstrip())
    if report['jobs']['details_truncated']:
        lines.append("  Job details truncated; aggregate counts include the full selected scope.")
    lines.append("History checkpoints:")
    for row in report['history_checkpoints']:
        lines.append(f"  account={row['user_id']} {row['state']} pending-messages={row['pending_message_count']} "
                     f"attempts={row['attempts']} expired-lease={row['lease_expired']} error={row['error_category']}")
    lines.append(f"Stored message outcomes (cumulative): {report['messages']['total']}")
    lines.extend(f"  {key}: {value}" for key, value in report['messages']['outcomes'].items())
    for dimension in ('by_template', 'by_carrier'):
        lines.append(dimension.replace('_', ' ').capitalize() + ':')
        lines.extend(f"  {key}: {json_counts(value)}" for key, value in report['messages'][dimension].items())
    lines.append("Limits:")
    lines.extend("  " + value for value in report['limitations'])
    return '\n'.join(lines) + '\n'


def json_counts(values):
    return ', '.join(f'{key}={value}' for key, value in values.items()) or 'none'
