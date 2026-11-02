"""Positive carrier recovery and real-import negative boundaries, all synthetic."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import socket

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, BookingObservation, CarrierTravelEvidence, ItineraryHistory, Message, MessageStatus, Segment, Trip, User
from app.services import carrier_travel_recovery as recovery
from app.services.booking_import import apply_booking_message, _retained_flight
from app.services.flight_message import prepare_flight_message
from app.services.parser import PARSER_VERSION
from carrier_corroboration_fixture_helpers import fixture, gmail_message, source


@pytest.fixture
def account(monkeypatch):
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "true")
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", "*")
    monkeypatch.delenv("BOOKING_STRICT_ENRICHMENT_ENABLED", raising=False)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("No network during carrier recovery"))
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("No network during carrier recovery"))
    from app.services import builder
    monkeypatch.setattr(builder, "enrich_segment", lambda *a, **k: None)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        person = fixture()["user"]
        user = User(name=person["name"], email=person["email"], travel_name_aliases=person["aliases"])
        db.add(user); db.flush()
        yield db, user
    engine.dispose()


def process(db, user, value, *, authentication=True):
    payload = prepare_flight_message(gmail_message(value, authentication=authentication),
        user_name=user.name, aliases=user.travel_name_aliases)
    message = db.query(Message).filter_by(user_id=user.id, provider_msg_id=value["id"]).one_or_none()
    if message is None:
        message = Message(user_id=user.id, provider_msg_id=value["id"], subject=value["subject"], from_email=value["sender"])
        db.add(message); db.flush()
    if payload["parse_result"] is not None:
        applied = apply_booking_message(db, user.id, payload["parse_result"], source_message_id=value["id"],
            subject=payload["subject"], plain_text=payload["plain_text"], html=payload["html"], received_at=payload["received_at"])
        message.status = applied.status
        message.parse_error = "passenger_identity_unresolved" if applied.build.held_unknown else None
    else:
        message.status, message.parse_error = MessageStatus.ACCEPTED, None
    message.parse_version = PARSER_VERSION
    db.flush()
    rows = recovery.record_payload(db, user.id, payload)
    result = recovery.reconcile(db, user.id, rows)
    db.flush()
    return payload, rows, result


def run_case(db, user, key, *, reverse=False):
    case = next(value for value in fixture()["positive_cases"] if value["id"] == key)
    messages = [source(key) for key in case["sources"]]
    messages.sort(key=lambda value: value["received_at"], reverse=reverse)
    for value in messages:
        process(db, user, value)
    return case, messages


def identity(segment):
    return (segment.flight_number, segment.dep_airport, segment.arr_airport,
            segment.dep_time.isoformat(), segment.arr_time.isoformat(), segment.meta_json["ownership"])


@pytest.mark.parametrize("case_key", ["aa-connecting-and-return", "sun-explicit-post-travel"])
@pytest.mark.parametrize("reverse", [False, True])
def test_complete_original_flights_recover_in_both_source_orders(account, case_key, reverse):
    db, user = account
    case, messages = run_case(db, user, case_key, reverse=reverse)
    actual = db.query(Segment).order_by(Segment.dep_time).all()
    assert len(actual) == len(case["expected_legs"]), "Zero deltas is not a positive acceptance result"
    for expected, row in zip(case["expected_legs"], actual):
        assert (row.flight_number, row.dep_airport, row.arr_airport) == (expected["number"], expected["dep"], expected["arr"])
        assert row.dep_time == datetime.fromisoformat(expected["departure_utc"]).replace(tzinfo=None)
        assert row.arr_time == datetime.fromisoformat(expected["arrival_utc"]).replace(tzinfo=None)
        assert row.meta_json["ownership"] == "self"
        assert any(entry.get("carrier_evidence_ids") for entry in row.meta_json["passenger_evidence"])
    # Original observations stay UNKNOWN; supporting assertions are separately typed.
    assert {row.ownership for row in db.query(BookingObservation)} == {"unknown"}
    for value in messages:
        message = db.query(Message).filter_by(provider_msg_id=value["id"]).one()
        assert message.status == MessageStatus.ACCEPTED
        assert recovery.MARKER in message.parse_evidence
    evidence = [(row.id, deepcopy(row.facts), row.evidence_key) for row in db.query(BookingObservation)]
    assertions = [(row.id, deepcopy(row.facts), row.evidence_key) for row in db.query(CarrierTravelEvidence)]
    state = [(row.id, row.trip_id, identity(row)) for row in actual]
    empty_trip_history = [(row.id, deepcopy(row.snapshot)) for row in db.query(ItineraryHistory).filter_by(
        entity_type="trip", reason="empty_trip_after_booking_reconciliation")]
    trip_ids = [row.id for row in db.query(Trip).order_by(Trip.id)]
    for value in messages:
        process(db, user, value)
    assert [(row.id, deepcopy(row.facts), row.evidence_key) for row in db.query(BookingObservation)] == evidence
    assert [(row.id, deepcopy(row.facts), row.evidence_key) for row in db.query(CarrierTravelEvidence)] == assertions
    assert [(row.id, row.trip_id, identity(row)) for row in db.query(Segment).order_by(Segment.dep_time)] == state
    assert [(row.id, deepcopy(row.snapshot)) for row in db.query(ItineraryHistory).filter_by(
        entity_type="trip", reason="empty_trip_after_booking_reconciliation")] == empty_trip_history
    assert [row.id for row in db.query(Trip).order_by(Trip.id)] == trip_ids


@pytest.mark.parametrize("case_key", ["aa-connecting-and-return", "sun-explicit-post-travel"])
@pytest.mark.parametrize("reverse", [False, True])
def test_represented_carrier_leg_reuses_trip_but_still_runs_normal_upsert(account, monkeypatch, case_key, reverse):
    db, user = account
    _, messages = run_case(db, user, case_key, reverse=reverse)
    from app.services import builder
    calls = []
    original = builder._upsert_segment

    def upsert(*args, **kwargs):
        calls.append(args[3].source_message_id)
        return original(*args, **kwargs)

    monkeypatch.setattr(builder, "_upsert_segment", upsert)
    monkeypatch.setattr(builder, "_find_or_create_trip", lambda *a, **k: pytest.fail("Already linked leg must reuse its trip"))
    for value in messages:
        process(db, user, value)
    assert calls, "Reusing the trip must not suppress normal updates or protection checks"


def test_later_carrier_schedule_and_new_original_provenance_still_apply(account):
    db, user = account
    run_case(db, user, "sun-explicit-post-travel")
    segment = db.query(Segment).one()
    before = identity(segment)
    original_ids = list(segment.meta_json["observation_ids"])
    old_observations = [(row.id, deepcopy(row.facts)) for row in db.query(BookingObservation)]
    update = source("sun-update-3")
    update["id"] = "sun-later-schedule"
    update["received_at"] = "2027-03-12T02:00:00Z"
    update["text"] = update["text"].replace("11:00AM", "11:30AM").replace("3:20PM", "3:50PM")
    process(db, user, update)
    assert db.query(Segment).count() == 1
    assert segment.dep_time == datetime.fromisoformat(before[3]) + timedelta(minutes=30)
    assert segment.arr_time == datetime.fromisoformat(before[4]) + timedelta(minutes=30)
    assert set(original_ids) < set(segment.meta_json["observation_ids"])
    assert update["id"] in segment.meta_json["source_message_ids"]
    assert segment.meta_json["time_provenance"]["departure"]["utc"].startswith(segment.dep_time.isoformat())
    assert [(row.id, row.facts) for row in db.query(BookingObservation).filter(BookingObservation.id.in_([r[0] for r in old_observations]))] == old_observations
    assert db.query(ItineraryHistory).filter_by(entity_type="segment", entity_id=segment.id).count() > 0
    latest = deepcopy(segment.meta_json), identity(segment)
    process(db, user, source("sun-update-3"))
    assert (segment.meta_json, identity(segment)) == latest


@pytest.mark.parametrize("boundary", ["off", "other_user", "other_day", "unlinked_observation", "unlinked_source", "no_carrier_proof", "multiple", "ambiguous"])
def test_projection_trip_reuse_requires_exact_existing_original_link(account, monkeypatch, boundary):
    db, user = account
    run_case(db, user, "sun-explicit-post-travel")
    from app.services.booking_ledger import record_flight_observations
    _, flight = target(db)
    applied = record_flight_observations(db, user.id, [flight], source_message_id=flight.source_message_id,
                                       source_event_at=flight.source_received_at).flights[0]
    assert recovery.existing_projection_trip(db, user.id, [applied]) is not None
    user_id, flights = user.id, [applied]
    if boundary == "off":
        monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "false")
    elif boundary == "other_user":
        user_id += 1
    elif boundary == "other_day":
        applied.time_provenance = deepcopy(applied.time_provenance)
        applied.time_provenance["departure_local_date"] = "2027-03-12"
    elif boundary == "unlinked_observation":
        applied.observation_id += 1000
    elif boundary == "unlinked_source":
        applied.source_message_id = "unlinked-original"
    elif boundary == "no_carrier_proof":
        applied.passenger_evidence = [{"reason": "verified_same_booking_dated_leg"}]
    elif boundary == "multiple":
        flights *= 2
    else:
        original = db.query(Segment).one()
        db.add(Segment(**{column.name: deepcopy(getattr(original, column.name))
                          for column in Segment.__table__.columns if column.name != "id"}))
        db.flush()
    assert recovery.existing_projection_trip(db, user_id, flights) is None


@pytest.mark.parametrize("missing", ["aa-survey", "aa-checkin", "aa-connection"])
def test_aa_requires_all_independent_typed_components(account, missing):
    db, user = account
    for key in ["aa-connection", "aa-gate-update", "aa-survey", "aa-checkin", "aa-return"]:
        if key != missing:
            process(db, user, source(key))
    assert db.query(Segment).count() == 0


@pytest.mark.parametrize("mutation", ["wrong_name", "wrong_day", "reversed_route", "wrong_sender", "no_auth", "wrong_region"])
def test_sun_corroboration_cannot_join_nearby_or_untrusted_claims(account, mutation):
    db, user = account
    process(db, user, source("sun-update-3"))
    value = source("sun-survey")
    if mutation == "wrong_name":
        value["subject"] = value["subject"].replace("Maya", "Taylor")
        value["text"] = value["text"].replace("Maya", "Taylor")
    elif mutation == "wrong_day":
        value["text"] = value["text"].replace("March 11", "March 10")
    elif mutation == "reversed_route":
        value["text"] = value["text"].replace("from Minneapolis, MN to Cancun, Mexico", "from Cancun, Mexico to Minneapolis, MN")
    elif mutation == "wrong_sender":
        value["sender"] = "Untrusted <suncountryairlines@express.sea1.medallia.com.example.test>"
    elif mutation == "wrong_region":
        value["text"] = value["text"].replace("Minneapolis, MN", "Minneapolis, TX")
    process(db, user, value, authentication=mutation != "no_auth")
    assert db.query(Segment).count() == 0


def test_bilt_headers_and_other_person_survey_do_not_establish_owner(account):
    db, user = account
    for key in ["bilt-other-openjaw", "bilt-other-return", "aa-other-survey", "aa-return", "emirates-other", "emirates-other-compact"]:
        process(db, user, source(key))
    assert db.query(Segment).count() == 0
    assert db.query(CarrierTravelEvidence).filter_by(kind="operational_personal").count() == 0
    assert db.query(BookingObservation).count() >= 6


def test_recipient_or_footer_name_is_not_authenticated_source_identity(account):
    db, user = account
    value = source("sun-update-3")
    payload = prepare_flight_message(gmail_message(value, recipient="someone@example.test"),
                                    user_name=user.name, aliases=user.travel_name_aliases)
    db.add(Message(user_id=user.id, provider_msg_id=value["id"], parse_version=PARSER_VERSION, status=MessageStatus.ACCEPTED))
    db.flush()
    assert recovery.record_payload(db, user.id, payload) == []


def target(db, source_id="sun-update-3"):
    observation = db.query(BookingObservation).filter_by(source_message_id=source_id).order_by(BookingObservation.id.desc()).first()
    flight = _retained_flight(observation)
    flight.source_message_id = observation.source_message_id
    return observation, flight


@pytest.mark.parametrize("protection", ["manual", "cancellation", "share", "assignment", "competing_booking", "conflicting_passenger"])
def test_protected_or_ambiguous_target_stays_held(account, protection):
    db, user = account
    process(db, user, source("sun-update-3"))
    observation, flight = target(db)
    if protection == "manual":
        from app.services.booking_ledger import record_user_decision
        record_user_decision(db, user.id, flight, ownership="other", status="active")
    elif protection == "cancellation":
        from app.services.booking_ledger import record_cancellation
        record_cancellation(db, user.id, flight.pnr, source_message_id="cancellation",
                            source_event_at=flight.source_received_at, flights=[flight])
    elif protection in {"share", "assignment"}:
        from app.models import FlightShare, TravelInboxEvidence, TravelInboxItem, TravelInboxAssignment
        item = db.query(TravelInboxItem).join(TravelInboxEvidence).filter(TravelInboxEvidence.observation_id == observation.id).first()
        if protection == "share":
            db.add(FlightShare(sender_id=user.id, recipient_email="other@example.test", passenger_name="Maya Vale",
                client_request_id="fixture-share", request_hash="x", token_hash="y", token_encrypted=b"fixture", item_ids=[item.id],
                flights=[], status="accepted", expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
        else:
            db.add(TravelInboxAssignment(item_id=item.id, user_id=user.id, passenger_name="Taylor Reed"))
        db.flush()
    else:
        duplicate = source("sun-update-3")
        duplicate["id"] = "competing-notice"
        if protection == "competing_booking":
            duplicate["text"] = duplicate["text"].replace("SZ4K8P", "YY4K8P")
        else:
            duplicate["text"] += "\nPassenger name: Taylor Reed\n"
        process(db, user, duplicate)
    process(db, user, source("sun-survey"))
    assert db.query(Segment).count() == 0
    assert not recovery.evaluate(db, user.id, flight).allowed


def test_current_zero_evidence_marker_withdraws_old_source_authority(account):
    db, user = account
    run_case(db, user, "sun-explicit-post-travel")
    before = [(row.id, identity(row)) for row in db.query(Segment)]
    changed = source("sun-survey")
    changed["text"] = "A generic travel offer."
    process(db, user, changed)
    changed = source("sun-survey-reminder")
    changed["text"] = "A generic travel offer."
    process(db, user, changed)
    _, flight = target(db)
    assert not recovery.evaluate(db, user.id, flight).allowed
    assert [(row.id, identity(row)) for row in db.query(Segment)] == before


def test_feature_flag_is_explicitly_opt_in(monkeypatch):
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", "1")
    monkeypatch.delenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", raising=False)
    assert not recovery.enabled(1)
    monkeypatch.setenv("CARRIER_TRAVEL_CORROBORATION_ENABLED", "1")
    assert recovery.enabled(1)
    assert not recovery.enabled()


def test_removing_account_from_rollout_preserves_recovered_flights_and_evidence(account, monkeypatch):
    db, user = account
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", str(user.id))
    run_case(db, user, "sun-explicit-post-travel")
    db.flush()
    before = [(row.id, row.trip_id, identity(row), deepcopy(row.meta_json)) for row in db.query(Segment)]
    evidence = [(row.id, deepcopy(row.facts)) for row in db.query(CarrierTravelEvidence)]
    _, flight = target(db)
    assert recovery.evaluate(db, user.id, flight).allowed
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", str(user.id + 100))
    assert not recovery.evaluate(db, user.id, flight).allowed
    assert recovery.reconcile(db, user.id, db.query(CarrierTravelEvidence).all()).inserted == 0
    assert recovery.record_payload(db, user.id, {}) == []
    assert [(row.id, row.trip_id, identity(row), deepcopy(row.meta_json)) for row in db.query(Segment)] == before
    assert [(row.id, deepcopy(row.facts)) for row in db.query(CarrierTravelEvidence)] == evidence
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", str(user.id))
    assert recovery.evaluate(db, user.id, flight).allowed


@pytest.mark.parametrize("protection", ["named_other", "cancellation", "manual", "share"])
def test_protected_return_anchor_cannot_authorize_outbound(account, protection):
    db, user = account
    for key in ["aa-connection", "aa-gate-update", "aa-checkin", "aa-return"]:
        process(db, user, source(key))
    observation, flight = target(db, "aa-checkin")
    if protection == "named_other":
        from app.services.parser import ParseResult
        flight.ownership = "other"
        flight.passenger_names = ["Taylor Reed"]
        flight.passenger_evidence = [{"name": "Taylor Reed", "role": "traveler", "applies": True,
                                     "complete": True, "source": "text_passenger_label",
                                     "scope": {"pnr": flight.pnr, "flight_number": flight.flight_number}}]
        apply_booking_message(db, user.id, ParseResult(flights=[flight]), source_message_id="return-named-other",
                              received_at=flight.source_received_at)
    elif protection == "cancellation":
        from app.services.booking_ledger import record_cancellation
        record_cancellation(db, user.id, flight.pnr, source_message_id="return-cancel",
                            source_event_at=flight.source_received_at, flights=[flight])
    elif protection == "manual":
        from app.services.booking_ledger import record_user_decision
        record_user_decision(db, user.id, flight, ownership="other", status="active")
    else:
        from app.models import FlightShare, TravelInboxEvidence, TravelInboxItem
        item = db.query(TravelInboxItem).join(TravelInboxEvidence).filter(TravelInboxEvidence.observation_id == observation.id).first()
        db.add(FlightShare(sender_id=user.id, recipient_email="other@example.test", passenger_name="Maya Vale",
                client_request_id="return-share", request_hash="x", token_hash="y", token_encrypted=b"fixture", item_ids=[item.id],
                flights=[], status="accepted", expires_at=datetime.now(timezone.utc) + timedelta(days=1)))
        db.flush()
    process(db, user, source("aa-survey"))
    assert db.query(Segment).count() == 0


def test_two_typed_personal_names_do_not_outvote_conflict(account):
    db, user = account
    process(db, user, source("sun-update-3"))
    changed = source("sun-update-2")
    changed["text"] = changed["text"].replace("Maya Vale", "Taylor Reed")
    process(db, user, changed)
    process(db, user, source("sun-survey"))
    assert db.query(Segment).count() == 0


def test_same_time_conflicting_schedule_is_not_order_tiebroken(account):
    db, user = account
    process(db, user, source("sun-update-3"))
    changed = source("sun-update-3")
    changed["id"] = "same-time-conflict"
    changed["text"] = changed["text"].replace("11:00AM", "11:30AM").replace("3:20PM", "3:50PM")
    process(db, user, changed)
    process(db, user, source("sun-survey"))
    assert db.query(Segment).count() == 0


@pytest.mark.parametrize("change", ["hash", "name", "ids", "version"])
def test_corrupt_current_marker_or_index_never_supplies_authority(account, change):
    db, user = account
    run_case(db, user, "sun-explicit-post-travel")
    _, flight = target(db)
    if change == "name":
        for row in db.query(CarrierTravelEvidence).filter_by(kind="post_travel"):
            row.name = "Taylor"
    else:
        for message in db.query(Message).filter(Message.provider_msg_id.in_(["sun-survey", "sun-survey-reminder"])):
            marker = deepcopy(message.parse_evidence)
            if change == "hash":
                marker[recovery.MARKER]["source_sha256"] = "0" * 64
            elif change == "ids":
                marker[recovery.MARKER]["evidence_ids"] = None
            else:
                marker[recovery.MARKER]["version"] += 1
            message.parse_evidence = marker
    db.flush()
    assert not recovery.evaluate(db, user.id, flight).allowed


def test_older_observation_revision_cannot_use_current_source_marker(account):
    db, user = account
    run_case(db, user, "sun-explicit-post-travel")
    _, flight = target(db)
    flight.parser_version -= 1
    assert recovery.evaluate(db, user.id, flight).reason == "target_observation_not_current"


def test_recovered_leg_does_not_clear_a_message_with_another_unresolved_leg(account):
    db, user = account
    process(db, user, source("sun-update-3"))
    observation, flight = target(db)
    from app.services.booking_ledger import record_flight_observations
    from app.services.flight_times import normalize_flight_times
    flight.arr_airport = "MIA"
    flight.time_provenance = None
    normalize_flight_times(flight)
    record_flight_observations(db, user.id, [flight], source_message_id="sun-update-3", source_event_at=observation.source_event_at)
    process(db, user, source("sun-survey"))
    message = db.query(Message).filter_by(provider_msg_id="sun-update-3").one()
    assert db.query(Segment).count() == 1
    assert message.status == MessageStatus.REVIEW_REQUIRED
    assert message.parse_error == "passenger_identity_unresolved"


def test_city_label_requires_matching_region_and_city_without_substring_guessing():
    assert recovery._label_matches("Dallas/Ft. Worth, TX", "DFW")
    assert recovery._label_matches("Punta Cana, Dominican Republic", "PUJ")
    assert not recovery._label_matches("Dallas/Ft. Worth, MN", "DFW")
    assert not recovery._label_matches("Dallas", "DFW")
    assert not recovery._label_matches("Punta Cana, Mexico", "PUJ")


def test_valid_survey_is_processed_support_not_an_itinerary_parse_error(account):
    db, user = account
    process(db, user, source("aa-survey"))
    message = db.query(Message).filter_by(provider_msg_id="aa-survey").one()
    assert message.status == MessageStatus.ACCEPTED and message.ignored
    assert message.parse_error == "carrier_travel_assertion_retained"
    assert message.parse_evidence["resolved"] is True
    assert message.parse_evidence[recovery.MARKER]["analyzed_no_flights"] is True
    assert db.query(Segment).count() == 0


def test_unauthenticated_survey_does_not_gain_success_classification(account):
    db, user = account
    payload, _, _ = process(db, user, source("aa-survey"), authentication=False)
    message = db.query(Message).filter_by(provider_msg_id="aa-survey").one()
    message.status = MessageStatus.REVIEW_REQUIRED
    message.parse_error = "strong_flight_evidence_but_no_segments"
    recovery.record_payload(db, user.id, payload)
    assert message.status == MessageStatus.REVIEW_REQUIRED
    assert not message.ignored
    assert message.parse_error != "carrier_travel_assertion_retained"
    assert message.parse_evidence[recovery.MARKER]["analyzed_no_flights"] is True
    assert not message.parse_evidence[recovery.MARKER]["evidence_ids"]


def test_existing_manually_owned_bilt_flights_survive_unrelated_corroboration(account):
    db, user = account
    value = source("bilt-confirmed-own")
    process(db, user, value)
    from app.services.booking_ledger import record_user_decision
    for observation in db.query(BookingObservation).filter_by(source_message_id=value["id"]).all():
        flight = _retained_flight(observation)
        record_user_decision(db, user.id, flight, ownership="self", status="active")
    process(db, user, value)
    before = [(row.id, row.trip_id, identity(row)) for row in db.query(Segment).order_by(Segment.dep_time)]
    assert len(before) == 4
    process(db, user, source("aa-other-survey"))
    process(db, user, source("bilt-other-return"))
    process(db, user, value)
    assert [(row.id, row.trip_id, identity(row)) for row in db.query(Segment).order_by(Segment.dep_time)] == before


def test_evidence_overflow_does_not_choose_first_plausible_rows(account):
    db, user = account
    run_case(db, user, "sun-explicit-post-travel")
    _, flight = target(db)
    original = db.query(CarrierTravelEvidence).first()
    for index in range(recovery.LIMIT):
        data = {column.name: getattr(original, column.name) for column in original.__table__.columns
                if column.name not in {"id", "created_at", "evidence_key"}}
        db.add(CarrierTravelEvidence(evidence_key=f"overflow-{index}", **data))
    db.flush()
    assert recovery.evaluate(db, user.id, flight).reason == "carrier_evidence_limit"


def test_survey_sent_before_flight_completion_cannot_confirm_travel(account):
    db, user = account
    process(db, user, source("sun-update-3"))
    early = source("sun-survey")
    early["received_at"] = "2027-03-11T16:00:00Z"
    process(db, user, early)
    assert db.query(Segment).count() == 0


def test_one_given_name_is_not_the_aa_independent_personal_anchor(account):
    db, user = account
    for key in ["aa-connection", "aa-gate-update", "aa-checkin", "aa-return", "aa-survey"]:
        value = source(key)
        if key == "aa-checkin":
            value["text"] = value["text"].replace("Maya June Ms", "Maya Ms")
        process(db, user, value)
    assert db.query(Segment).count() == 0


def test_later_forged_authentication_header_cannot_override_gmail_failure(account):
    db, user = account
    raw = gmail_message(source("aa-survey"))
    valid = raw["payload"]["headers"][-1]["value"]
    raw["payload"]["headers"][-1]["value"] = "mx.google.com; dkim=fail; dmarc=fail"
    raw["payload"]["headers"].append({"name": "Authentication-Results", "value": valid})
    payload = prepare_flight_message(raw, user_name=user.name, aliases=user.travel_name_aliases)
    db.add(Message(user_id=user.id, provider_msg_id=raw["id"], parse_version=PARSER_VERSION, status=MessageStatus.ACCEPTED))
    db.flush()
    assert recovery.record_payload(db, user.id, payload) == []


@pytest.mark.parametrize("reason", ["ambiguous_cancellation_scope", "ambiguous_cancellation_time",
                                    "unresolved_cancellation_scope", "cancellation_document_requires_review"])
def test_signed_survey_does_not_override_unresolved_cancellation_state(account, reason):
    db, user = account
    process(db, user, source("sun-update-3"))
    value = source("sun-survey")
    payload = prepare_flight_message(gmail_message(value), user_name=user.name, aliases=user.travel_name_aliases)
    message = Message(user_id=user.id, provider_msg_id=value["id"], status=MessageStatus.REVIEW_REQUIRED,
                      parse_version=PARSER_VERSION, parse_error=reason)
    db.add(message); db.flush()
    rows = recovery.record_payload(db, user.id, payload)
    assert rows == []
    assert message.status == MessageStatus.REVIEW_REQUIRED and message.parse_error == reason
    assert not message.parse_evidence[recovery.MARKER]["analyzed_no_flights"]
    _, flight = target(db)
    assert not recovery.evaluate(db, user.id, flight).allowed
    assert db.query(Segment).count() == 0


def test_changed_cancellation_state_withdraws_previous_survey_authority(account):
    db, user = account
    run_case(db, user, "sun-explicit-post-travel")
    for row in db.query(Message).filter(Message.provider_msg_id.in_(["sun-survey", "sun-survey-reminder"])):
        row.status, row.parse_error = MessageStatus.REVIEW_REQUIRED, "unresolved_cancellation_scope"
    db.flush()
    _, flight = target(db)
    assert not recovery.evaluate(db, user.id, flight).allowed


@pytest.mark.parametrize("case_key,anchor_id", [
    ("sun-explicit-post-travel", "sun-update-3"),
    ("aa-connecting-and-return", "aa-connection"),
    ("aa-connecting-and-return", "aa-checkin"),
])
@pytest.mark.parametrize("ownership", ["other", "unknown"])
def test_separate_original_booking_outside_typed_templates_blocks_survey(account, case_key, anchor_id, ownership):
    db, user = account
    case = next(value for value in fixture()["positive_cases"] if value["id"] == case_key)
    messages = [source(key) for key in case["sources"]]
    for value in sorted(messages, key=lambda value: value["received_at"]):
        if "survey" not in value["id"]:
            process(db, user, value)
    from app.services.parser import ParseResult
    _, flight = target(db, anchor_id)
    flight.pnr, flight.ownership = "XX4K8P", ownership
    flight.passenger_names = ["Taylor Reed"] if ownership == "other" else []
    flight.passenger_evidence = [{"name": "Taylor Reed", "role": "traveler", "applies": True,
        "complete": True, "source": "text_passenger_label", "scope": {
            "pnr": flight.pnr, "flight_number": flight.flight_number}}] if ownership == "other" else []
    source_id = "separate-original-receipt"
    apply_booking_message(db, user.id, ParseResult(flights=[flight]), source_message_id=source_id,
                          received_at=flight.source_received_at)
    db.add(Message(user_id=user.id, provider_msg_id=source_id, parse_version=PARSER_VERSION,
                   status=MessageStatus.ACCEPTED))
    db.flush()
    assert not db.query(CarrierTravelEvidence).filter_by(source_message_id=source_id).count()
    for value in messages:
        if "survey" in value["id"]:
            process(db, user, value)
    assert db.query(Segment).count() == 0
    for value in messages:
        if "survey" not in value["id"]:
            _, original = target(db, value["id"])
            assert not recovery.evaluate(db, user.id, original).allowed


def test_confirmed_own_separate_booking_survives_ambiguous_survey(account):
    db, user = account
    process(db, user, source("sun-update-3"))
    from app.services.parser import ParseResult
    _, flight = target(db)
    flight.pnr, flight.ownership = "XX4K8P", "self"
    flight.passenger_names = ["Maya Reed"]
    flight.passenger_evidence = [{"name": "Maya Reed", "role": "traveler", "applies": True,
        "complete": True, "source": "text_passenger_label", "scope": {
            "pnr": flight.pnr, "flight_number": flight.flight_number}}]
    apply_booking_message(db, user.id, ParseResult(flights=[flight]), source_message_id="own-original-receipt",
                          received_at=flight.source_received_at)
    db.add(Message(user_id=user.id, provider_msg_id="own-original-receipt", parse_version=PARSER_VERSION,
                   status=MessageStatus.ACCEPTED))
    db.flush()
    before = [(row.id, row.trip_id, row.pnr, identity(row)) for row in db.query(Segment)]
    assert len(before) == 1
    process(db, user, source("sun-survey"))
    assert [(row.id, row.trip_id, row.pnr, identity(row)) for row in db.query(Segment)] == before
    _, original = target(db)
    assert recovery.evaluate(db, user.id, original).reason == "competing_original_booking"


@pytest.mark.parametrize("case_key,survey_id", [
    ("sun-explicit-post-travel", "sun-survey"),
    ("aa-connecting-and-return", "aa-survey"),
])
@pytest.mark.parametrize("conflict", ["same_scope", "different_day", "different_route"])
def test_conflicting_named_survey_cannot_be_outvoted_but_unrelated_survey_is_harmless(account, case_key, survey_id, conflict):
    db, user = account
    case = next(value for value in fixture()["positive_cases"] if value["id"] == case_key)
    messages = [source(key) for key in case["sources"]]
    for value in sorted(messages, key=lambda value: value["received_at"]):
        if "survey" not in value["id"]:
            process(db, user, value)
    other = source(survey_id)
    other["id"] = "other-traveler-survey"
    other["subject"] = other["subject"].replace("MAYA", "TAYLOR").replace("Maya", "Taylor")
    other["text"] = other["text"].replace("Maya", "Taylor").replace("MAYA", "TAYLOR")
    if conflict == "different_day":
        other["text"] = other["text"].replace("March 11", "March 10").replace("February 10", "February 9")
    elif conflict == "different_route":
        other["text"] = other["text"].replace("Cancun, Mexico", "Cozumel, Mexico").replace("to NAS", "to MEX")
    _, rows, _ = process(db, user, other)
    assert any(row.kind == "post_travel" and "TAYLOR" in row.name.upper() for row in rows)
    for value in messages:
        if "survey" in value["id"]:
            process(db, user, value)
    expected = 0 if conflict == "same_scope" else len(case["expected_legs"])
    assert db.query(Segment).count() == expected
