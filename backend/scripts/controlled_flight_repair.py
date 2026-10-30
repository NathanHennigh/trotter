"""Preview or apply an exact persisted account repair. Never discovers mail."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user-id', type=int, required=True)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--preview-bundle', type=Path, help='Local JSON: {messages:[{full_msg,documents:[]}]}')
    action.add_argument('--apply', metavar='MANIFEST_ID')
    parser.add_argument('--schedule-links', type=Path, help='Explicit reviewed source selectors; preview only')
    parser.add_argument('--expect-plan-hash', help='Required for apply; copied from the saved preview')
    parser.add_argument('--output', type=Path, help='Write preview/result JSON to this exact file')
    args = parser.parse_args()
    from app.db import SessionLocal
    from app.models import User
    from app.services.booking_repair import apply_repair, prepare_repair
    from app.services.flight_message import prepare_flight_message
    with SessionLocal() as db:
        if args.apply:
            if not args.expect_plan_hash or args.schedule_links:
                parser.error('Apply requires --expect-plan-hash and cannot accept new schedule links')
            result = apply_repair(db, args.user_id, args.apply, expected_plan_hash=args.expect_plan_hash)
            output = {'manifest_id': args.apply, 'state': 'applied', 'result': result}
        else:
            user = db.get(User, args.user_id)
            if not user:
                parser.error('Account not found')
            bundle = json.loads(args.preview_bundle.read_text(encoding='utf-8-sig'))
            prepared = [prepare_flight_message(item['full_msg'], user_name=user.name or '',
                aliases=user.travel_name_aliases or [], documents=item.get('documents', []), force_parse=True)
                for item in bundle['messages']]
            links = json.loads(args.schedule_links.read_text(encoding='utf-8-sig')) if args.schedule_links else []
            manifest = prepare_repair(db, args.user_id, prepared, schedule_links=links)
            db.commit()
            output = {'manifest_id': manifest.id, 'state': manifest.state, 'plan_hash': manifest.plan_hash,
                      'base_fingerprint': manifest.base_fingerprint, 'preview': manifest.preview_json}
    rendered = json.dumps(output, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(rendered + '\n', encoding='utf-8')
    details = output.get('preview') or output.get('result') or {}
    summary = {key: output[key] for key in ('manifest_id', 'state', 'plan_hash', 'base_fingerprint') if key in output}
    summary.update(user_id=args.user_id, added=len(details.get('added', [])), updated=len(details.get('updated', [])),
        flights_before=details.get('flights_before'), flights_after=details.get('flights_after'),
        held_reasons=dict(Counter(item['reason'] for item in details.get('held', []))),
        invariants=details.get('invariants', {}))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
