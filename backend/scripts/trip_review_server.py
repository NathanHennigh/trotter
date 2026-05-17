"""Local review UI for trip-organization feedback.

Usage:
    cd backend
    python scripts/trip_review_server.py

The UI reads only the local SQLite trip graph and stores review notes in
``scripts/trip_review_feedback.json``. It does not fetch email bodies.
"""

from __future__ import annotations

import json
import sqlite3
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


SCRIPT_DIR = Path(__file__).parent
BACKEND_DIR = SCRIPT_DIR.parent
DB_PATH = BACKEND_DIR / "trotter.db"
FEEDBACK_FILE = SCRIPT_DIR / "trip_review_feedback.json"
EXPORT_FILE = SCRIPT_DIR / "trip_review_feedback.md"
HOST = "127.0.0.1"
PORT = 8766


def load_feedback() -> dict[str, Any]:
    if not FEEDBACK_FILE.exists():
        return {"trips": {}, "updated_at": None}
    try:
        payload = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        payload = {"trips": {}, "updated_at": None}
    payload.setdefault("trips", {})
    return payload


def save_feedback(payload: dict[str, Any]) -> None:
    payload["updated_at"] = utc_now()
    FEEDBACK_FILE.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def db_rows() -> list[dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    trips = conn.execute(
        """
        SELECT
            t.id,
            t.title,
            t.start_ts,
            t.end_ts,
            COUNT(s.id) AS segment_count
        FROM trips t
        LEFT JOIN segments s ON s.trip_id = t.id
        GROUP BY t.id
        ORDER BY t.start_ts DESC, t.id DESC
        """
    ).fetchall()
    result: list[dict[str, Any]] = []
    for trip in trips:
        segments = conn.execute(
            """
            SELECT
                id,
                dep_airport,
                arr_airport,
                dep_time,
                arr_time,
                airline,
                flight_number,
                pnr
            FROM segments
            WHERE trip_id = ?
            ORDER BY dep_time, arr_time, id
            """,
            (trip["id"],),
        ).fetchall()
        result.append(
            {
                "id": trip["id"],
                "title": trip["title"] or "",
                "start_ts": trip["start_ts"],
                "end_ts": trip["end_ts"],
                "segment_count": trip["segment_count"],
                "segments": [dict(segment) for segment in segments],
            }
        )
    conn.close()
    return result


def review_items() -> list[dict[str, Any]]:
    feedback = load_feedback().get("trips", {})
    rows = db_rows()
    for row in rows:
        row["feedback"] = feedback.get(str(row["id"]), {})
    return rows


def export_markdown() -> None:
    feedback = load_feedback().get("trips", {})
    rows = {str(row["id"]): row for row in db_rows()}
    lines = [
        "# Trip Review Feedback",
        "",
        f"Updated: {utc_now()}",
        "",
    ]
    for trip_id, item in sorted(feedback.items(), key=lambda pair: int(pair[0])):
        row = rows.get(trip_id)
        if not row:
            continue
        lines.append(f"## Trip {trip_id}: {row['title'] or '(untitled)'}")
        lines.append("")
        lines.append(f"- Dates: {row['start_ts']} to {row['end_ts']}")
        lines.append(f"- Current status: {item.get('status') or ''}")
        lines.append(f"- Actual destination/title: {item.get('actual_title') or ''}")
        lines.append(f"- Belongs with trip IDs: {item.get('merge_with') or ''}")
        lines.append(f"- Should split before segment IDs: {item.get('split_before') or ''}")
        lines.append(f"- Missing legs: {item.get('missing_legs') or ''}")
        lines.append(f"- Notes: {item.get('notes') or ''}")
        lines.append("")
        lines.append("Segments:")
        for segment in row["segments"]:
            seg_feedback = (item.get("segments") or {}).get(str(segment["id"]), {})
            route = f"{segment['dep_airport']} -> {segment['arr_airport']}"
            flight = segment["flight_number"] or ""
            label = seg_feedback.get("label") or ""
            note = seg_feedback.get("note") or ""
            lines.append(
                f"- `{segment['id']}` {route} {flight} {segment['dep_time']} | {label} | {note}"
            )
        lines.append("")
    EXPORT_FILE.write_text("\n".join(lines), encoding="utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_html(INDEX_HTML)
            return
        if parsed.path == "/api/trips":
            params = parse_qs(parsed.query)
            only_unreviewed = (params.get("unreviewed") or [""])[0] == "1"
            items = review_items()
            if only_unreviewed:
                items = [item for item in items if not item.get("feedback", {}).get("status")]
            self._send_json({"items": items})
            return
        if parsed.path == "/api/export":
            export_markdown()
            self._send_json({"ok": True, "path": str(EXPORT_FILE)})
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if self.path != "/api/feedback":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            trip_id = str(int(payload["trip_id"]))
        except (ValueError, KeyError, json.JSONDecodeError):
            self.send_error(400)
            return
        feedback = load_feedback()
        item = {
            "status": payload.get("status") or "",
            "actual_title": payload.get("actual_title") or "",
            "merge_with": payload.get("merge_with") or "",
            "split_before": payload.get("split_before") or "",
            "missing_legs": payload.get("missing_legs") or "",
            "notes": payload.get("notes") or "",
            "segments": payload.get("segments") or {},
            "updated_at": utc_now(),
        }
        feedback["trips"][trip_id] = item
        save_feedback(feedback)
        self._send_json({"ok": True, "feedback": item})

    def _send_json(self, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Trotter Trip Review</title>
  <style>
    :root {
      --bg: #f5efe3;
      --panel: #fff9ef;
      --ink: #181512;
      --muted: #6f6559;
      --line: #ddcfb8;
      --accent: #2f5f9f;
      --accent-soft: #e6eef9;
      --warn: #a34c2d;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 15px/1.45 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 10;
      display: flex;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
      padding: 16px 22px;
      border-bottom: 1px solid var(--line);
      background: rgba(245, 239, 227, 0.96);
      backdrop-filter: blur(8px);
    }
    h1 { margin: 0; font-size: 20px; }
    .layout {
      display: grid;
      grid-template-columns: minmax(280px, 360px) minmax(520px, 1fr);
      min-height: calc(100vh - 66px);
    }
    .sidebar {
      border-right: 1px solid var(--line);
      padding: 18px;
      overflow: auto;
    }
    .main { padding: 22px; }
    .toolbar { display: flex; gap: 8px; align-items: center; }
    button, select, input, textarea {
      font: inherit;
    }
    button {
      border: 1px solid var(--line);
      background: var(--panel);
      color: var(--ink);
      padding: 8px 11px;
      cursor: pointer;
    }
    button.primary {
      border-color: var(--accent);
      background: var(--accent);
      color: white;
    }
    .trip {
      width: 100%;
      text-align: left;
      margin-bottom: 8px;
      border-radius: 8px;
    }
    .trip.active { border-color: var(--accent); background: var(--accent-soft); }
    .trip .title { font-weight: 650; }
    .trip .meta { color: var(--muted); font-size: 13px; }
    .badge {
      display: inline-block;
      margin-left: 6px;
      padding: 1px 6px;
      border-radius: 999px;
      background: #eadfcd;
      font-size: 12px;
    }
    .panel {
      max-width: 980px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--panel);
      padding: 18px;
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin: 14px 0 18px;
    }
    .metric {
      border: 1px solid var(--line);
      padding: 10px;
      border-radius: 8px;
    }
    .metric span { display: block; color: var(--muted); font-size: 12px; }
    label {
      display: block;
      margin-top: 14px;
      font-weight: 600;
    }
    input, select, textarea {
      width: 100%;
      margin-top: 5px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 9px 10px;
      background: white;
    }
    textarea { min-height: 84px; resize: vertical; }
    table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 18px;
    }
    th, td {
      padding: 9px 8px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
      text-align: left;
    }
    th { color: var(--muted); font-size: 12px; text-transform: uppercase; }
    td select, td input { margin-top: 0; }
    .actions {
      display: flex;
      gap: 10px;
      align-items: center;
      margin-top: 18px;
    }
    .saved { color: var(--accent); }
    .hint {
      color: var(--muted);
      max-width: 850px;
      margin-bottom: 16px;
    }
    @media (max-width: 900px) {
      .layout { grid-template-columns: 1fr; }
      .sidebar { border-right: 0; border-bottom: 1px solid var(--line); max-height: 40vh; }
      .summary { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>Trotter Trip Review</h1>
      <div id="count" class="hint"></div>
    </div>
    <div class="toolbar">
      <label style="margin:0;font-weight:400;"><input id="unreviewed" type="checkbox" style="width:auto;margin:0 6px 0 0;">Only unreviewed</label>
      <button id="export">Export markdown</button>
    </div>
  </header>
  <div class="layout">
    <aside class="sidebar" id="list"></aside>
    <main class="main">
      <p class="hint">
        The highest-value notes are: what the trip really was, which airports were only connections or refuel stops,
        which trips should merge or split, which legs are wrong or duplicated, and any missing leg you know existed.
        You only need to review trips that look suspicious.
      </p>
      <section id="detail"></section>
    </main>
  </div>
  <script>
    const state = { items: [], activeId: null };
    const statuses = [
      ['', 'Unreviewed'],
      ['correct', 'Correct trip'],
      ['wrong_title', 'Wrong destination/title'],
      ['needs_merge', 'Should merge with another trip'],
      ['needs_split', 'Should split into multiple trips'],
      ['duplicate', 'Duplicate trip'],
      ['not_mine', 'Not my trip'],
      ['impossible', 'Impossible / parser error'],
      ['unsure', 'Unsure']
    ];
    const segmentLabels = [
      ['', 'No label'],
      ['real_leg', 'Real leg'],
      ['layover_only', 'Layover / connection only'],
      ['technical_stop', 'Technical / refuel stop'],
      ['wrong_segment', 'Wrong segment'],
      ['duplicate_segment', 'Duplicate segment'],
      ['missing_before', 'Missing leg before this'],
      ['missing_after', 'Missing leg after this']
    ];
    function esc(value) {
      return String(value ?? '').replace(/[&<>"']/g, ch => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
      }[ch]));
    }
    function fmt(value) {
      return value ? value.replace('.000000', '') : '';
    }
    async function load() {
      const qs = document.querySelector('#unreviewed').checked ? '?unreviewed=1' : '';
      const data = await fetch('/api/trips' + qs).then(r => r.json());
      state.items = data.items;
      if (!state.items.some(item => item.id === state.activeId)) {
        state.activeId = state.items[0]?.id ?? null;
      }
      render();
    }
    function render() {
      document.querySelector('#count').textContent = `${state.items.length} trips shown`;
      const list = document.querySelector('#list');
      list.innerHTML = state.items.map(item => `
        <button class="trip ${item.id === state.activeId ? 'active' : ''}" data-id="${item.id}">
          <div class="title">${esc(item.title || '(untitled)')} ${item.feedback?.status ? `<span class="badge">${esc(item.feedback.status)}</span>` : ''}</div>
          <div class="meta">#${item.id} · ${esc(fmt(item.start_ts))} · ${item.segment_count} segments</div>
        </button>
      `).join('');
      list.querySelectorAll('[data-id]').forEach(button => {
        button.onclick = () => { state.activeId = Number(button.dataset.id); render(); };
      });
      const item = state.items.find(row => row.id === state.activeId);
      document.querySelector('#detail').innerHTML = item ? detailHtml(item) : '<p>No trips found.</p>';
      if (item) wireDetail(item);
    }
    function options(options, selected) {
      return options.map(([value, label]) => `<option value="${value}" ${value === selected ? 'selected' : ''}>${label}</option>`).join('');
    }
    function detailHtml(item) {
      const fb = item.feedback || {};
      const segs = fb.segments || {};
      return `
        <div class="panel">
          <h2 style="margin-top:0;">#${item.id} ${esc(item.title || '(untitled)')}</h2>
          <div class="summary">
            <div class="metric"><span>Dates</span>${esc(fmt(item.start_ts))}<br>${esc(fmt(item.end_ts))}</div>
            <div class="metric"><span>Segments</span>${item.segment_count}</div>
            <div class="metric"><span>Current route</span>${esc(item.segments.map(s => `${s.dep_airport}->${s.arr_airport}`).join(' / '))}</div>
          </div>
          <label>Status
            <select id="status">${options(statuses, fb.status || '')}</select>
          </label>
          <label>What should this trip actually be called?
            <input id="actual_title" value="${esc(fb.actual_title || '')}" placeholder="Example: Singapore, Philippines, Raleigh/Durham">
          </label>
          <label>Should merge with trip IDs
            <input id="merge_with" value="${esc(fb.merge_with || '')}" placeholder="Example: 72, 73">
          </label>
          <label>Should split before segment IDs
            <input id="split_before" value="${esc(fb.split_before || '')}" placeholder="Example: 188">
          </label>
          <label>Missing legs you know about
            <input id="missing_legs" value="${esc(fb.missing_legs || '')}" placeholder="Example: EWR->LFW should be represented as EWR->ADD with LFW as stopover">
          </label>
          <label>Notes
            <textarea id="notes" placeholder="Anything a human would know that the parser cannot infer yet.">${esc(fb.notes || '')}</textarea>
          </label>
          <table>
            <thead>
              <tr><th>ID</th><th>Leg</th><th>Flight</th><th>When</th><th>Label</th><th>Segment note</th></tr>
            </thead>
            <tbody>
              ${item.segments.map(segment => {
                const sfb = segs[String(segment.id)] || {};
                return `
                  <tr data-segment-id="${segment.id}">
                    <td>${segment.id}</td>
                    <td>${esc(segment.dep_airport)} -> ${esc(segment.arr_airport)}</td>
                    <td>${esc(segment.flight_number || '')}</td>
                    <td>${esc(fmt(segment.dep_time))}</td>
                    <td><select class="segment-label">${options(segmentLabels, sfb.label || '')}</select></td>
                    <td><input class="segment-note" value="${esc(sfb.note || '')}"></td>
                  </tr>
                `;
              }).join('')}
            </tbody>
          </table>
          <div class="actions">
            <button class="primary" id="save">Save review</button>
            <span class="saved" id="saved"></span>
          </div>
        </div>
      `;
    }
    function wireDetail(item) {
      document.querySelector('#save').onclick = async () => {
        const segments = {};
        document.querySelectorAll('[data-segment-id]').forEach(row => {
          const label = row.querySelector('.segment-label').value;
          const note = row.querySelector('.segment-note').value;
          if (label || note) segments[row.dataset.segmentId] = { label, note };
        });
        const payload = {
          trip_id: item.id,
          status: document.querySelector('#status').value,
          actual_title: document.querySelector('#actual_title').value,
          merge_with: document.querySelector('#merge_with').value,
          split_before: document.querySelector('#split_before').value,
          missing_legs: document.querySelector('#missing_legs').value,
          notes: document.querySelector('#notes').value,
          segments
        };
        await fetch('/api/feedback', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        document.querySelector('#saved').textContent = 'Saved';
        await load();
      };
    }
    document.querySelector('#unreviewed').onchange = load;
    document.querySelector('#export').onclick = async () => {
      const result = await fetch('/api/export').then(r => r.json());
      alert(`Saved ${result.path}`);
    };
    load();
  </script>
</body>
</html>
"""


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Missing SQLite DB: {DB_PATH}")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://{HOST}:{PORT}"
    print(f"Trip review UI: {url}")
    print(f"Feedback JSON: {FEEDBACK_FILE}")
    print(f"Markdown export: {EXPORT_FILE}")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
