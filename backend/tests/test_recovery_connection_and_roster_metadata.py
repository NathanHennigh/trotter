import pytest

from app.models import Message, MessageStatus, Segment
from app.services import flight_template_recovery as recovery
from app.services.parser import PARSER_VERSION
from test_booking_import_worker import worker, run
from test_carrier_worker_integration import select_message
from test_flight_template_recovery import setup
from test_partial_airline_evidence import message


FORWARDED = "Fwd: Check in online for your flight EK321 on 11 January"
CASES = [
    ("Your Flight Confirmation Code ABC123", "Frontier Airlines <flights@emails.flyfrontier.com>"),
    ("Check in online for your flight EK321 on 11 January", "notice@emirates.com"),
    (FORWARDED, "Forwarder <person@example.test>"),
    (FORWARDED.replace('Fwd: ', 'Re:Fwd:'), "Forwarder <person@example.test>"),
    ("Check-in is open, download your boarding pass now.", "Aeromexico <no-reply@aeromexico.com>"),
]


@pytest.mark.parametrize("subject,sender", CASES)
def test_new_source_shapes_recover_current_version_rows_with_existing_bounds(worker, monkeypatch, subject, sender):
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    assert recovery.eligible(subject, sender)
    with factory() as db:
        for n in range(30):
            db.add(Message(user_id=uid, provider_msg_id=f"source-{n}", subject=subject,
                from_email=sender, status=MessageStatus.ACCEPTED, parse_version=PARSER_VERSION,
                parse_evidence={"resolved":True, "retained":"original evidence"}))
        db.commit()
        first = recovery.select_messages(db, uid, limit=1000)
        assert len(first) == 25
        for row in first:
            row.parse_evidence = {**row.parse_evidence, recovery.MARKER:recovery.completed_marker(uid)}
        db.commit()
        second = recovery.select_messages(db, uid)
        assert len(second) == 5
        for row in second:
            row.parse_evidence = {**row.parse_evidence, recovery.MARKER:recovery.completed_marker(uid)}
        db.commit()
        assert recovery.select_messages(db, uid) == []
        assert all(r.parse_evidence['retained'] == 'original evidence' for r in db.query(Message))


@pytest.mark.parametrize("subject,sender", [
    ("Your flight confirmation", "notice@flyfrontier.com.attacker.test"),
    ("Your flight confirmation", "notice@emirates.com.attacker.test"),
    ("Your flight confirmation", "notice@notemirates.com"),
    ("Check-in is open", "notice@aeromexico.com.attacker.test"),
    ("Flight deal alert", "notice@emirates.com"),
    (FORWARDED.replace('Fwd: ', ''), "person@example.test"),
    (FORWARDED.replace('EK321', 'AA321'), "person@example.test"),
    (FORWARDED.replace('11 January', 'soon'), "person@example.test"),
    (FORWARDED.replace('11 January', '32 January'), "person@example.test"),
    (FORWARDED + ' sale', "person@example.test"),
    ('Re: Fwd: Re: Fwd: ' + FORWARDED, "person@example.test"),
    (FORWARDED, "a@example.test,b@example.test"),
])
def test_metadata_does_not_admit_lookalikes_or_generic_forwarded_mail(subject, sender):
    assert not recovery.eligible(subject, sender)


def test_new_forwarded_metadata_read_never_becomes_flight_authority(worker, monkeypatch):
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    msg = message('An incomplete forwarded message with no printed itinerary or passenger.')
    msg['payload']['headers'] = [{'name':'From', 'value':'person@example.test'}, {'name':'Subject', 'value':FORWARDED}]
    with factory() as db:
        db.add(Message(user_id=uid, provider_msg_id=msg['id'], subject=FORWARDED,
            from_email='person@example.test', status=MessageStatus.ACCEPTED,
            ignored=True, parse_version=PARSER_VERSION, parse_evidence={'resolved':True}))
        db.commit()
        monkeypatch.setenv('BOOKING_STRICT_ENRICHMENT_ENABLED', 'false')
        assert recovery.select_messages(db, uid) == []
        monkeypatch.setenv('BOOKING_STRICT_ENRICHMENT_ENABLED', 'true')
        monkeypatch.setenv('FLIGHT_IMPORT_RECOVERY_USER_IDS', str(uid + 1))
        assert recovery.select_messages(db, uid) == []
        monkeypatch.setenv('FLIGHT_IMPORT_RECOVERY_USER_IDS', str(uid))
    fetched = select_message(monkeypatch, msg)
    assert run(factory, uid, 'sync', 'new-metadata-first')['state'] == 'completed'
    assert run(factory, uid, 'sync', 'new-metadata-repeat')['state'] == 'completed'
    with factory() as db:
        assert db.query(Segment).count() == 0
        assert recovery.current_for_user(db.query(Message).one().parse_evidence, uid)
    assert fetched == [msg['id']]


def test_forwarded_metadata_screening_is_bounded_and_advances(worker, monkeypatch):
    factory, uid, _ = worker
    setup(monkeypatch, uid)
    with factory() as db:
        for n in range(105):
            db.add(Message(user_id=uid, provider_msg_id=f'lookalike-{n}', subject=FORWARDED+' sale',
                from_email='person@example.test', status=MessageStatus.ACCEPTED, parse_version=PARSER_VERSION))
        db.add(Message(user_id=uid, provider_msg_id='actual-shape', subject=FORWARDED,
            from_email='person@example.test', status=MessageStatus.ACCEPTED, parse_version=PARSER_VERSION))
        db.commit()
        assert recovery.select_messages(db, uid) == []
        assert sum(bool((r.parse_evidence or {}).get(recovery.MARKER)) for r in db.query(Message)) == 100
        assert [r.provider_msg_id for r in recovery.select_messages(db, uid)] == ['actual-shape']
