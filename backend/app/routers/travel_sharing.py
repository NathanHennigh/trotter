"""Authenticated private travel inbox and explicit recipient acceptance."""
from __future__ import annotations

from uuid import UUID
import json
import os
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from ..services import travel_sharing as sharing
from ..services.import_lock import ImportAlreadyRunning, user_import_lock
from .auth import get_current_user

router = APIRouter(prefix="/travel-sharing", tags=["travel-sharing"])


class AssignmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passenger_name: str = Field(min_length=2, max_length=100)


class ShareIn(AssignmentIn):
    item_ids: list[UUID] = Field(min_length=1, max_length=40)
    recipient_email: str = Field(min_length=3, max_length=255)
    client_request_id: UUID | None = None


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=128)


def _locked_write(db, user, operation):
    try:
        with user_import_lock(db.get_bind(), user.id):
            response = operation()
            db.commit()
            return response
    except ImportAlreadyRunning as exc:
        db.rollback()
        raise HTTPException(409, "A flight import is running. Try again shortly") from exc
    except Exception:
        db.rollback()
        raise


@router.get("/inbox")
def inbox(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return sharing.inbox(db, current_user)


@router.patch("/items/{item_id}")
def assign(item_id: UUID, body: AssignmentIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _locked_write(db, current_user, lambda: sharing.assign(db, current_user, str(item_id), body.passenger_name))


@router.post("")
def create(body: ShareIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _locked_write(db, current_user, lambda: sharing.create_share(db, current_user,
        [str(item_id) for item_id in body.item_ids], body.recipient_email, body.passenger_name,
        str(body.client_request_id) if body.client_request_id else None))


@router.post("/resolve")
def resolve(body: ResolveIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return sharing.share_view(db, sharing.authorized_share(db, current_user, token=body.token))


@router.post("/{share_id}/accept")
def accept(share_id: UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return sharing.accept_share(db, current_user, str(share_id))


@router.post("/{share_id}/decline")
def decline(share_id: UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _locked_write(db, current_user, lambda: sharing.transition(db, current_user, str(share_id), "decline"))


@router.post("/{share_id}/revoke")
def revoke(share_id: UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _locked_write(db, current_user, lambda: sharing.transition(db, current_user, str(share_id), "revoke"))


@router.post("/{share_id}/link")
def link(share_id: UUID, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    share = sharing.authorized_share(db, current_user, str(share_id), role="sender")
    if sharing._share_status(share) != "pending":
        raise HTTPException(409, "This invitation is no longer pending")
    return {"share_url": sharing._share_url(share)}


# No flight details, recipient identities, cookies or analytics on the public
# landing page. The token stays in the fragment, outside request/access logs.
_LANDING = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><title>Flights shared with you · Trotter</title>
<style>body{background:#f8f5eb;color:#214b5e;font:17px system-ui;margin:0;padding:40px 24px}main{max-width:420px;margin:10vh auto}h1{font:42px Georgia;line-height:1.1}p{line-height:1.6}a{display:block;background:#214b5e;color:#fff;padding:16px 20px;text-align:center;text-decoration:none;border-radius:8px;margin:28px 0}small{display:block;color:#586f75;line-height:1.6}[hidden]{display:none}</style></head>
<body><main><p>TROTTER</p><h1>Flights shared with you.</h1><p id="message">Open Trotter to review these flights before adding them to your trips.</p>
<a id="open" hidden>Open Trotter</a><a id="web" hidden>Continue in browser</a><small>Sign in or join with the Google account the sender addressed the invitation to. You can review the flights before accepting. For the Android preview, ask the sender for the current install link.</small></main>
<script>const token=new URLSearchParams(location.hash.slice(1)).get('token');const web=__WEB_APP_URL__;if(token&&/^[A-Za-z0-9_-]{43}$/.test(token)){const a=document.getElementById('open');a.href='trotterv2://flight-share?token='+encodeURIComponent(token);a.hidden=false;if(web){const b=document.getElementById('web');b.href=web+'/#flight-invitation='+encodeURIComponent(token);b.hidden=false;}}else{document.getElementById('message').textContent='This link is incomplete. Ask the sender to share the invitation again.'}</script></body></html>"""


@router.get("/open", response_class=HTMLResponse, include_in_schema=False)
def open_invitation():
    web = os.getenv("WEB_APP_URL", "").rstrip("/")
    parsed = urlparse(web)
    allowed = parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"})
    if not allowed or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        web = ""
    html = _LANDING.replace("__WEB_APP_URL__", json.dumps(web).replace("<", "\\u003c"))
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"})
