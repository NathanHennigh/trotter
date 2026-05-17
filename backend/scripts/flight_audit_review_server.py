"""Local web UI for reviewing flight audit candidates.

This serves only cached audit metadata and safe snippets. It does not fetch or
display raw email bodies.

Usage:
    cd backend
    python scripts/flight_audit_review_server.py
"""

from __future__ import annotations

import json
import mimetypes
import re
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


SCRIPT_DIR = Path(__file__).parent
RESULTS_FILE = SCRIPT_DIR / "flight_ai_audit_results.json"
FEEDBACK_FILE = SCRIPT_DIR / "flight_ai_audit_feedback.json"
REVIEW_QUEUE_FILE = SCRIPT_DIR / "flight_ai_audit_review_queue.md"
HOST = "127.0.0.1"
PORT = 8765

REVIEW_BUCKETS = {
    "likely_flight_parser_missed",
    "likely_flight_discovery_missed",
    "possible_flight_needs_review",
    "duplicate_or_reminder",
    "change_or_cancellation",
}


def load_results() -> dict[str, Any]:
    if not RESULTS_FILE.exists():
        return {"scanned": {}}
    return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))


def load_feedback() -> dict[str, Any]:
    if not FEEDBACK_FILE.exists():
        return import_markdown_feedback()
    try:
        payload = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {"items": {}, "updated_at": None}
    payload.setdefault("items", {})
    markdown_payload = import_markdown_feedback(write_file=False)
    for message_id, item in (markdown_payload.get("items") or {}).items():
        payload["items"].setdefault(message_id, item)
    for item in payload["items"].values():
        if item.get("source") == "markdown_import" and item.get("category"):
            item.setdefault("suggested_category", item.get("category") or "")
            item.setdefault("prior_note", item.get("note") or "")
            item["category"] = ""
            item["note"] = ""
    return payload


