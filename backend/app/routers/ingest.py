"""Ingest router: start Gmail import job and query job status."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Message, MessageStatus, SyncJob, User
from ..tasks.import_tasks import run_gmail_import
from .auth import get_current_user

router = APIRouter(prefix="/ingest", tags=["ingest"])


class StartImportResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    job_id: str
    state: str
    scanned_count: int
    parsed_count: int
    segment_count: int
    started_at: Optional[datetime]
    updated_at: Optional[datetime]
    error_message: Optional[str] = None


class UnparsedCandidateOut(BaseModel):
    message_id: int
    provider_msg_id: str
    from_email: Optional[str]
    subject: Optional[str]
    status: str
    parse_version: int
    parse_error: Optional[str]
    parse_evidence: Optional[dict] = None
    created_at: Optional[datetime]


class UnparsedCandidateListResponse(BaseModel):
    total: int
    candidates: list[UnparsedCandidateOut]


@router.post("/gmail/import", response_model=StartImportResponse, status_code=200)
def start_gmail_import(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StartImportResponse:
    """Create a SyncJob record and enqueue a background Gmail import task."""
    job_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    job = SyncJob(
        id=job_id,
        user_id=current_user.id,
        state="pending",
        started_at=now,
        updated_at=now,
    )
    db.add(job)
    db.commit()

    eager_mode = os.getenv("CELERY_TASK_ALWAYS_EAGER", "").lower() in ("1", "true", "yes")
    if eager_mode:
        # In local single-terminal mode, running Celery eagerly inside this
        # request blocks the app from polling until the sync is already done.
        background_tasks.add_task(run_gmail_import.run, job_id=job_id, user_id=current_user.id)
    else:
        run_gmail_import.delay(job_id=job_id, user_id=current_user.id)

    return StartImportResponse(job_id=job_id)


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
def get_job_status(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> JobStatusResponse:
    """Return the current status of a sync job (user can only see their own)."""
    job = (
        db.query(SyncJob)
        .filter(SyncJob.id == job_id, SyncJob.user_id == current_user.id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    return JobStatusResponse(
        job_id=job.id,
        state=job.state,
        scanned_count=job.scanned_count,
        parsed_count=job.parsed_count,
        segment_count=job.segment_count,
        started_at=job.started_at,
        updated_at=job.updated_at,
        error_message=job.error_message,
    )


@router.get("/unparsed-candidates", response_model=UnparsedCandidateListResponse)
def list_unparsed_candidates(
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UnparsedCandidateListResponse:
    """Return flight-like messages that were discovered but not parsed into segments."""
    limit = max(1, min(limit, 250))
    base_query = db.query(Message).filter(
        Message.user_id == current_user.id,
        Message.status == MessageStatus.REVIEW_REQUIRED,
        Message.ignored.is_(False),
    )
    total = base_query.count()
    rows = (
        base_query
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
        .all()
    )
    return UnparsedCandidateListResponse(
        total=total,
        candidates=[
            UnparsedCandidateOut(
                message_id=row.id,
                provider_msg_id=row.provider_msg_id,
                from_email=row.from_email,
                subject=row.subject,
                status=row.status.value,
                parse_version=row.parse_version,
                parse_error=row.parse_error,
                parse_evidence=row.parse_evidence,
                created_at=row.created_at,
            )
            for row in rows
        ],
    )

@router.get("/test-queries")
def test_queries(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Collect v1/v2 query IDs immediately, then parse emails in the background."""
    from app.services.gmail import build_gmail_service, list_messages
    from app.services.flight_query import build_gmail_query as build_v1
    from app.services.flight_query_v2 import build_gmail_queries as build_v2
    from app.services.flight_query_v3 import build_gmail_queries as build_v3
    from app.models import Account
    import sys

    account = db.query(Account).filter(Account.user_id == current_user.id, Account.provider == "google").first()
    if not account:
        raise HTTPException(status_code=400, detail="No Google account found")

    service = build_gmail_service(account.refresh_token_encrypted)
    q_v1 = build_v1()
    q_v2 = build_v2()
    q_v3 = build_v3()

    BOLD  = "\033[1m"
    RESET = "\033[0m"
    GREEN = "\033[92m"
    CYAN  = "\033[96m"
    DIM   = "\033[90m"

    def collect_ids(query, label):
        sys.stdout.write(f"  {DIM}Collecting {label}...{RESET}\n")
        sys.stdout.flush()
        msg_ids = set()
        page_token = None
        while True:
            messages, next_token = list_messages(service, query=query, page_token=page_token)
            for msg in messages:
                msg_ids.add(msg["id"])
            sys.stdout.write(f"\r  {DIM}{label}: {len(msg_ids)} found{RESET}")
            sys.stdout.flush()
            if not next_token:
                break
            page_token = next_token
        print(f"\r  {GREEN}✔ {label}: {len(msg_ids)} emails{RESET}       ")
        return msg_ids

    def collect_query_group(queries, label):
        msg_ids = set()
        for i, query in enumerate(queries, 1):
            msg_ids.update(collect_ids(query, f"{label} {i}/{len(queries)}"))
        return msg_ids

    print(f"\n{BOLD}{'─'*60}{RESET}")
    print(f"{BOLD}  ⚖  v1 vs v2 — collecting IDs…{RESET}")
    v1_ids = collect_ids(q_v1, "v1 Query")
    v2_ids = collect_query_group(q_v2, "v2 Hybrid")
    v3_ids = collect_query_group(q_v3, "v3 Production")
    print(f"{BOLD}  IDs collected — parsing will run in background{RESET}")
    print(f"{BOLD}{'─'*60}{RESET}\n")

    # Snapshot the encrypted token so the background task doesn't need the DB session
    token_enc = account.refresh_token_encrypted
    background_tasks.add_task(_parse_comparison, token_enc, v1_ids, v2_ids)

    return {
        "status": "parsing_in_background",
        "v1_count": len(v1_ids),
        "v2_count": len(v2_ids),
        "v3_count": len(v3_ids),
        "both": len(v1_ids & v2_ids),
        "only_in_v1": len(v1_ids - v2_ids),
        "only_in_v2": len(v2_ids - v1_ids),
        "v1_v3_delta": len(v1_ids ^ v3_ids),
    }


