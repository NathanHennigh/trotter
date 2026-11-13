"""Bounded, once-per-revision recovery of affected stored flight templates.

No global parser invalidation, mailbox search, or new user-facing retry flow.
Eligibility is template metadata, never a particular account or message ID.
"""
from __future__ import annotations

from email.utils import getaddresses
import re
import time

from sqlalchemy import BigInteger, String, and_, case, cast, func, or_

from .flight_import_rollout import enabled

VERSION = 1
CONTEXTUAL_GROUPING_VERSION = 1
MARKER = "flight_template_recovery"
MAX_PER_SCAN = 25
MAX_METADATA_PER_SCAN = 100
DOMAINS = ("southwest.com", "united.com", "delta.com", "alaskaair.com", "allegiantair.com", "allegiant.com",
           "suncountry.com", "expedia.com", "expediamail.com", "aexp.com", "amextravel.com", "americanexpress.com",
           "flyfrontier.com", "emirates.com", "aeromexico.com")
SUBJECT = re.compile(r"\b(?:confirmation|confirmations|confirmed|itinerary|flight|flights|trip|travel|reservation|cancelled|canceled|cancellation|check.in)\b", re.I)
SOUTHWEST_BOOKED_SUBJECT = re.compile(
    r"^\s*You['’]re going to [^\r\n]{2,80}? on \d{2}/\d{2} \([A-Z0-9]{5,8}\)!?\s*$", re.I)
PRICELINE_BOOKED_SUBJECT = re.compile(
    r"^(?:(?:Re|Fw|Fwd):\s*){0,4}Your priceline itinerary for [^\r\n]{2,120}?\s*-\s*"
    r"(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+"
    r"\d{1,2},\s+\d{4}\s+\(Itinerary\s*#\s*\d{3}-\d{3}-\d{3}-\d{2}\)\s*$", re.I)
FORWARDED_EMIRATES_CHECKIN_SUBJECT = re.compile(
    r"^(?:(?:Re|Fw|Fwd):\s*){1,4}Check in online for your flight EK\d{1,4} on "
    r"(?:0?[1-9]|[12]\d|3[01]) (?:January|February|March|April|May|June|July|August|September|October|November|December)$", re.I)
_FORWARD = re.compile(r"^(?:(?:re|fw|fwd):\s*){1,4}", re.I)
_STUDENT_ORDER = re.compile(
    r"Your StudentUniverse Order\s*-\s*(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(?:0?[1-9]|[12]\d|3[01]),\s+\d{4}", re.I)
_LIFEMILES_REDEMPTION = re.compile(r"You['’]ve redeemed lifemiles!", re.I)
_CAPITAL_ONE_DETAILS = re.compile(r"View your flight details for your [^\r\n]{1,90} trip", re.I)
_CAPITAL_ONE_CONFIRMATION = re.compile(r"View your Capital One Travel Confirmation", re.I)
_AGENCY_HEADINGS = ("your studentuniverse order", "ve redeemed lifemiles!", "view your flight details for your ",
                    "view your capital one travel confirmation", "expedia flight purchase confirmation")
AGENCY_RECEIPT_VERSION = 1


def _agency_receipt(subject, domain):
    title = _FORWARD.sub("", subject, count=1)
    forwarded = title != subject
    if _STUDENT_ORDER.fullmatch(title):
        provider = "studentuniverse.com"
    elif _LIFEMILES_REDEMPTION.fullmatch(title):
        provider = "lifemiles.com"
    elif _CAPITAL_ONE_DETAILS.fullmatch(title):
        provider = "capitalonebooking.com"
    elif _CAPITAL_ONE_CONFIRMATION.fullmatch(title):
        provider = "capitalonebooking.com"
    else:
        return False
    return forwarded or domain == provider or domain.endswith("." + provider)
NOISE = re.compile(r"\b(?:newsletter|statement|award sale|fare sale|deal alert|points offer|bonus miles|credit card offer)\b", re.I)
AMEX_PROFILE_NOTICE = re.compile(
    r"^(?:Confirmation of (?:your )?(?:email address (?:update|change)|Voice ID enrollment)"
    r"|Your AutoPay changes are confirmed|Your \$[0-9,.]+ [^\r\n]{1,80} Credit enrollment confirmation"
    r"|Your Amex Offer expires\b.*)$", re.I)
CAMPAIGN_SUBJECT = re.compile(
    r"^(?:Made to Travel:|Your One Key monthly check-in\b|(?:Last-minute |New )?Flight deals?\b"
    r"|Don['’]t miss another flight deal\b|(?:Now boarding:\s*)?(?:Roundtrip )?Flights under \$\d+\b"
    r"|Book (?:a flight, earn|your entire trip)\b|Every trip\. Every detail\. All in one place\."
    r"|Bundle your trip for bigger savings\b|Get your flights for \$\d+ or less\b"
    r"|Enter for the chance to win a trip\b|(?:Last-minute .{0,30})?travel sale\b"
    r"|(?:Plans can change: Find hotels|Choose a hotel) with free cancellation\b)", re.I)
