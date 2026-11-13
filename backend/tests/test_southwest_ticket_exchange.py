"""Named issued-ticket change receipts retire only their exact prior booking leg."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import permutations

import pytest

from app.models import BookingObservation, ItineraryHistory, Segment, Trip, User
from app.services.booking_import import apply_booking_message
from app.services.booking_ledger import flight_facts
from app.services.booking_legacy_repair import _state
from app.services.flight_times import normalize_flight_times
from app.services.parser import ParsedFlight, ParseResult
from app.services.southwest_ticket_revision import extract, supersedes
from test_booking_lifecycle_hardening import db_user


def receipt(new=False):
    airport, number, dep, arr = ("HOU", "18", "10:30", "11:40") if new else ("BNA", "2890", "14:15", "16:05")
    ticket = "5261234567891" if new else "5261234567890"
    printed_dep = datetime.strptime(dep,"%H:%M").strftime("%I:%M\n%p")
    printed_arr = datetime.strptime(arr,"%H:%M").strftime("%I:%M\n%p")
    text = f"""Southwest Airlines
{'We have a confirmed reservation.' if not new else "We've confirmed the change to your trip. Here is your updated itinerary."}
Confirmation #
ROUND1
PASSENGER
RAPID REWARDS #
TICKET #
Alex Morgan
{ticket}
Your itinerary
Flight:
Thursday, 05/20/2027
FLIGHT
# {number}
DEPARTS
{airport} {printed_dep}
ARRIVES
DAL {printed_arr}
Payment information
{f'Credit from ticket: #5261234567890 to #{ticket}' if new else 'Payment confirmed.'}
"""
    flight = ParsedFlight(airport, "DAL", datetime.fromisoformat(f"2027-05-20T{dep}:00+00:00"),
        datetime.fromisoformat(f"2027-05-20T{arr}:00+00:00"), airline="WN", flight_number="WN"+number,
        pnr="ROUND1", source="shape_southwest_itinerary_blocks", ownership="self",
        passenger_names=["Alex Morgan"], passenger_evidence=[{"name":"Alex Morgan", "source":"text_passenger_label",
            "role":"traveler", "complete":True, "scope":{"pnr":"ROUND1"}, "applies":True, "scope_ambiguous":False}])
    normalize_flight_times(flight)
    return text, flight


def apply(db, user, kind):
    text, flight = receipt(kind in {"new", "new-reminder"})
    subject = "Your change is confirmed" if kind == "new" else "Your flight confirmation"
    if "reminder" in kind:
        text, subject = "Your complete itinerary.", "Your trip is almost here!"
    at = {"old":"2027-05-01T12:00:00Z", "new":"2027-05-03T12:00:00Z",
          "old-reminder":"2027-05-04T12:00:00Z", "new-reminder":"2027-05-05T12:00:00Z"}[kind]
    return apply_booking_message(db,user.id,ParseResult(flights=[flight]),source_message_id=kind,
        subject=subject,plain_text=text,received_at=at)


def legacy(db,user,*,wall_clocks=False):
    _, flight = receipt()
    dep, arr = flight.dep_time, flight.arr_time
    if wall_clocks:
        dep, arr = (datetime.fromisoformat(flight.time_provenance[k]["local"]) for k in ("departure","arrival"))
    trip = Trip(user_id=user.id,title="Existing journey",start_ts=dep,end_ts=arr)
    db.add(trip);db.flush()
    segment = Segment(trip_id=trip.id,mode="flight",dep_airport="BNA",arr_airport="DAL",dep_time=dep,arr_time=arr,
        airline="WN",flight_number="WN2890",pnr="ROUND1",meta_json={"source":"heuristic","source_received_at":"2027-05-02T12:00:00+00:00"})
    db.add(segment);db.flush()
    return segment


@pytest.fixture(autouse=True)
def gate(monkeypatch):
    monkeypatch.setattr("app.services.booking_ticket_lifecycle.enabled",lambda uid:True)


def test_exact_ticket_chain_uses_hashed_identifiers_and_predeparture_events():
    facts=[]
    for new in (False,True):
        text,flight=receipt(new);flight.booking_ticket=extract("Your flight receipt",text,[flight])
        assert flight.booking_ticket
        assert "526123456789" not in str(flight.booking_ticket)
        facts.append(flight_facts(flight))
    assert supersedes(*facts,previous_event_at="2027-05-01T12:00:00Z",successor_event_at="2027-05-03T12:00:00Z")
    assert not supersedes(*facts,previous_event_at=None,successor_event_at="2027-05-03T12:00:00Z")
    assert not supersedes(*facts,previous_event_at="2027-05-03T12:00:00Z",successor_event_at="2027-05-01T12:00:00Z")
    assert not supersedes(*facts,previous_event_at="2027-05-01T12:00:00Z",successor_event_at="2027-05-21T12:00:00Z")


@pytest.mark.parametrize("mutation", ["credit_only","wrong_ticket","same_ticket","second_person","incomplete_name","second_leg","wrong_date","no_name","wrong_pnr","not_normalized"])
def test_incomplete_or_ambiguous_receipts_supply_no_exchange_authority(mutation):
    text,flight=receipt(True);flights=[flight]
    if mutation=="credit_only":text=text.replace("We've confirmed the change to your trip.","Your reservation details.")
    if mutation=="wrong_ticket":text=text.replace("to #5261234567891","to #5261234567892")
    if mutation=="same_ticket":text=text.replace("from ticket: #5261234567890","from ticket: #5261234567891")
    if mutation=="second_person":text=text.replace("Your itinerary","PASSENGER\nAnother Person\n5261234567892\nYour itinerary")
    if mutation=="incomplete_name":flight.passenger_evidence[0]["complete"]=False
    if mutation=="second_leg":flights.append(deepcopy(flight))
    if mutation=="wrong_date":text=text.replace("05/20/2027","05/21/2027")
    if mutation=="no_name":text=text.replace("Alex Morgan","Friendly greeting")
    if mutation=="wrong_pnr":text=text.replace("ROUND1","ROUND2")
    if mutation=="not_normalized":flight.time_provenance={}
    assert extract("Your change is confirmed",text,flights) is None


@pytest.mark.parametrize("order",list(permutations(("old","new","old-reminder"))))
@pytest.mark.parametrize("baseline",[None,"normalized","wall"])
def test_exact_exchange_and_reminders_converge_in_every_source_order(db_user,order,baseline):
    db,user=db_user
    old_id=legacy(db,user,wall_clocks=baseline=="wall").id if baseline else None
    other_state = None
    if baseline:
        # PostgreSQL sequences never reuse the retired ID. Keep an unrelated
        # account row in this SQLite fixture to exercise the same property.
        other = User(name="Other Traveler",email="sequence-control@example.test")
        db.add(other);db.flush();legacy(db,other)
        other_state = deepcopy(_state(db,other.id))
    for kind in order:apply(db,user,kind)
    apply(db,user,"new-reminder")
    rows=db.query(Segment).join(Trip).filter(Trip.user_id==user.id).all()
    assert len(rows)==1 and rows[0].flight_number=="WN18" and rows[0].dep_airport=="HOU"
    if old_id:
        assert db.get(Segment,old_id) is None
        assert db.query(ItineraryHistory).filter_by(entity_type="ticket_exchange",entity_id=old_id).count()==1
    observation_state=deepcopy(_state(db,user.id)["observations"])
    for kind in reversed(order):apply(db,user,kind)
    stable=deepcopy(_state(db,user.id))
    for _ in range(3):
        for kind in order:apply(db,user,kind)
        apply(db,user,"new-reminder")
        assert _state(db,user.id)==stable
    assert all(stable["observations"][key]==value for key,value in observation_state.items())
    if other_state is not None:
        assert _state(db,other.id)==other_state


@pytest.mark.parametrize("order",[("old","new"),("new","old")])
def test_disabled_reconciliation_holds_only_explicit_exchange_and_preserves_old_flow(db_user,monkeypatch,order):
    db,user=db_user
    monkeypatch.setattr("app.services.booking_ticket_lifecycle.enabled",lambda uid:False)
    outcomes={kind:apply(db,user,kind) for kind in order}
    assert outcomes["new"].review_reason=="ticket_reconciliation_not_enabled"
    assert [r.flight_number for r in db.query(Segment)]==["WN2890"]
    assert db.query(BookingObservation).count()==2
    assert all(r.facts.get("booking_ticket") for r in db.query(BookingObservation))
    monkeypatch.setattr("app.services.booking_ticket_lifecycle.enabled",lambda uid:True)
    for kind in order:apply(db,user,kind)
    assert [r.flight_number for r in db.query(Segment)]==["WN18"]


@pytest.mark.parametrize("protection",["manual","user_review","accepted_flight_share","flight_share","personal_note","manually_edited","public","unlisted","manual_grouping","trip_grouping_locked"])
def test_exchange_never_retires_protected_original(db_user,protection):
    db,user=db_user
    old=legacy(db,user,wall_clocks=True);trip=db.get(Trip,old.trip_id)
    if protection in {"public","unlisted"}:trip.visibility=protection
    elif protection in {"manual","user_review","accepted_flight_share","flight_share"}:old.meta_json={**old.meta_json,"source":protection}
    else:old.meta_json={**old.meta_json,protection:True}
    db.flush();before=deepcopy(_state(db,user.id))
    for _ in range(3):
        apply(db,user,"new");apply(db,user,"old")
        assert db.get(Segment,old.id) is not None
        assert _state(db,user.id)["segments"][str(old.id)]==before["segments"][str(old.id)]
        if protection in {"public","unlisted","manual_grouping","trip_grouping_locked"}:
            assert _state(db,user.id)["trips"][str(trip.id)]==before["trips"][str(trip.id)]


@pytest.mark.parametrize("mutation",["adjacent_date","one_clock","duplicate","alias","newer_event","different_account"])
def test_legacy_binding_requires_one_exact_unprotected_candidate(db_user,mutation):
    db,user=db_user;old=legacy(db,user,wall_clocks=True)
    if mutation=="adjacent_date":old.dep_time+=timedelta(days=1);old.arr_time+=timedelta(days=1)
    if mutation=="one_clock":old.arr_time+=timedelta(minutes=1)
    if mutation=="alias":old.meta_json={**old.meta_json,"pnr_aliases":["OTHER1"]}
    if mutation=="newer_event":old.meta_json={**old.meta_json,"source_received_at":"2027-05-04T12:00:00Z"}
    if mutation=="different_account":
        other=User(name=user.name,email="another@example.test");db.add(other);db.flush();db.get(Trip,old.trip_id).user_id=other.id
    if mutation=="duplicate":
        second=legacy(db,user,wall_clocks=True)
        assert second.id!=old.id
    db.flush()
    # New-first prevents a normal older import from enriching/reinterpreting the
    # deliberately ambiguous legacy row before the exchange binding is checked.
    apply(db,user,"new");apply(db,user,"old")
    assert db.get(Segment,old.id) is not None


def test_later_independent_confirmation_is_not_retired_as_old_ticket(db_user):
    db,user=db_user
    apply(db,user,"old")
    old=db.query(Segment).one();old_id=old.id
    text,flight=receipt();text=text.replace("5261234567890","5261234567893")
    apply_booking_message(db,user.id,ParseResult(flights=[flight]),source_message_id="later-purchase",
        subject="Your flight confirmation",plain_text=text,received_at="2027-05-04T12:00:00Z")
    apply(db,user,"new")
    assert db.get(Segment,old_id) is not None


@pytest.mark.parametrize("order",[("old","new"),("new","old")])
def test_previous_parser_same_originals_gain_ticket_proof_without_losing_old_observations(db_user,monkeypatch,order):
    from app.services import southwest_ticket_revision
    db,user=db_user
    extractor=southwest_ticket_revision.extract
    monkeypatch.setattr(southwest_ticket_revision,"extract",lambda *args:None)
    apply(db,user,"old");apply(db,user,"old-reminder")
    original=deepcopy(_state(db,user.id)["observations"])
    assert all(not row["facts"].get("booking_ticket") for row in original.values())
    monkeypatch.setattr(southwest_ticket_revision,"extract",extractor)
    for kind in order:apply(db,user,kind)
    assert [row.flight_number for row in db.query(Segment)]==["WN18"]
    current=_state(db,user.id)
    assert all(current["observations"][key]==value for key,value in original.items())


@pytest.mark.parametrize("mutation",["bool_version","bad_hash","bad_airport","wrong_airline","wrong_own_clock","bad_time_endpoint","bool_time_version","other_person","other_pnr","unknown","review"])
def test_retained_malformed_or_different_identity_facts_never_grant_ticket_authority(mutation):
    facts=[]
    for new in (False,True):
        text,flight=receipt(new);flight.booking_ticket=extract("Receipt",text,[flight]);facts.append(flight_facts(flight))
    target=facts[1]
    if mutation=="bool_version":target["booking_ticket"]["version"]=True
    if mutation=="bad_hash":target["booking_ticket"]["ticket_key"]="wrong"
    if mutation=="bad_airport":target["booking_ticket"]["legs"][0]["dep_airport"]=["HOU"]
    if mutation=="wrong_airline":target["airline"]="UA"
    if mutation=="wrong_own_clock":target["arr_time"]="2027-05-20T16:41:00Z"
    if mutation=="bad_time_endpoint":target["time_provenance"]["departure"]=["invalid"]
    if mutation=="bool_time_version":target["time_provenance"]["version"]=True
    if mutation=="other_person":target["passenger_evidence"][0]["name"]="Another Traveler"
    if mutation=="other_pnr":target["pnr"]="OTHER1"
    if mutation=="unknown":target["ownership"]="unknown"
    if mutation=="review":target["force_review"]=True
    assert not supersedes(*facts,previous_event_at="2027-05-01T12:00:00Z",successor_event_at="2027-05-03T12:00:00Z")


def test_conflicting_carrier_field_cannot_extract_southwest_ticket_authority():
    text, flight = receipt(True)
    flight.airline = "UA"
    assert extract("Receipt", text, [flight]) is None


def competing(db, user, kind, *, same_route=False, wrong_previous=False, reminder_shift=0, unknown_confirmation=False):
    from app.services.booking_projection_context import projection_run
    text, flight = receipt(kind != "old")
    if kind == "unknown_reminder":
        flight.ownership = "unknown"
        flight.passenger_names = []
        flight.passenger_evidence = []
        text = "Your complete itinerary is below."
        if reminder_shift:
            flight.dep_time += timedelta(minutes=reminder_shift)
            flight.arr_time += timedelta(minutes=reminder_shift)
            for endpoint in ("departure", "arrival"):
                for key in ("original", "local", "utc"):
                    flight.time_provenance[endpoint][key] = (datetime.fromisoformat(
                        flight.time_provenance[endpoint][key]) + timedelta(minutes=reminder_shift)).isoformat()
    if kind == "independent":
        text = text.replace("5261234567891", "5261234567893")
        text = text.replace("We've confirmed the change to your trip. Here is your updated itinerary.", "Your new reservation is confirmed.")
        text = text.replace("Credit from ticket: #5261234567890 to #5261234567893", "Payment confirmed.")
    if kind == "newB":
        text = text.replace("5261234567891", "5261234567892").replace("# 18", "# 19")
        flight.flight_number = "WN19"
        if not same_route:
            text = text.replace("HOU", "AUS")
            flight.dep_airport = "AUS"
            flight.time_provenance["departure"]["airport"] = "AUS"
        if wrong_previous:
            text = text.replace("from ticket: #5261234567890", "from ticket: #5261234567899")
    with projection_run(db, user.id):
        result = apply_booking_message(db, user.id, ParseResult(flights=[flight]),
            source_message_id=kind, subject=("Your flight confirmation" if unknown_confirmation else "Your trip is almost here!") if kind == "unknown_reminder" else
                "Your change is confirmed" if kind in {"newA", "newB"} else "Your flight confirmation",
            plain_text=text, received_at={"old":"2027-05-01T12:00:00Z", "newA":"2027-05-03T12:00:00Z",
                                          "newB":"2027-05-04T12:00:00Z", "unknown_reminder":"2027-05-05T12:00:00Z",
                                          "independent":"2027-05-06T12:00:00Z"}[kind])
    db.flush()
    return result


@pytest.mark.parametrize("order", list(permutations(("old", "newA", "newB"))))
@pytest.mark.parametrize("baseline", [False, True])
def test_competing_successors_hold_only_new_projections_without_restoring_old_ticket(db_user, order, baseline):
    db, user = db_user
    if baseline:
        legacy(db, user, wall_clocks=True)
    for kind in order:
        outcome = competing(db, user, kind)
    assert db.query(Segment).count() == 0
    assert db.query(Trip).count() == 0
    assert outcome.canceled == 0
    assert outcome.review_reason == "competing_ticket_successors"
    assert db.query(BookingObservation).count() == 3
    immutable = deepcopy(_state(db, user.id)["observations"])
    stable = _state(db, user.id)
    for _ in range(3):
        for kind in reversed(order):
            assert competing(db, user, kind).review_reason == "competing_ticket_successors"
        assert _state(db, user.id) == stable
        assert _state(db, user.id)["observations"] == immutable


@pytest.mark.parametrize("order", list(permutations(("old", "newA", "newB"))))
def test_same_route_later_schedule_is_not_a_competing_route_conflict(db_user, order):
    db, user = db_user
    for kind in order:
        outcome = competing(db, user, kind, same_route=True)
        assert outcome.review_reason != "competing_ticket_successors"
    assert [row.flight_number for row in db.query(Segment)] == ["WN19"]


@pytest.mark.parametrize("protection", ["baseline", "public", "manual", "flight_share"])
def test_competing_successors_preserve_adopted_or_protected_projection_with_conflict(db_user, protection):
    db, user = db_user
    competing(db, user, "newA")
    row = db.query(Segment).one()
    if protection == "baseline":
        meta = dict(row.meta_json); meta.pop("booking_projection_creation")
        row.meta_json = meta
    elif protection == "public":
        db.get(Trip, row.trip_id).visibility = "public"
    else:
        row.meta_json = {**row.meta_json, "source": protection}
    db.flush()
    original = deepcopy(_state(db, user.id)["segments"][str(row.id)])
    for kind in ("old", "newB"):
        competing(db, user, kind)
    current = _state(db, user.id)["segments"][str(row.id)]
    assert {k:v for k,v in current.items() if k != "meta_json"} == {k:v for k,v in original.items() if k != "meta_json"}
    assert current["meta_json"]["booking_conflicts"][0]["reason"] == "competing_ticket_successors"
    assert db.query(Segment).count() == 1
    before_capture = _state(db, user.id)
    for kind in ("newB", "newA", "old"):
        competing(db, user, kind)
    after_capture = _state(db, user.id)
    assert {k:v for k,v in before_capture.items() if k != "history"} == {
        k:v for k,v in after_capture.items() if k != "history"}
    assert all(after_capture["history"][key] == value for key,value in before_capture["history"].items())
    for key in after_capture["history"].keys() - before_capture["history"].keys():
        history = after_capture["history"][key]
        assert history["entity_type"] in {"trip", "segment"}
        assert history["snapshot"] == before_capture[history["entity_type"] + "s"][str(history["entity_id"])]
    stable = _state(db, user.id)
    for _ in range(3):
        for kind in ("newB", "newA", "old"):
            competing(db, user, kind)
        assert _state(db, user.id) == stable


def test_different_previous_ticket_cannot_create_competing_exchange_authority(db_user):
    db, user = db_user
    for kind in ("old", "newA", "newB"):
        outcome = competing(db, user, kind, wrong_previous=True)
        assert outcome.review_reason != "competing_ticket_successors"
    assert db.query(Segment).count() == 2


@pytest.mark.parametrize("order", list(permutations(("old", "newA", "newB", "unknown_reminder"))))
@pytest.mark.parametrize("variant", ["operational", "shifted_operational", "confirmation"])
def test_unknown_corroboration_keeps_immutable_identity_without_reinstating_competing_ticket(db_user, order, variant):
    db, user = db_user
    for kind in order:
        competing(db, user, kind, reminder_shift=5 if variant == "shifted_operational" else 0,
                  unknown_confirmation=variant == "confirmation")
    assert db.query(Segment).count() == db.query(Trip).count() == 0
    reminder = db.query(BookingObservation).filter_by(source_message_id="unknown_reminder").one()
    assert reminder.ownership == "unknown" and reminder.facts["ownership"] == "unknown"
    stable = _state(db, user.id)
    for _ in range(3):
        for kind in reversed(order):
            competing(db, user, kind, reminder_shift=5 if variant == "shifted_operational" else 0,
                      unknown_confirmation=variant == "confirmation")
        assert _state(db, user.id) == stable


def test_unknown_nonoperational_source_does_not_grant_independent_named_ticket_authority(db_user):
    db, user = db_user
    competing(db, user, "newA")
    text, flight = receipt(True)
    flight.ownership = "unknown"; flight.passenger_names = []; flight.passenger_evidence = []
    apply_booking_message(db, user.id, ParseResult(flights=[flight]), source_message_id="unknown-independent",
        subject="Your flight confirmation", plain_text="Your new reservation is confirmed.", received_at="2027-05-05T12:00:00Z")
    for kind in ("old", "newB"):
        competing(db, user, kind)
    assert db.query(Segment).count() == db.query(Trip).count() == 0
    assert db.query(BookingObservation).filter_by(source_message_id="unknown-independent").one().ownership == "unknown"


@pytest.mark.parametrize("order", list(permutations(("old", "newA", "newB", "independent"))))
def test_later_separately_issued_named_ticket_keeps_purchase_authority_after_competing_exchange(db_user, order):
    db, user = db_user
    for kind in order:
        competing(db, user, kind)
    rows = db.query(Segment).all()
    assert len(rows) == 1 and rows[0].flight_number == "WN18"
    assert db.query(Trip).count() == 1
    original = deepcopy(_state(db, user.id)["observations"])
    # Each captured row must have existed immediately around that import;
    # later snapshots cannot be excused as generic history churn.
    for replay_order in (tuple(reversed(order)), order):
        for kind in replay_order:
            before = _state(db, user.id)
            competing(db, user, kind)
            after = _state(db, user.id)
            assert all(after["history"][key] == value for key,value in before["history"].items())
            for key in after["history"].keys() - before["history"].keys():
                history = after["history"][key]
                assert history["entity_type"] in {"trip", "segment"}
                table, entity_id = history["entity_type"] + "s", str(history["entity_id"])
                assert history["snapshot"] in (before[table][entity_id], after[table][entity_id])
            assert after["observations"] == original
            assert after["trips"].keys() == before["trips"].keys()
            for key, trip in after["trips"].items():
                prior = before["trips"][key]
                assert {k:v for k,v in trip.items() if k != "title"} == {
                    k:v for k,v in prior.items() if k != "title"}
                if trip["title"] != prior["title"]:
                    assert (prior["title"], trip["title"]) == ("Houston", "Dallas")
            assert {key:{k:v for k,v in value.items() if k != "meta_json"} for key,value in after["segments"].items()} == {
                key:{k:v for k,v in value.items() if k != "meta_json"} for key,value in before["segments"].items()}
    stable = _state(db, user.id)
    assert stable["observations"] == original
    for _ in range(3):
        for kind in order:
            competing(db, user, kind)
        assert _state(db, user.id) == stable


@pytest.mark.parametrize("mutation", ["person", "pnr", "unknown_event", "inconsistent_row_scope", "same_ticket"])
def test_competing_guard_requires_same_named_previous_ticket_and_consistent_source_scope(mutation):
    from types import SimpleNamespace
    from app.services.booking_ticket_lifecycle import _competing_southwest_successors
    rows = []
    for index in range(3):
        text, flight = receipt(index != 0)
        if index == 2:
            text = text.replace("5261234567891", "5261234567892").replace("HOU", "AUS")
            flight.dep_airport = "AUS"
            flight.time_provenance["departure"]["airport"] = "AUS"
        flight.booking_ticket = extract("Receipt", text, [flight])
        facts = flight_facts(flight)
        rows.append(SimpleNamespace(id=index + 1, facts=facts, pnr="ROUND1", ownership="self",
            dep_airport=flight.dep_airport, arr_airport=flight.arr_airport, flight_number=flight.flight_number,
            travel_date="2027-05-20", source_event_at=f"2027-05-0{index+1}T12:00:00Z"))
    assert len(_competing_southwest_successors(rows)) == 1
    target = rows[2]
    if mutation == "person":
        target.facts["passenger_evidence"][0]["name"] = "Blair Morgan"
        target.facts["passenger_names"] = ["Blair Morgan"]
        target.facts["booking_ticket"]["passenger_name"] = "blair morgan"
    elif mutation == "pnr":
        target.pnr = target.facts["pnr"] = target.facts["booking_ticket"]["pnr"] = "OTHER1"
    elif mutation == "unknown_event":
        target.source_event_at = None
    elif mutation == "inconsistent_row_scope":
        target.travel_date = "2027-05-21"
    else:
        target.facts["booking_ticket"]["ticket_key"] = rows[1].facts["booking_ticket"]["ticket_key"]
    assert not _competing_southwest_successors(rows)
