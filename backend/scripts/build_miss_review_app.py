from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote_plus


ROOT = Path(__file__).resolve().parent
CORPUS_DIR = ROOT / ".flight_shape_corpus"
OUT_PATH = CORPUS_DIR / "miss_review.html"
EXTRA_REVIEW_REASONS = {
    "uncataloged_candidate",
    "possible_overparse_or_catalog_gap",
    "cataloged_under_other_pnr_or_alias",
}


def main() -> None:
    evaluation = json.loads((CORPUS_DIR / "evaluation_results.json").read_text(encoding="utf-8"))
    manifest = json.loads((CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))

    records = manifest.get("records") or []
    manifest_by_id = {record["message_id"]: record for record in records}
    eval_by_id = {row["message_id"]: row for row in evaluation.get("results") or []}
    messages_by_id = load_messages(records)
    records_by_pnr = index_records_by_pnr(records, eval_by_id)
    groups = build_extra_groups(evaluation.get("results") or [], records_by_pnr, manifest_by_id)

    OUT_PATH.write_text(render_page(groups, eval_by_id, manifest_by_id, messages_by_id), encoding="utf-8")
    print(OUT_PATH)


def load_messages(records: list[dict]) -> dict[str, dict]:
    messages = {}
    for record in records:
        message_id = record.get("message_id")
        message_path = record.get("message_path")
        if not message_id or not message_path:
            continue
        path = CORPUS_DIR / message_path
        if path.exists():
            messages[message_id] = json.loads(path.read_text(encoding="utf-8"))
    return messages


def index_records_by_pnr(records: list[dict], eval_by_id: dict[str, dict]) -> dict[str, list[str]]:
    by_pnr: dict[str, set[str]] = defaultdict(set)
    for record in records:
        message_id = record.get("message_id")
        for pnr in record.get("pnrs") or []:
            by_pnr[pnr].add(message_id)
    for row in eval_by_id.values():
        for bucket in ("expected", "parsed", "missing", "extras"):
            for segment in row.get(bucket) or []:
                pnr = segment.get("pnr")
                if pnr:
                    by_pnr[pnr].add(row["message_id"])
    return {pnr: sorted(ids) for pnr, ids in by_pnr.items()}


def build_extra_groups(
    rows: list[dict],
    records_by_pnr: dict[str, list[str]],
    manifest_by_id: dict[str, dict],
) -> list[dict]:
    groups = []
    reason_rank = {
        "uncataloged_candidate": 0,
        "possible_overparse_or_catalog_gap": 1,
        "cataloged_under_other_pnr_or_alias": 2,
    }
    for row in rows:
        extra_analysis = [
            item for item in row.get("extra_analysis") or []
            if item.get("reason") in EXTRA_REVIEW_REASONS
            and not item.get("review_resolved")
        ]
        if not extra_analysis:
            continue
        pnrs = sorted({item["segment"].get("pnr") for item in extra_analysis if item["segment"].get("pnr")})
        related_ids: set[str] = {row["message_id"]}
        for pnr in pnrs:
            related_ids.update(records_by_pnr.get(pnr) or [])
        for record in manifest_by_id.values():
            if row["message_id"] in related_ids:
                continue
            if set(record.get("pnrs") or []) & set(pnrs):
                related_ids.add(record["message_id"])
        primary_reason = min(
            (item.get("reason") or "" for item in extra_analysis),
            key=lambda reason: reason_rank.get(reason, 99),
        )
        groups.append(
            {
                "message_id": row["message_id"],
                "pnrs": pnrs,
                "row": row,
                "extra_analysis": extra_analysis,
                "primary_reason": primary_reason,
                "related_ids": sorted(related_ids),
            }
        )
    groups.sort(key=lambda group: (reason_rank.get(group["primary_reason"], 99), group["message_id"]))
    return groups