CAMPAIGN_PRICE = re.compile(
    r"\b(?:flights under \$\d+|your flight .{0,60}could be under \$\d+|our biggest travel event of the year"
    r"|Save up to \d+% when you bundle your flight and hotel)\b", re.I)


def eligible(subject, sender):
    addresses = getaddresses([sender or ""])
    if len(addresses) != 1 or "@" not in addresses[0][1]:
        return False
    local, domain = addresses[0][1].rsplit("@", 1)
    if not local or not domain or "@" in local:
        return False
    domain = domain.lower()
    subject = (subject or "").strip()
    if _agency_receipt(subject, domain):
        return True
    # These explicit account-setting and campaign subjects are distinct from
    # booking confirmations. Do not veto a whole sender or generic "confirmation".
    if ((domain == "americanexpress.com" or domain.endswith(".americanexpress.com"))
            and AMEX_PROFILE_NOTICE.fullmatch(subject)) or CAMPAIGN_SUBJECT.search(subject) or CAMPAIGN_PRICE.search(subject):
        return False
    subject_matches = bool(SUBJECT.search(subject or "")) or (
        (domain == "southwest.com" or domain.endswith(".southwest.com"))
        and bool(SOUTHWEST_BOOKED_SUBJECT.fullmatch(subject or "")))
    # Forwarded transactional receipts retain their exact dated itinerary
    # subject, but their sender is the forwarder. This only admits a bounded
    # source read; the dated card and ticket roster still prove every fact.
    sender_or_forwarded_receipt = (any(domain == target or domain.endswith("." + target) for target in DOMAINS)
                                  or bool(PRICELINE_BOOKED_SUBJECT.fullmatch(subject))
                                  or bool(FORWARDED_EMIRATES_CHECKIN_SUBJECT.fullmatch(subject)))
    return (sender_or_forwarded_receipt
            and subject_matches and not NOISE.search(subject or ""))


def active(user_id):
    return enabled("BOOKING_STRICT_ENRICHMENT_ENABLED", user_id)


def current(evidence):
    marker = evidence.get(MARKER) if isinstance(evidence, dict) else None
    return (isinstance(marker, dict) and type(marker.get("version")) is int
            and marker["version"] == VERSION and marker.get("completed") is True)


def feature_versions(user_id):
    """Only mark hooks that were enabled for this account and actually ran."""
    versions = {}
    # Completion under one switch must not claim a different, disabled hook.
    # Enabling a hook later revisits already-indexed sources once via both the
    # SQL selector and the ordinary cached-message check; disabling it never
    # invalidates a completed source or erases retained evidence.
    if enabled("BOOKING_LEG_RECONCILIATION_ENABLED", user_id):
        from .booking_ticket_lifecycle import VERSION as leg_version
        versions["leg_reconciliation_version"] = leg_version
    if enabled("BOOKING_CONTEXTUAL_TRIP_GROUPING_ENABLED", user_id):
        versions["contextual_grouping_version"] = CONTEXTUAL_GROUPING_VERSION
    if enabled("CARRIER_TRAVEL_CORROBORATION_ENABLED", user_id):
        from .partial_airline_evidence import VERSION as partial_version
        from .carrier_travel_evidence import EVIDENCE_VERSION as carrier_version
        versions.update(partial_evidence_version=partial_version, carrier_evidence_version=carrier_version)
    return versions


def completed_marker(user_id):
    return {"version": VERSION, "completed": True, "agency_receipt_version": AGENCY_RECEIPT_VERSION,
            **feature_versions(user_id)}


def current_for_user(evidence, user_id, *, subject=""):
    if not current(evidence):
        return False
    marker = evidence[MARKER]
    if any(heading in (subject or "").lower() for heading in _AGENCY_HEADINGS):
        version = marker.get("agency_receipt_version")
        if type(version) is not int or version != AGENCY_RECEIPT_VERSION:
            return False
    return all(type(marker.get(key)) is int and marker[key] == version
               for key, version in feature_versions(user_id).items())


def needs_recovery(row):
    return (active(row.user_id) and eligible(row.subject, row.from_email)
            and not current_for_user(row.parse_evidence, row.user_id, subject=row.subject)
            and not unavailable_or_waiting(row.parse_evidence))


def unavailable_or_waiting(evidence, *, now=None):
    evidence = evidence if isinstance(evidence, dict) else {}
    if evidence.get("source_fetch_status") == "gmail_404":
        return "source_no_longer_available"
    retry = evidence.get("template_fetch_retry")
    if isinstance(retry, dict) and type(retry.get("version")) is int and retry["version"] == VERSION:
        after = retry.get("after_epoch")
        if type(after) is int and 0 <= after <= 253402300799 and after > (time.time() if now is None else now):
            return "template_source_retry_backoff"
    return None