def save_feedback(payload: dict[str, Any]) -> None:
    payload["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    FEEDBACK_FILE.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def import_markdown_feedback(*, write_file: bool = True) -> dict[str, Any]:
    payload = {"items": {}, "updated_at": None, "source": "markdown_import"}
    if not REVIEW_QUEUE_FILE.exists() or not RESULTS_FILE.exists():
        return payload

    comments = load_markdown_review_comments()
    if not comments["subjects"] and not comments["senders"]:
        return payload

    for row in (load_results().get("scanned") or {}).values():
        message_id = row.get("message_id") or ""
        subject = row.get("subject") or ""
        sender_domain = row.get("sender_domain") or ""
        notes: list[str] = []
        notes.extend(comments["subjects"].get(subject, []))
        sender_note = comments["senders"].get(sender_domain)
        if sender_note:
            notes.append(sender_note)
        note = " / ".join(dict.fromkeys(part.strip() for part in notes if part.strip()))
        if not message_id or not note:
            continue
        payload["items"][message_id] = {
            "category": "",
            "note": "",
            "prior_note": note,
            "suggested_category": infer_feedback_category(note),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": "markdown_import",
        }

    if write_file and payload["items"]:
        save_feedback(payload)
    return payload


def load_markdown_review_comments() -> dict[str, dict[str, Any]]:
    lines = REVIEW_QUEUE_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    subjects: dict[str, list[str]] = {}
    senders: dict[str, str] = {}
    pending_comments: list[str] = []
    current_sender = ""
    item_re = re.compile(r"^- \[(?P<subject>.+?)\]\(")
    sender_re = re.compile(r"^### (?P<sender>\S+) \(\d+\)(?P<comment>.*)$")
    metadata_re = re.compile(r"^\s+- (?:ai=|snippet:)")

    for line in lines:
        sender_match = sender_re.match(line)
        if sender_match:
            current_sender = sender_match.group("sender")
            comment = sender_match.group("comment").strip()
            if comment:
                senders[current_sender] = comment
            pending_comments = []
            continue

        item_match = item_re.match(line)
        if item_match:
            subject = item_match.group("subject").replace("\\[", "[").replace("\\]", "]")
            if pending_comments:
                subjects.setdefault(subject, pending_comments.copy())
            pending_comments = []
            continue

        if not line.strip() or line.startswith("#") or line.lower().startswith("reviewed:") or metadata_re.match(line):
            continue
        if line.startswith("- "):
            continue
        pending_comments.append(line.strip())

    return {"subjects": subjects, "senders": senders}


def infer_feedback_category(note: str) -> str:
    normalized = note.lower()
    if "airbnb" in normalized:
        return "airbnb"
    if "hotel" in normalized or "stay" in normalized:
        return "hotel"
    if "bus" in normalized or "greyhound" in normalized:
        return "bus"
    if "train" in normalized or "amtrak" in normalized:
        return "train"
    if "car" in normalized or "rental" in normalized:
        return "car"
    if "cancel" in normalized:
        return "cancellation"
    if (
        "schedule change" in normalized
        or "changed" in normalized
        or "change notice" in normalized
        or "flight change" in normalized
    ):
        return "change"
    if "not mine" in normalized or "other people" in normalized:
        return "not_mine"
    if "not relevant" in normalized or "not a flight" in normalized:
        return "not_relevant"
    if "reminder" in normalized and "flight" not in normalized:
        return "reminder"
    if "flight" in normalized or normalized.startswith("yes"):
        return "yes_flight"
    return "unsure"


def gmail_search_url(sender: str, subject: str) -> str:
    from urllib.parse import quote

    sender_domain = sender.split("@")[-1].rstrip(">").strip().lower() if "@" in sender else ""
    terms = []
    if sender_domain:
        terms.append(f"from:{sender_domain}")
    if subject:
        terms.append(f'subject:"{subject.replace(chr(34), " ").strip()}"')
    return "https://mail.google.com/mail/u/0/#search/" + quote(" ".join(terms) if terms else subject)


def review_items() -> list[dict[str, Any]]:
    results = load_results()
    feedback = load_feedback().get("items", {})
    rows = []
    for row in (results.get("scanned") or {}).values():
        bucket = row.get("audit_bucket") or ""
        if bucket not in REVIEW_BUCKETS:
            continue
        ai = row.get("ai") or {}
        parse_miss = row.get("parse_miss") or {}
        message_id = row.get("message_id") or ""
        subject = row.get("subject") or "(no subject)"
        item_feedback = feedback.get(message_id) or {}
        rows.append(
            {
                "message_id": message_id,
                "date": row.get("date") or "",
                "from": row.get("from") or "",
                "sender_domain": row.get("sender_domain") or "unknown",
                "subject": subject,
                "audit_bucket": bucket,
                "ai_label": ai.get("label") or "",
                "ai_confidence": ai.get("confidence"),
                "parse_score": parse_miss.get("score"),
                "detected_airports": ai.get("detected_airports") or [],
                "detected_flight_numbers": ai.get("detected_flight_numbers") or [],
                "safe_snippet": row.get("safe_snippet") or "",
                "gmail_url": gmail_search_url(row.get("from") or "", subject),
                "feedback": item_feedback,
            }
        )
    rows.sort(
        key=lambda item: (
            bool(item.get("feedback", {}).get("category")),
            item["audit_bucket"],
            item["sender_domain"],
            item["subject"],
            item["message_id"],
        )
    )
    return rows


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(INDEX_HTML)
            return
        if parsed.path == "/api/items":
            params = parse_qs(parsed.query)
            items = review_items()
            bucket = (params.get("bucket") or [""])[0]
            only_unreviewed = (params.get("unreviewed") or [""])[0] == "1"
            if bucket:
                items = [item for item in items if item["audit_bucket"] == bucket]
            if only_unreviewed:
                items = [item for item in items if not item.get("feedback", {}).get("category")]
            self._send_json({"items": items, "count": len(items)})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path != "/api/feedback":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return
        message_id = str(data.get("message_id") or "")
        if not message_id:
            self.send_error(400, "Missing message_id")
            return
        payload = load_feedback()
        payload.setdefault("items", {})
        payload["items"][message_id] = {
            "category": str(data.get("category") or ""),
            "note": str(data.get("note") or ""),
            "prior_note": str(data.get("prior_note") or (payload["items"].get(message_id) or {}).get("prior_note") or ""),
            "suggested_category": str(
                data.get("suggested_category") or (payload["items"].get(message_id) or {}).get("suggested_category") or ""
            ),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": "ui",
        }
        save_feedback(payload)
        self._send_json({"ok": True, "feedback": payload["items"][message_id]})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.types_map.get(".json", "application/json"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Trotter Flight Audit Review</title>
  <style>
    :root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif; }
    body { margin: 0; background: #f6f7f9; color: #17202a; }
    header { position: sticky; top: 0; z-index: 2; background: #fff; border-bottom: 1px solid #dfe3e8; padding: 14px 20px; }
    h1 { font-size: 18px; margin: 0 0 10px; }
    .bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
    select, input, button, textarea { font: inherit; }
    select, input { border: 1px solid #c9d0d8; border-radius: 6px; padding: 7px 9px; background: #fff; }
    button { border: 1px solid #c9d0d8; background: #fff; border-radius: 6px; padding: 7px 10px; cursor: pointer; }
    button.primary { background: #0f766e; color: white; border-color: #0f766e; }
    main { padding: 18px 20px 36px; max-width: 1200px; margin: 0 auto; }
    .item { background: #fff; border: 1px solid #dfe3e8; border-radius: 8px; padding: 14px; margin-bottom: 12px; }
    .item.reviewed { border-color: #9bd4c9; background: #f3fbf9; }
    .top { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
    .subject { font-weight: 700; font-size: 15px; line-height: 1.3; }
    .meta { margin-top: 6px; color: #52606d; font-size: 12px; }
    .chips { display: flex; gap: 6px; flex-wrap: wrap; margin: 10px 0; }
    .chip { background: #eef2f6; border-radius: 999px; padding: 4px 8px; font-size: 12px; color: #3a4754; }
    .snippet { color: #24313d; line-height: 1.4; font-size: 13px; margin: 8px 0 12px; }
    .actions { display: grid; grid-template-columns: minmax(180px, 240px) 1fr auto; gap: 8px; align-items: start; }
    textarea { min-height: 38px; resize: vertical; border: 1px solid #c9d0d8; border-radius: 6px; padding: 8px; }
    a { color: #0f5e9c; text-decoration: none; }
    .count { color: #52606d; font-size: 13px; }
    .empty { color: #52606d; padding: 40px 0; text-align: center; }
  </style>
</head>
<body>
  <header>
    <h1>Trotter Flight Audit Review</h1>
    <div class="bar">
      <select id="bucket">
        <option value="">All review buckets</option>
        <option value="likely_flight_parser_missed">Parser misses</option>
        <option value="likely_flight_discovery_missed">Discovery misses</option>
        <option value="possible_flight_needs_review">Needs review</option>
        <option value="duplicate_or_reminder">Reminders / boarding links</option>
        <option value="change_or_cancellation">Changes / cancellations</option>
      </select>
      <label><input id="unreviewed" type="checkbox" /> unreviewed only</label>
      <input id="search" placeholder="Search subject, sender, snippet" size="34" />
      <button id="reload">Reload</button>
      <span class="count" id="count"></span>
    </div>
  </header>
  <main id="items"></main>
  <script>
    const categories = [
      ["yes_flight", "YES flight"],
      ["not_mine", "Not mine"],
      ["duplicate", "Duplicate"],
      ["reminder", "Reminder"],
      ["change", "Change"],
      ["cancellation", "Cancellation"],
      ["hotel", "Hotel"],
      ["airbnb", "Airbnb"],
      ["bus", "Bus"],
      ["train", "Train"],
      ["car", "Car"],
      ["not_relevant", "Not relevant"],
      ["needs_parser", "Parser fixture"],
      ["unsure", "Unsure"]
    ];
    let allItems = [];

    async function load() {
      const bucket = document.getElementById("bucket").value;
      const unreviewed = document.getElementById("unreviewed").checked ? "1" : "";
      const params = new URLSearchParams();
      if (bucket) params.set("bucket", bucket);
      if (unreviewed) params.set("unreviewed", "1");
      const res = await fetch("/api/items?" + params.toString());
      const data = await res.json();
      allItems = data.items;
      render();
    }

    function render() {
      const q = document.getElementById("search").value.toLowerCase();
      const items = allItems.filter(item => !q || [item.subject, item.from, item.sender_domain, item.safe_snippet].join(" ").toLowerCase().includes(q));
      document.getElementById("count").textContent = `${items.length} item${items.length === 1 ? "" : "s"}`;
      const root = document.getElementById("items");
      if (!items.length) {
        root.innerHTML = `<div class="empty">No items match this filter.</div>`;
        return;
      }
      root.innerHTML = items.map(item => itemHtml(item)).join("");
      for (const item of items) {
        const category = document.getElementById(`cat-${item.message_id}`);
        const note = document.getElementById(`note-${item.message_id}`);
        const save = document.getElementById(`save-${item.message_id}`);
        save.addEventListener("click", () => saveFeedback(item.message_id, category.value, note.value));
      }
    }

    function itemHtml(item) {
      const feedback = item.feedback || {};
      const categoryOptions = [`<option value="">Choose label</option>`].concat(categories.map(([value, label]) =>
        `<option value="${value}" ${feedback.category === value ? "selected" : ""}>${label}</option>`
      )).join("");
      const reviewed = feedback.category ? " reviewed" : "";
      const airports = (item.detected_airports || []).join(",") || "-";
      const flights = (item.detected_flight_numbers || []).join(",") || "-";
      const prior = feedback.prior_note
        ? `<div class="snippet"><b>Prior note:</b> ${escapeHtml(feedback.prior_note)}${feedback.suggested_category ? ` <span class="chip">suggested ${escapeHtml(feedback.suggested_category)}</span>` : ""}</div>`
        : "";
      return `<section class="item${reviewed}">
        <div class="top">
          <div>
            <div class="subject"><a href="${item.gmail_url}" target="_blank" rel="noreferrer">${escapeHtml(item.subject)}</a></div>
            <div class="meta">${escapeHtml(item.sender_domain)} · ${escapeHtml(item.audit_bucket)} · ${escapeHtml(item.date || "")}</div>
          </div>
          <a href="${item.gmail_url}" target="_blank" rel="noreferrer">Open Gmail</a>
        </div>
        <div class="chips">
          <span class="chip">AI ${escapeHtml(item.ai_label || "-")}/${escapeHtml(String(item.ai_confidence ?? "-"))}</span>
          <span class="chip">score ${escapeHtml(String(item.parse_score ?? "-"))}</span>
          <span class="chip">airports ${escapeHtml(airports)}</span>
          <span class="chip">flights ${escapeHtml(flights)}</span>
        </div>
        <div class="snippet">${escapeHtml(item.safe_snippet)}</div>
        ${prior}
        <div class="actions">
          <select id="cat-${item.message_id}">${categoryOptions}</select>
          <textarea id="note-${item.message_id}" placeholder="Notes for parser improvements">${escapeHtml(feedback.note || "")}</textarea>
          <button class="primary" id="save-${item.message_id}">Save</button>
        </div>
      </section>`;
    }

    async function saveFeedback(message_id, category, note) {
      const item = allItems.find(x => x.message_id === message_id);
      const feedback = item?.feedback || {};
      await fetch("/api/feedback", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
          message_id,
          category,
          note,
          prior_note: feedback.prior_note || "",
          suggested_category: feedback.suggested_category || ""
        })
      });
      if (item) item.feedback = {...feedback, category, note, source: "ui"};
      render();
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, ch => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[ch]));
    }

    document.getElementById("bucket").addEventListener("change", load);
    document.getElementById("unreviewed").addEventListener("change", load);
    document.getElementById("search").addEventListener("input", render);
    document.getElementById("reload").addEventListener("click", load);
    load();
  </script>
</body>
</html>
"""


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"Flight audit review UI running at {url}")
    print(f"Saving feedback to {FEEDBACK_FILE}")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    server.serve_forever()


if __name__ == "__main__":
    main()
