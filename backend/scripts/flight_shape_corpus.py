r"""Build a local redacted source-email corpus for parser shape analysis.

The flight audit JSON already links parser output to Gmail message ids. This
script follows those ids back to source emails, writes redacted local copies
under an ignored directory, and renders a small shape report that is useful
before adding new parser special cases.

Usage:
    cd backend
    python scripts/flight_shape_corpus.py --download
    python scripts/flight_shape_corpus.py --download --reference-export ..\trotter-parser-test-data-20260526-134009\cataloged_flights_export.json
    python scripts/flight_shape_corpus.py --report
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(".env")
sys.path.insert(0, os.getcwd())

from app.services.gmail import (  # noqa: E402
    build_gmail_service,
    extract_attachments,
    extract_headers,
    extract_message_body,
    get_message,
)
from app.db import SessionLocal  # noqa: E402
from app.models import Account, User  # noqa: E402


SCRIPT_DIR = Path(__file__).resolve().parent
CORPUS_DIR = SCRIPT_DIR / ".flight_shape_corpus"
MESSAGES_DIR = CORPUS_DIR / "messages"
MANIFEST_PATH = CORPUS_DIR / "manifest.json"
REPORT_PATH = CORPUS_DIR / "shape_report.md"
AUDIT_PATHS = [
    SCRIPT_DIR / "flight_ai_audit_results.json",
    SCRIPT_DIR / "flight_ai_audit_results.travel.json",
    SCRIPT_DIR / "flight_ai_audit_results.strong-nontravel.json",
]

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_URL_RE = re.compile(r"https?://\S+|www\.[^\s<>\"]+", re.IGNORECASE)
_PHONE_RE = re.compile(
    r"""
    (?:\+\d[\d \-().]{6,}\d)
    |
    (?:\(\d{2,4}\)[\s\-.]?\d{2,4}[\s\-.]?\d{2,4}\b)
    |
    \b\d{3}[\s.\-]\d{3}[\s.\-]\d{4}\b
    |
    \b1[\s\-]\d{3}[\s\-]\d{3}[\s\-]\d{4}\b
    """,
    re.VERBOSE,
)
_LONG_DIGITS_RE = re.compile(r"\b\d{12,}\b")
_FORWARDED_RE = re.compile(r"\b(?:fwd|fw):|forwarded message", re.IGNORECASE)
_OTA_DOMAINS = {
    "capitalone.com",
    "cheapoair.com",
    "expedia.com",
    "justfly.com",
    "kiwi.com",
    "priceline.com",
    "trip.com",
}
_INVALID_PNRS = {
    "AGENT",
    "BEFORE",
    "BOARDING",
    "BOOKING",
    "CODES",
    "CONGRATS",
    "DETAILS",
    "DISPLAY",
    "EMAIL",
    "FINAL",
    "LETTER",
    "MANAGED",
    "NUMBER",
    "NUMBERS",
    "POLICY",
    "PORTAL",
    "PRINT",
    "PROVIDED",
    "ROOMTYPE",
    "SECTION",
    "SOURCE",
    "STARTS",
    "STATUS",
    "THROUGH",
    "WITHIN",
    "WITHOUT",
}


def collect_parser_sources() -> dict[str, dict[str, Any]]:
    """Return audit parser-PNR source rows keyed by Gmail message id."""
    sources: dict[str, dict[str, Any]] = {}
    for path in AUDIT_PATHS:
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for message_id, row in (payload.get("scanned") or {}).items():
            if not isinstance(row, dict):
                continue
            pnrs = {
                pnr
                for flight in row.get("parser_flights") or []
                if (pnr := _normal_pnr((flight or {}).get("pnr")))
            }
            if not pnrs:
                continue
            source = sources.setdefault(
                message_id,
                {
                    "message_id": message_id,
                    "pnrs": set(),
                    "audit_paths": set(),
                    "audit_buckets": set(),
                    "subjects": set(),
                    "sender_domains": set(),
                    "parser_flights": [],
                },
            )
            source["pnrs"].update(pnrs)
            source["audit_paths"].add(path.name)
            source["audit_buckets"].add(row.get("audit_bucket") or "unknown")
            source["subjects"].add(row.get("subject") or "")
            source["sender_domains"].add(row.get("sender_domain") or "")
            source["parser_flights"].extend(row.get("parser_flights") or [])
    return sources


def collect_reference_sources(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Map cataloged segments back to accepted source message timestamps."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    messages_by_ts = {
        _normal_timestamp(row.get("internal_ts")): row
        for row in payload.get("messages") or []
        if row.get("provider_msg_id") and row.get("internal_ts")
    }
    sources: dict[str, dict[str, Any]] = {}
    catalog_pnrs: set[str] = set()
    invalid_pnrs: Counter = Counter()
    unmatched_pnrs: set[str] = set()
    for segment in payload.get("segments") or []:
        raw_pnr = segment.get("pnr")
        pnr = _normal_pnr(raw_pnr)
        if not pnr:
            if raw_pnr:
                invalid_pnrs[str(raw_pnr).upper()] += 1
            continue
        catalog_pnrs.add(pnr)
        source_ts = ((segment.get("meta_json") or {}).get("source_received_at") if isinstance(segment.get("meta_json"), dict) else None)
        message = messages_by_ts.get(_normal_timestamp(source_ts))
        if not message:
            unmatched_pnrs.add(pnr)
            continue
        message_id = message["provider_msg_id"]
        source = sources.setdefault(
            message_id,
            {
                "message_id": message_id,
                "pnrs": set(),
                "audit_paths": set(),
                "audit_buckets": set(),
                "subjects": set(),
                "sender_domains": set(),
                "parser_flights": [],
            },
        )
        source["pnrs"].add(pnr)
        source["audit_paths"].add(path.name)
        source["audit_buckets"].add("catalog_reference")
        source["subjects"].add(message.get("subject") or "")
        source["sender_domains"].add(_sender_domain(message.get("from_email") or ""))
        source["parser_flights"].append(
            {
                "airline": segment.get("airline"),
                "flight_number": segment.get("flight_number"),
                "dep_airport": segment.get("dep_airport"),
                "arr_airport": segment.get("arr_airport"),
                "dep_time": segment.get("dep_time"),
                "arr_time": segment.get("arr_time"),
                "pnr": pnr,
                "source": "catalog_reference",
            }
        )
    summary = {
        "path": str(path),
        "segments": len(payload.get("segments") or []),
        "trips": len(payload.get("trips") or []),
        "valid_pnrs": sorted(catalog_pnrs),
        "invalid_pnrs": dict(invalid_pnrs),
        "source_message_count": len(sources),
        "unmatched_pnrs": sorted(unmatched_pnrs),
    }
    return sources, summary


def download_corpus(
    *,
    limit: int | None = None,
    user_email: str | None = None,
    reference_export: Path | None = None,
) -> dict[str, Any]:
    audit_sources = collect_parser_sources()
    sources = dict(audit_sources)
    reference_summary = None
    if reference_export:
        reference_sources, reference_summary = collect_reference_sources(reference_export)
        _merge_sources(sources, reference_sources)
    token = _get_token(user_email=user_email)
    if not token:
        raise RuntimeError("No Google refresh token found in backend/trotter.db.")
    service = build_gmail_service(token)

    MESSAGES_DIR.mkdir(parents=True, exist_ok=True)
    records = []
    errors = []
    ordered_sources = list(sorted(sources.values(), key=lambda item: item["message_id"]))
    if limit:
        ordered_sources = ordered_sources[:limit]

    for index, source in enumerate(ordered_sources, 1):
        message_id = source["message_id"]
        target = MESSAGES_DIR / f"{message_id}.json"
        try:
            if target.exists():
                payload = json.loads(target.read_text(encoding="utf-8"))
            else:
                payload = _fetch_redacted_message(service, message_id)
                target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
            records.append(_manifest_record(source, payload, target))
            print(f"{index:>4}/{len(ordered_sources)} {message_id} {records[-1]['sender_domain']} {records[-1]['shape']}")
        except Exception as exc:  # noqa: BLE001
            errors.append({"message_id": message_id, "error": f"{type(exc).__name__}: {exc}"})
            print(f"{index:>4}/{len(ordered_sources)} {message_id} ERROR {type(exc).__name__}: {exc}")

    manifest = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "audit_paths": [str(path) for path in AUDIT_PATHS if path.exists()],
        "reference_catalog": reference_summary,
        "source_message_count": len(sources),
        "downloaded_message_count": len(records),
        "audit_parser_pnr_count": len({pnr for item in audit_sources.values() for pnr in item["pnrs"]}),
        "parser_pnr_count": len({pnr for item in sources.values() for pnr in item["pnrs"]}),
        "downloaded_pnr_count": len({pnr for record in records for pnr in record["pnrs"]}),
        "records": records,
        "errors": errors,
    }
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    REPORT_PATH.write_text(render_shape_report(manifest), encoding="utf-8")
    return manifest


def render_shape_report(manifest: dict[str, Any]) -> str:
    records = manifest.get("records") or []
    shapes = Counter(record.get("shape") or "unknown" for record in records)
    senders = Counter(record.get("sender_domain") or "unknown" for record in records)
    shape_senders: dict[str, Counter] = defaultdict(Counter)
    shape_examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        shape = record.get("shape") or "unknown"
        shape_senders[shape][record.get("sender_domain") or "unknown"] += 1
        if len(shape_examples[shape]) < 5:
            shape_examples[shape].append(record)

    reference = manifest.get("reference_catalog") or {}
    downloaded_pnrs = {pnr for record in records for pnr in record.get("pnrs") or []}
    reference_pnrs = set(reference.get("valid_pnrs") or [])
    lines = [
        "# Flight Parser Shape Corpus",
        "",
        f"- Source Gmail messages mapped for corpus: {manifest.get('source_message_count', 0)}",
        f"- Downloaded redacted source messages: {manifest.get('downloaded_message_count', 0)}",
        f"- Parser PNRs mapped from audit: {manifest.get('audit_parser_pnr_count', manifest.get('parser_pnr_count', 0))}",
        f"- Parser PNRs represented in downloaded corpus: {manifest.get('downloaded_pnr_count', 0)}",
        f"- Download errors: {len(manifest.get('errors') or [])}",
        "",
    ]
    if reference:
        lines.extend(
            [
                "## Catalog Reference",
                "",
                f"- Catalog segments: {reference.get('segments', 0)}",
                f"- Catalog trips: {reference.get('trips', 0)}",
                f"- Catalog valid PNRs: {len(reference_pnrs)}",
                f"- Catalog PNRs represented in corpus: {len(reference_pnrs & downloaded_pnrs)}",
                f"- Catalog PNRs missing from corpus: {len(reference_pnrs - downloaded_pnrs)}",
                f"- Corpus PNRs not in catalog: {len(downloaded_pnrs - reference_pnrs)}",
                f"- Catalog invalid PNR-like values: {json.dumps(reference.get('invalid_pnrs') or {}, sort_keys=True)}",
            ]
        )
        missing = sorted(reference_pnrs - downloaded_pnrs)
        extras = sorted(downloaded_pnrs - reference_pnrs)
        if missing:
            lines.append(f"- Missing catalog PNRs: {', '.join(missing)}")
        if extras:
            lines.append(f"- Corpus-only PNRs: {', '.join(extras[:30])}{' ...' if len(extras) > 30 else ''}")
        if reference.get("unmatched_pnrs"):
            lines.append(f"- Catalog PNRs without source-message timestamp match: {', '.join(reference['unmatched_pnrs'])}")
        lines.append("")
    lines.extend(["## Shape Families", ""])
    for shape, count in shapes.most_common():
        lines.append(f"### {shape} ({count})")
        lines.append("")
        top_senders = ", ".join(
            f"{sender}={count}" for sender, count in shape_senders[shape].most_common(6)
        )
        lines.append(f"- Top senders: {top_senders or '-'}")
        for record in shape_examples[shape]:
            pnrs = ",".join(record.get("pnrs") or [])
            lines.append(
                f"- `{record['message_id']}` `{record.get('sender_domain') or '-'}` "
                f"PNR={pnrs or '-'} subject={_safe_inline(record.get('subject') or '')}"
            )
        lines.append("")
    lines.extend(["## Top Sender Domains", ""])
    for sender, count in senders.most_common(20):
        lines.append(f"- `{sender}`: {count}")
    return "\n".join(lines) + "\n"


def attach_reference_summary(manifest: dict[str, Any], reference_export: Path) -> dict[str, Any]:
    """Attach reference comparison without fetching any additional Gmail messages."""
    _, reference = collect_reference_sources(reference_export)
    records = manifest.get("records") or []
    downloaded_pnrs = {pnr for record in records for pnr in record.get("pnrs") or []}
    reference_pnrs = set(reference.get("valid_pnrs") or [])
    reference["represented_pnrs"] = sorted(reference_pnrs & downloaded_pnrs)
    reference["missing_pnrs"] = sorted(reference_pnrs - downloaded_pnrs)
    reference["corpus_only_pnrs"] = sorted(downloaded_pnrs - reference_pnrs)
    return {**manifest, "reference_catalog": reference}


def load_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        raise RuntimeError(f"Corpus manifest not found: {MANIFEST_PATH}. Run with --download first.")
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _fetch_redacted_message(service, message_id: str) -> dict[str, Any]:
    message = get_message(service, message_id)
    headers = extract_headers(message)
    plain_text, html = extract_message_body(message)
    attachments = extract_attachments(message)
    sender = headers.get("from") or ""
    return {
        "message_id": message_id,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "date": headers.get("date") or "",
        "from": _redact(sender),
        "sender_domain": _sender_domain(sender),
        "subject": _redact(headers.get("subject") or ""),
        "plain_text": _redact(plain_text),
        "html": _redact(html),
        "attachment_filenames": [_redact(item.get("filename") or "") for item in attachments],
    }


def _manifest_record(source: dict[str, Any], payload: dict[str, Any], target: Path) -> dict[str, Any]:
    body = "\n".join([payload.get("subject") or "", payload.get("plain_text") or "", payload.get("html") or ""])
    sender_domain = payload.get("sender_domain") or next(iter(source["sender_domains"]), "")
    return {
        "message_id": source["message_id"],
        "pnrs": sorted(source["pnrs"]),
        "audit_paths": sorted(source["audit_paths"]),
        "audit_buckets": sorted(source["audit_buckets"]),
        "sender_domain": sender_domain,
        "subject": payload.get("subject") or next(iter(source["subjects"]), ""),
        "message_path": str(target.relative_to(CORPUS_DIR)),
        "shape": classify_shape(subject=payload.get("subject") or "", sender_domain=sender_domain, body=body),
        "attachment_count": len(payload.get("attachment_filenames") or []),
        "parser_flight_count": len(source.get("parser_flights") or []),
    }


def _merge_sources(target: dict[str, dict[str, Any]], incoming: dict[str, dict[str, Any]]) -> None:
    for message_id, source in incoming.items():
        existing = target.setdefault(message_id, source)
        if existing is source:
            continue
        existing["pnrs"].update(source["pnrs"])
        existing["audit_paths"].update(source["audit_paths"])
        existing["audit_buckets"].update(source["audit_buckets"])
        existing["subjects"].update(source["subjects"])
        existing["sender_domains"].update(source["sender_domains"])
        existing["parser_flights"].extend(source["parser_flights"])


def classify_shape(*, subject: str, sender_domain: str, body: str) -> str:
    subject_text = (subject or "").lower()
    text = f"{subject}\n{body}".lower()
    sender_root = ".".join((sender_domain or "").lower().split(".")[-2:])
    if _FORWARDED_RE.search(subject or ""):
        return "forwarded_message"
    if "boarding pass" in text or "boarding document" in text or "mobile boarding" in text:
        return "boarding_pass"
    if any(term in text for term in ("schedule change", "flight change", "flight update", "gate change", "delayed")):
        return "change_notice"
    if any(term in subject_text for term in ("cancel", "cancellation", "refund")) or "reservation has been canceled" in text:
        return "cancellation_or_refund"
    if "check in" in text or "check-in" in text or "upcoming trip" in text or "time to check" in text:
        return "checkin_or_reminder"
    if sender_root in _OTA_DOMAINS or "travel confirmation" in text and "airline confirmation" in text:
        return "ota_confirmation"
    if "receipt" in text or "ticket number" in text or "e-ticket" in text or "eticket" in text:
        return "receipt_or_ticket"
    if "itinerary" in text or "flight confirmation" in text or "record locator" in text:
        return "airline_itinerary"
    return "other_parsed_flight"


def _get_token(*, user_email: str | None) -> bytes | None:
    db = SessionLocal()
    try:
        query = db.query(Account).filter(Account.provider == "google")
        if user_email:
            query = query.join(User).filter(User.email == user_email)
        account = query.order_by(Account.id.asc()).first()
        return account.refresh_token_encrypted if account else None
    finally:
        db.close()


def _normal_pnr(value: Any) -> str | None:
    normalized = "".join(str(value or "").upper().split())
    if not (5 <= len(normalized) <= 8):
        return None
    if not normalized.isalnum() or normalized in _INVALID_PNRS:
        return None
    return normalized


def _redact(text: str) -> str:
    value = text or ""
    value = _EMAIL_RE.sub("[email]", value)
    value = _URL_RE.sub("[url]", value)
    value = _PHONE_RE.sub("[phone]", value)
    return _LONG_DIGITS_RE.sub("[digits]", value)


def _sender_domain(sender: str) -> str:
    if "@" not in sender:
        return ""
    return sender.split("@")[-1].rstrip(">").strip().lower()


def _normal_timestamp(value: Any) -> str:
    text = str(value or "")
    return text.replace("T", " ")[:19]


def _safe_inline(value: str) -> str:
    return " ".join((value or "").replace("`", "'").split())[:140]


def _safe_console_write(value: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    sys.stdout.write(value.encode(encoding, errors="replace").decode(encoding))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Fetch redacted source emails from Gmail.")
    parser.add_argument("--report", action="store_true", help="Render a report from the current manifest.")
    parser.add_argument("--limit", type=int, default=None, help="Fetch only the first N audit source messages.")
    parser.add_argument("--user-email", default=None, help="Use this linked Gmail account instead of the first one.")
    parser.add_argument("--reference-export", type=Path, default=None, help="Cataloged flights export to compare and source-map.")
    args = parser.parse_args()

    if args.download:
        manifest = download_corpus(limit=args.limit, user_email=args.user_email, reference_export=args.reference_export)
    else:
        manifest = load_manifest()
        if args.reference_export:
            manifest = attach_reference_summary(manifest, args.reference_export)
    if args.download or args.report:
        report = render_shape_report(manifest)
        REPORT_PATH.write_text(report, encoding="utf-8")
        _safe_console_write(report)
        print(f"Manifest: {MANIFEST_PATH}")
        print(f"Report:   {REPORT_PATH}")
        return
    parser.error("choose --download or --report")


if __name__ == "__main__":
    main()