def record_fetch_failure(row, *, not_found=False, now=None):
    """Keep all prior evidence. Only an explicit provider 404 is terminal."""
    if row is None:
        return
    evidence = dict(row.parse_evidence) if isinstance(row.parse_evidence, dict) else {}
    if not_found:
        evidence["source_fetch_status"] = "gmail_404"
    elif active(row.user_id) and eligible(row.subject, row.from_email):
        prior = evidence.get("template_fetch_retry")
        attempts = prior.get("attempts") if isinstance(prior, dict) and prior.get("version") == VERSION else 0
        attempts = min(8, max(0, attempts) + 1) if type(attempts) is int else 1
        evidence["template_fetch_retry"] = {"version": VERSION, "attempts": attempts,
            "after_epoch": int(time.time() if now is None else now) + min(3600, 60 * 2 ** (attempts - 1))}
    row.parse_evidence = evidence


def _json_scalar(db, *path):
    """Return a scalar and its JSON type on the supported database dialects."""
    from ..models import Message
    value = Message.parse_evidence
    for key in path:
        value = value[key]
    if db.get_bind().dialect.name == "postgresql":
        kind = func.json_typeof(value)
    else:
        kind = func.json_type(Message.parse_evidence, "$." + ".".join(path))
    return value, kind


def _json_integer(db, *path):
    # Guard casts inside CASE. Malformed legacy JSON must neither abort a scan
    # on PostgreSQL nor impersonate a completed feature marker on SQLite.
    value, kind = _json_scalar(db, *path)
    text = cast(value.as_string(), String)
    nondigits = text
    for digit in "0123456789":
        nondigits = func.replace(nondigits, digit, "")
    valid = and_(kind.in_(("integer", "number")), func.length(text).between(1, 12), nondigits == "")
    return case((valid, cast(text, BigInteger)), else_=0)


def source_available_filter(db, *, include_backoff=True):
    from ..models import Message
    available = func.coalesce(Message.parse_evidence["source_fetch_status"].as_string(), "") != "gmail_404"
    if not include_backoff:
        return available
    after = _json_integer(db, "template_fetch_retry", "after_epoch")
    waiting = and_(_json_integer(db, "template_fetch_retry", "version") == VERSION,
                   after <= 253402300799, after > int(time.time()))
    return and_(available, ~waiting)


def select_messages(db, user_id, limit=MAX_PER_SCAN):
    from ..models import Message, MessageStatus
    if limit <= 0 or not active(user_id):
        return []
    # Marker exclusion occurs in SQL before the bounded metadata read, avoiding
    # starvation behind messages that were already assessed on earlier scans.
    completed, completed_kind = _json_scalar(db, MARKER, "completed")
    is_complete = and_(completed_kind.in_(("boolean", "true")),
                       cast(completed.as_string(), String).in_(("true", "1")))
    needs_version = or_(_json_integer(db, MARKER, "version") != VERSION,
        ~func.coalesce(is_complete, False),
        *(_json_integer(db, MARKER, key) != version for key, version in feature_versions(user_id).items()))
    standard_metadata = and_(
        or_(*(Message.from_email.ilike("%@%" + domain + "%") for domain in DOMAINS),
            Message.subject.ilike("%your priceline itinerary for %(itinerary%"),
            Message.subject.ilike("%check in online for your flight EK% on %")),
        or_(*(Message.subject.ilike("%" + word + "%") for word in ("confirmation", "itinerary", "flight", "trip", "travel", "reservation", "cancel", "check", "going to"))))
    # Include the receipt headings even through a forwarding address. The exact
    # provider/subject check above still runs before any original is fetched.
    agency_metadata = or_(*(Message.subject.ilike("%" + heading + "%") for heading in _AGENCY_HEADINGS))
    stale_agency_rules = and_(agency_metadata,
        _json_integer(db, MARKER, "agency_receipt_version") != AGENCY_RECEIPT_VERSION)
    query = db.query(Message).filter(Message.user_id == user_id,
        Message.status != MessageStatus.PENDING,
        source_available_filter(db),
        or_(_json_integer(db, MARKER, "screened_out_version") != VERSION, stale_agency_rules),
        or_(needs_version, stale_agency_rules),
        or_(standard_metadata, agency_metadata))
    # Bound metadata work too. Record only an explicit metadata-screening marker
    # on nonmatching rows so a page of newsletters cannot starve later sources.
    # This is called under the worker's account lock and commits with the job.
    result = []
    for row in query.order_by(Message.id.asc()).limit(MAX_METADATA_PER_SCAN).all():
        if needs_recovery(row):
            result.append(row)
            if len(result) >= min(limit, MAX_PER_SCAN):
                break
        elif not eligible(row.subject, row.from_email):
            evidence = row.parse_evidence if isinstance(row.parse_evidence, dict) else {}
            row.parse_evidence = {**evidence, MARKER: {
                "screened_out_version": VERSION, "reason": "outside_template_metadata",
                "agency_receipt_version": AGENCY_RECEIPT_VERSION}}
    return result