def render_page(
    groups: list[dict],
    eval_by_id: dict[str, dict],
    manifest_by_id: dict[str, dict],
    messages_by_id: dict[str, dict],
) -> str:
    total_candidates = sum(len(group.get("extra_analysis") or []) for group in groups)
    cards = "\n".join(
        render_group(index, group, eval_by_id, manifest_by_id, messages_by_id)
        for index, group in enumerate(groups, start=1)
    ) or render_empty_state()
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Flight Extra Candidate Review</title>
  <style>
    :root {{ color-scheme: light; --ink:#17202a; --muted:#637083; --line:#d9dee7; --bg:#f7f8fb; --panel:#fff; --accent:#0f766e; --warn:#a16207; }}
    * {{ box-sizing: border-box; }}
    body {{ margin:0; font-family: Inter, Segoe UI, Arial, sans-serif; background:var(--bg); color:var(--ink); }}
    header {{ position:sticky; top:0; z-index:2; padding:16px 22px; background:#ffffffee; border-bottom:1px solid var(--line); backdrop-filter: blur(8px); }}
    h1 {{ margin:0 0 6px; font-size:22px; }}
    .sub {{ color:var(--muted); font-size:14px; }}
    main {{ max-width:1380px; margin:0 auto; padding:20px; }}
    .toolbar {{ display:flex; gap:10px; align-items:center; margin-top:12px; flex-wrap:wrap; }}
    input[type=search] {{ width:min(520px, 100%); padding:10px 12px; border:1px solid var(--line); border-radius:6px; font-size:14px; }}
    button {{ padding:9px 12px; border:1px solid var(--line); border-radius:6px; background:#fff; cursor:pointer; }}
    button.primary {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
    .group {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; margin:0 0 18px; overflow:hidden; }}
    .group-head {{ padding:14px 16px; display:grid; grid-template-columns:1fr auto; gap:16px; border-bottom:1px solid var(--line); }}
    .title {{ font-weight:700; }}
    .meta {{ color:var(--muted); font-size:13px; margin-top:4px; }}
    .pill {{ display:inline-block; padding:3px 7px; border-radius:999px; background:#e9f5f3; color:#075e57; font-size:12px; margin:2px 4px 2px 0; }}
    .review, .related, .notes {{ padding:14px 16px; border-bottom:1px solid var(--line); }}
    .candidate {{ display:grid; grid-template-columns:1fr auto; gap:12px; padding:9px 0; border-top:1px dashed var(--line); }}
    .candidate:first-child {{ border-top:0; }}
    .route {{ font-family: Consolas, monospace; font-size:13px; }}
    .reason {{ color:var(--warn); font-size:13px; }}
    details.email {{ border:1px solid var(--line); border-radius:6px; margin:10px 0; background:#fbfcfe; }}
    details.email > summary {{ cursor:pointer; padding:10px 12px; list-style:none; }}
    details.email > summary::-webkit-details-marker {{ display:none; }}
    .email-grid {{ display:grid; grid-template-columns:minmax(320px, 1fr) minmax(320px, 1fr); gap:12px; padding:0 12px 12px; }}
    pre {{ white-space:pre-wrap; overflow:auto; max-height:520px; padding:10px; border:1px solid var(--line); border-radius:6px; background:#fff; font-size:12px; line-height:1.4; }}
    iframe {{ width:100%; height:520px; border:1px solid var(--line); border-radius:6px; background:#fff; }}
    textarea {{ width:100%; min-height:110px; padding:10px; border:1px solid var(--line); border-radius:6px; font-family:inherit; resize:vertical; }}
    select {{ width:min(420px, 100%); padding:10px 12px; border:1px solid var(--line); border-radius:6px; background:#fff; font-size:14px; }}
    label {{ display:block; color:var(--muted); font-size:13px; margin:0 0 6px; }}
    .parsed {{ color:#155e28; }}
    .missing {{ color:#8a1f11; }}
    .links a {{ color:#075e57; margin-right:10px; font-size:13px; }}
    .hidden {{ display:none; }}
    @media (max-width: 880px) {{ .group-head, .email-grid, .candidate {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <header>
    <h1>Flight Extra Candidate Review</h1>
    <div class="sub">{len(groups)} email groups, {total_candidates} extra candidates to review. Start with uncataloged candidates, then possible over-parses/catalog gaps, then PNR aliases.</div>
    <div class="toolbar">
      <input id="filter" type="search" placeholder="Filter by reason, PNR, route, message id, sender, subject">
      <button class="primary" onclick="exportNotes()">Export notes</button>
      <button onclick="expandAll(true)">Expand all emails</button>
      <button onclick="expandAll(false)">Collapse emails</button>
    </div>
  </header>
  <main>{cards}</main>
  <script>
    const filter = document.getElementById('filter');
    filter.addEventListener('input', () => {{
      const q = filter.value.trim().toLowerCase();
      document.querySelectorAll('.group').forEach(card => {{
        card.classList.toggle('hidden', q && !card.dataset.search.includes(q));
      }});
    }});
    document.querySelectorAll('textarea[data-key]').forEach(area => {{
      const key = area.dataset.key;
      area.value = localStorage.getItem(key) || area.dataset.defaultValue || '';
      area.addEventListener('input', () => localStorage.setItem(key, area.value));
    }});
    document.querySelectorAll('select[data-key]').forEach(select => {{
      const key = select.dataset.key;
      select.value = localStorage.getItem(key) || select.dataset.defaultValue || '';
      select.addEventListener('change', () => localStorage.setItem(key, select.value));
    }});
    function exportNotes() {{
      const notes = [];
      document.querySelectorAll('.notes[data-key]').forEach(box => {{
        const select = box.querySelector('select');
        const area = box.querySelector('textarea');
        if ((select && select.value) || (area && area.value.trim())) {{
          notes.push({{
            key: box.dataset.key,
            messageId: box.dataset.messageId,
            pnrs: box.dataset.pnrs ? box.dataset.pnrs.split(',').filter(Boolean) : [],
            reason: box.dataset.reason,
            classification: select ? select.value : '',
            note: area ? area.value : ''
          }});
        }}
      }});
      const blob = new Blob([JSON.stringify(notes, null, 2)], {{ type: 'application/json' }});
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'flight-extra-review-notes.json';
      a.click();
      URL.revokeObjectURL(a.href);
    }}
    function expandAll(open) {{
      document.querySelectorAll('details.email').forEach(details => details.open = open);
    }}
  </script>
</body>
</html>"""


def render_group(
    index: int,
    group: dict,
    eval_by_id: dict[str, dict],
    manifest_by_id: dict[str, dict],
    messages_by_id: dict[str, dict],
) -> str:
    row = group["row"]
    pnrs = ", ".join(group["pnrs"]) or "-"
    candidates = "\n".join(render_extra_candidate(item) for item in group.get("extra_analysis") or [])
    related = "\n".join(
        render_email(message_id, eval_by_id, manifest_by_id, messages_by_id, primary=message_id == row["message_id"])
        for message_id in group["related_ids"]
    )
    note_key = f"extra-review:{row['message_id']}:{','.join(group['pnrs'])}:{group.get('primary_reason') or ''}"
    default_review = next(
        (item for item in group.get("extra_analysis") or [] if item.get("review_classification") or item.get("review_note")),
        {},
    )
    default_classification = default_review.get("review_classification") or ""
    default_note = default_review.get("review_note") or ""
    search_blob = " ".join(
        [
            row.get("message_id") or "",
            row.get("sender_domain") or "",
            row.get("subject") or "",
            pnrs,
            group.get("primary_reason") or "",
            " ".join(
                f"{item['segment'].get('dep_airport')} {item['segment'].get('arr_airport')} {item['segment'].get('flight_number') or ''}"
                for item in group.get("extra_analysis") or []
            ),
        ]
    )
    return f"""
<section class="group" data-search="{esc_attr(search_blob.lower())}">
  <div class="group-head">
    <div>
      <div class="title">{index}. {esc(row.get('subject') or '(no subject)')}</div>
      <div class="meta">{esc(row['message_id'])} - {esc(row.get('sender_domain') or '-')} - shape {esc(row.get('shape') or '-')}</div>
      <div><span class="pill">{esc(group.get('primary_reason') or '-')}</span>{''.join(f'<span class="pill">{esc(pnr)}</span>' for pnr in group['pnrs'])}</div>
    </div>
    <div class="meta">matched {row.get('matched_count')}/{row.get('expected_count')} - parsed {row.get('parsed_count')} - extras {row.get('extra_count')}</div>
  </div>
  <div class="review">
    <h3>Extra Candidates</h3>
    {candidates}
  </div>
  <div class="notes" data-key="{esc_attr(note_key)}" data-message-id="{esc_attr(row['message_id'])}" data-pnrs="{esc_attr(','.join(group['pnrs']))}" data-reason="{esc_attr(group.get('primary_reason') or '')}">
    <h3>Your Review</h3>
    <label for="{esc_attr(note_key)}-classification">Classification</label>
    <select id="{esc_attr(note_key)}-classification" data-key="{esc_attr(note_key)}:classification" data-default-value="{esc_attr(default_classification)}">
      <option value="">Choose classification...</option>
      <option value="real_flight_add_to_catalog">Real flight - add to catalog</option>
      <option value="check_in_email_update_evidence">Check-in email - update evidence</option>
      <option value="duplicate_or_update_evidence">Duplicate or update evidence</option>
      <option value="pnr_alias_same_trip">PNR alias for same trip</option>
      <option value="parser_overparse_ignore">Parser over-parse - ignore/fix</option>
      <option value="not_my_flight_or_irrelevant">Not my flight or irrelevant</option>
      <option value="needs_more_investigation">Needs more investigation</option>
    </select>
    <label for="{esc_attr(note_key)}-note" style="margin-top:12px;">Notes</label>
    <textarea id="{esc_attr(note_key)}-note" data-key="{esc_attr(note_key)}:note" data-default-value="{esc_attr(default_note)}" placeholder="Optional context: same as LGCOFH, return was canceled, PNR alias for DYXGR8, should only be IAH -> DCA, etc."></textarea>
  </div>
  <div class="related">
    <h3>Related Emails</h3>
    {related}
  </div>
</section>"""


def render_empty_state() -> str:
    return """
<section class="group">
  <div class="group-head">
    <div>
      <div class="title">No Extra Candidates</div>
      <div class="meta">No extra candidates need review.</div>
    </div>
  </div>
</section>"""


def render_extra_candidate(item: dict) -> str:
    segment = item.get("segment") or {}
    route = f"{segment.get('flight_number') or '-'} {segment.get('dep_airport')} -> {segment.get('arr_airport')}"
    details = f"{segment.get('dep_time')} - PNR {segment.get('pnr') or '-'} - source {segment.get('source') or '-'}"
    classification = item.get("review_classification") or "unreviewed"
    source = item.get("review_source") or "-"
    return f"""
<div class="candidate">
  <div>
    <div class="route missing">{esc(route)}</div>
    <div class="meta">{esc(details)}</div>
  </div>
  <div class="reason">{esc(item.get('reason') or '-')}<br><span class="meta">{esc(classification)} - {esc(source)}</span></div>
</div>"""


def render_email(
    message_id: str,
    eval_by_id: dict[str, dict],
    manifest_by_id: dict[str, dict],
    messages_by_id: dict[str, dict],
    *,
    primary: bool,
) -> str:
    record = manifest_by_id.get(message_id) or {}
    row = eval_by_id.get(message_id) or {}
    message = messages_by_id.get(message_id) or {}
    subject = message.get("subject") or record.get("subject") or "(no subject)"
    sender = message.get("from") or record.get("sender_domain") or "-"
    local_json = f"messages/{message_id}.json"
    gmail_query = quote_plus(" ".join(part for part in [*(record.get("pnrs") or []), subject] if part))
    gmail_link = f"https://mail.google.com/mail/u/0/#search/{gmail_query}"
    parsed = render_segment_list(row.get("parsed") or [], "parsed")
    expected = render_segment_list(row.get("expected") or [], "parsed")
    extras = render_segment_list(row.get("extras") or [], "missing")
    plain = message.get("plain_text") or ""
    html_body = message.get("html") or ""
    open_attr = " open" if primary else ""
    primary_label = "primary review email" if primary else "related"
    return f"""
<details class="email"{open_attr}>
  <summary>
    <strong>{esc(subject)}</strong>
    <div class="meta">{esc(primary_label)} - {esc(message_id)} - {esc(sender)} - {esc(message.get('date') or '')}</div>
    <div class="links"><a href="{esc_attr(local_json)}" target="_blank">Open JSON</a><a href="{esc_attr(gmail_link)}" target="_blank">Search Gmail</a></div>
  </summary>
  <div class="email-grid">
    <div>
      <h4>Expected Segments</h4>
      {expected or '<div class="meta">None</div>'}
      <h4>Parsed Segments</h4>
      {parsed or '<div class="meta">None</div>'}
      <h4>Extra Candidates On This Row</h4>
      {extras or '<div class="meta">None</div>'}
      <h4>Plain Text</h4>
      <pre>{esc(plain)}</pre>
    </div>
    <div>
      <h4>Rendered HTML</h4>
      <iframe sandbox srcdoc="{esc_attr(html_body)}"></iframe>
    </div>
  </div>
</details>"""


def render_segment_list(segments: list[dict], class_name: str) -> str:
    lines = []
    for segment in segments:
        lines.append(
            f"<div class=\"route {class_name}\">{esc(segment.get('flight_number') or '-')} "
            f"{esc(segment.get('dep_airport') or '-')} -> {esc(segment.get('arr_airport') or '-')} "
            f"<span class=\"meta\">{esc(segment.get('dep_time') or '')} - PNR {esc(segment.get('pnr') or '-')} - {esc(segment.get('source') or '')}</span></div>"
        )
    return "\n".join(lines)


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=False)


def esc_attr(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


if __name__ == "__main__":
    main()