def _parse_comparison(token_enc, v1_ids: set, v2_ids: set) -> None:
    """Background task: fetch + parse every email and print a flight-count comparison."""
    import sys
    from app.services.gmail import (
        build_gmail_service, get_message,
        extract_message_body, extract_attachments, extract_headers,
    )
    from app.services.parser import parse_email

    BOLD  = "\033[1m"
    RESET = "\033[0m"
    GREEN = "\033[92m"
    CYAN  = "\033[96m"
    DIM   = "\033[90m"
    RED   = "\033[91m"

    service = build_gmail_service(token_enc)
    all_ids = v1_ids | v2_ids
    total = len(all_ids)

    print(f"\n{BOLD}{'─'*60}{RESET}")
    print(f"{BOLD}  ⚖  Parsing {total:,} emails for flight extraction…{RESET}")
    print(f"{BOLD}{'─'*60}{RESET}")

    v1_flights = 0
    v2_flights = 0
    errors = 0

    for i, msg_id in enumerate(all_ids, 1):
        try:
            full_msg = get_message(service, msg_id)
            headers = extract_headers(full_msg)
            plain_text, html = extract_message_body(full_msg)
            attachments = extract_attachments(full_msg)
            result = parse_email(
                html=html,
                plain_text=plain_text,
                attachments=attachments,
                user_name="",
                aliases=[],
                received_at=headers.get("date"),
                subject=headers.get("subject"),
                from_email=headers.get("from"),
            )
            has_flight = bool(result.flights)
        except Exception:
            has_flight = False
            errors += 1

        if has_flight:
            if msg_id in v1_ids:
                v1_flights += 1
            if msg_id in v2_ids:
                v2_flights += 1

        if i % 100 == 0 or i == total:
            sys.stdout.write(
                f"\r  {i:,}/{total:,}  |  "
                f"v1 flights: {GREEN}{v1_flights}{RESET}  "
                f"v2 flights: {GREEN}{v2_flights}{RESET}  "
                f"{DIM}errors: {errors}{RESET}   "
            )
            sys.stdout.flush()

    sys.stdout.write("\n")
    winner = "v1" if v1_flights > v2_flights else ("v2" if v2_flights > v1_flights else "tie")

    print(f"\n{BOLD}{'─'*60}{RESET}")
    print(f"{BOLD}  ⚖  Comparison Results{RESET}")
    print(f"{BOLD}{'─'*60}{RESET}")
    print(f"  {'v1 query matched':<28} {len(v1_ids):>6,} emails  →  {GREEN}{v1_flights} flights{RESET}")
    print(f"  {'v2 query matched':<28} {len(v2_ids):>6,} emails  →  {GREEN}{v2_flights} flights{RESET}")
    print(f"  {'Only in v1':<28} {len(v1_ids - v2_ids):>6,} emails")
    print(f"  {'Only in v2':<28} {len(v2_ids - v1_ids):>6,} emails")
    print(f"  {DIM}Parse errors: {errors}{RESET}")
    print(f"\n  {BOLD}Winner: {CYAN}{winner}{RESET}")
    print(f"{BOLD}{'─'*60}{RESET}\n")
