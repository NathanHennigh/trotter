"""Synthetic sources shared by extraction and real-import acceptance tests."""
import base64
from copy import deepcopy
from datetime import datetime
from email.utils import format_datetime, parseaddr
from html import escape
import json
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "carrier-corroboration-cases.json"


def fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def source(key):
    return next(deepcopy(value) for value in fixture()["messages"] if value["id"] == key)


def gmail_message(value, *, authentication=True, recipient="maya@example.test", html=False):
    """Build the same original-message boundary used by the preparation worker.

    Trust comes from a Google receiver authentication header, never a name or
    authentication-looking string placed inside the message body.
    """
    received = datetime.fromisoformat(value["received_at"].replace("Z", "+00:00"))
    domain = parseaddr(value["sender"])[1].rsplit("@", 1)[-1]
    dmarc_domain = "aa.com" if domain.endswith(".aa.com") else domain
    headers = [
        {"name": "From", "value": value["sender"]},
        {"name": "To", "value": recipient},
        {"name": "Delivered-To", "value": recipient},
        {"name": "Subject", "value": value["subject"]},
        {"name": "Date", "value": format_datetime(received)},
    ]
    if authentication:
        result = (f"mx.google.com; dkim=pass header.i=@{domain} header.s=fixture; "
                  f"dmarc=pass (p=REJECT sp=REJECT dis=NONE) header.from={dmarc_domain}")
        headers.append({"name": "Authentication-Results", "value": result})
    text = value["text"]
    mime = "text/plain"
    if html:
        text = "<html><body>" + "".join(f"<div>{escape(line)}</div>" for line in text.splitlines()) + "</body></html>"
        mime = "text/html"
    return {
        "id": value["id"],
        "threadId": value["id"],
        "internalDate": str(int(received.timestamp() * 1000)),
        "snippet": value["subject"],
        "payload": {"mimeType": mime, "headers": headers,
                    "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()}},
    }
