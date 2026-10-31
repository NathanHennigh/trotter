"""Fresh-source replay must not erase legacy travel or guess booking identity."""
from copy import deepcopy
from html import escape

import pytest

from app.models import BookingObservation, MessageStatus, Segment, User
from app.services.booking_ledger import record_flight_observations, record_user_decision
from app.services.passenger_identity import apply_passenger_identity, names_match, _name
from test_legacy_local_clock_replay import account, apply, dt, flight, seed  # noqa: F401


def identify(value, printed, *, aliases=None):
    value.passenger_names = []
    value.passenger_evidence = []
    value.passenger_name = None
    apply_passenger_identity([value], html="", plain_text=f"Passenger: {printed}",
                             user_name="Alex Avery", aliases=aliases or [])
    return value


@pytest.mark.parametrize("printed", [
    "AVERY/ALEXJORDAN", "Avery, AlexJordan", "AlexJordan Avery", "AVERY/ALEXANDRA",
])
def test_compact_name_extension_is_unknown_not_self_or_definitely_other(printed):
    value = identify(flight(), printed)
    assert not names_match(printed, "Alex Avery")
    assert value.ownership == "unknown"
    assert value.passenger_names == [printed]
    assert value.passenger_evidence[0]["complete"]


@pytest.mark.parametrize("printed", ["AVERY/MORGAN", "OTHER/ALEXJORDAN", "Alex Avery Jr"])
def test_distinct_traveler_or_suffix_still_is_other(printed):
    assert identify(flight(), printed).ownership == "other"


def test_confirmed_full_middle_name_alias_resolves_compact_name():
    assert identify(flight(), "AVERY/ALEXJORDAN", aliases=["Alex Jordan Avery"]).ownership == "self"


def test_compact_middle_name_receipt_cannot_remove_existing_round_trip(account):
    db, user = account
    outbound = flight(pnr="ROUND1", dep="SFO", arr="EWR", number="UA2044",
                      departure="2019-03-27T15:00:00Z", arrival="2019-03-27T23:36:00Z")
    inbound = flight(pnr="ROUND1", dep="EWR", arr="SFO", number="UA1885",
                     departure="2019-04-01T16:00:00Z", arrival="2019-04-01T19:26:00Z")
    rows = [seed(db, user, value) for value in [outbound, inbound]]
    original = [(row.id, row.trip_id, row.dep_time, row.arr_time, row.pnr, deepcopy(row.meta_json)) for row in rows]
    values = [identify(value, "AVERY/ALEXJORDAN") for value in [outbound, inbound]]
    for _ in range(2):
        result = apply(db, user, values)
        assert result.build.removed_other == result.build.inserted == result.build.updated == 0
        assert result.build.held_unknown == 2
        assert result.status == MessageStatus.REVIEW_REQUIRED
        assert [(row.id, row.trip_id, row.dep_time, row.arr_time, row.pnr, row.meta_json)
                for row in db.query(Segment).order_by(Segment.id)] == original
    assert db.query(BookingObservation).count() == 2


def test_compact_ambiguous_name_may_use_independent_exact_booking_evidence(account):
    db, user = account
    value = flight()
    old = seed(db, user, value)
    record_flight_observations(db, user.id, [deepcopy(value)], source_message_id="named-original",
                              source_event_at=dt("2025-01-01T12:00:00Z"))
    db.commit()
    result = apply(db, user, [identify(value, "AVERY/ALEXJORDAN")])
    assert result.build.inserted == 0 and result.build.updated == 1
    assert db.query(Segment).one().id == old.id


@pytest.mark.parametrize("missing", ["incoming", "existing", "both"])
@pytest.mark.parametrize("changed_time", [False, True])
def test_missing_booking_identity_holds_legacy_physical_flight_without_mutation(account, missing, changed_time):
    db, user = account
    original = flight(pnr="LEGACY", dep="KLO", arr="MNL", number="Z2712",
                      departure="2025-05-03T11:15:00Z", arrival="2025-05-03T12:20:00Z")
    old = seed(db, user, original)
    if missing in {"existing", "both"}:
        old.pnr = None
        db.commit()
    incoming = flight(pnr=None if missing in {"incoming", "both"} else "LEGACY",
                      dep="KLO", arr="MNL", number="Z2712",
                      departure="2025-05-03T10:00:00Z" if changed_time else "2025-05-03T11:15:00Z",
                      arrival="2025-05-03T11:05:00Z" if changed_time else "2025-05-03T12:20:00Z")
    before = (old.id, old.trip_id, old.dep_time, old.arr_time, old.pnr, deepcopy(old.meta_json))
    for _ in range(2):
        result = apply(db, user, [incoming])
        assert result.build.inserted == result.build.updated == 0
        assert result.build.held_unknown == 1
        assert result.review_reason == "legacy_flight_identity_conflict"
        row = db.query(Segment).one()
        assert (row.id, row.trip_id, row.dep_time, row.arr_time, row.pnr, row.meta_json) == before
    assert db.query(BookingObservation).count() == 1


@pytest.mark.parametrize("decision", ["hold", "canceled", "other"])
def test_no_reference_receipt_preserves_legacy_manual_decisions(account, decision):
    db, user = account
    original = flight()
    old = seed(db, user, original)
    record_user_decision(db, user.id, original, ownership="other" if decision == "other" else "self",
                         status="active" if decision == "other" else decision)
    db.commit()
    facts = {row.id: deepcopy(row.facts) for row in db.query(BookingObservation)}
    before = (old.id, old.trip_id, old.dep_time, old.arr_time, old.pnr, deepcopy(old.meta_json))
    incoming = flight(pnr=None)
    result = apply(db, user, [incoming])
    assert result.build.inserted == result.build.updated == 0
    assert result.build.held_unknown == 1
    assert (old.id, old.trip_id, old.dep_time, old.arr_time, old.pnr, old.meta_json) == before
    assert all(db.get(BookingObservation, key).facts == value for key, value in facts.items())


def test_missing_reference_does_not_merge_next_day_same_number_flight(account):
    db, user = account
    seed(db, user, flight())
    next_day = flight(pnr=None, departure="2025-02-24T20:49:00Z", arrival="2025-02-24T22:10:00Z")
    result = apply(db, user, [next_day])
    assert result.build.inserted == 1 and result.build.held_unknown == 0
    assert db.query(Segment).count() == 2


def test_missing_reference_collision_is_account_scoped(account):
    db, user = account
    other = User(name="Morgan Avery", email="morgan@example.test")
    db.add(other); db.flush()
    seed(db, other, flight())
    result = apply(db, user, [flight(pnr=None)])
    assert result.build.inserted == 1 and result.build.held_unknown == 0
    assert db.query(Segment).count() == 2


def test_older_agency_alias_with_changed_clocks_does_not_duplicate_newer_legacy_schedule(account):
    db, user = account
    latest = flight(pnr="AIR123", dep="MGA", arr="MEX", number="AM651",
                    departure="2023-03-12T07:00:00Z", arrival="2023-03-12T09:42:00Z")
    old = seed(db, user, latest, source_time="2023-03-12T16:00:18Z")
    receipt = flight(pnr="OTA123", dep="MGA", arr="MEX", number="AM651",
                     departure="2023-03-12T13:49:00Z", arrival="2023-03-12T16:40:00Z")
    receipt.pnr_aliases = ["AIR123"]
    before = (old.id, old.trip_id, old.dep_time, old.arr_time, old.pnr, deepcopy(old.meta_json))
    for _ in range(2):
        result = apply(db, user, [receipt], received="2022-09-21T18:16:16Z")
        assert result.build.inserted == result.build.updated == 0
        assert result.build.held_unknown == 1
        assert result.review_reason == "legacy_flight_identity_conflict"
        row = db.query(Segment).one()
        assert (row.id, row.trip_id, row.dep_time, row.arr_time, row.pnr, row.meta_json) == before


def test_same_primary_newer_dated_schedule_still_updates_existing_id(account):
    db, user = account
    initial = flight()
    old = seed(db, user, initial)
    latest = flight(departure="2025-02-23T21:49:00Z", arrival="2025-02-23T23:10:00Z")
    result = apply(db, user, [latest], received="2025-01-03T12:00:00Z")
    assert result.build.inserted == 0 and result.build.updated == 1
    assert result.build.held_unknown == 0
    assert db.query(Segment).one().id == old.id
    assert old.dep_time == latest.dep_time.replace(tzinfo=None)
    assert old.arr_time == latest.arr_time.replace(tzinfo=None)


def traveler_details(names, *, booking="BOOK01", end="Payments\nAmount\nAlex Avery", label="Traveler"):
    rows = [f"Booking confirmation: {booking}", f"{label} Details"]
    for name in names:
        rows.extend([f"[image: pax icon] {name}", "[image: plane icon] *SY739* (DFW-PUJ)",
                     "• Seat: None", "• Under Seat Item: Included"])
    return "\n".join([*rows, end])


def identify_details(text, *, html=False, bookings=("BOOK01",)):
    values = [flight(pnr=pnr, dep="DFW", arr="PUJ", number="SY739") for pnr in bookings]
    for value in values:
        value.passenger_names = []
        value.passenger_evidence = []
        value.passenger_name = None
    apply_passenger_identity(values,
        plain_text="" if html else text,
        html="".join(f"<div>{escape(row)}</div>" for row in text.splitlines()) if html else "",
        user_name="Alex Avery", aliases=[])
    return values


@pytest.mark.parametrize("html", [False, True])
@pytest.mark.parametrize("names", [["Morgan Other", "Alex Avery"], ["Alex Avery", "Morgan Other"]])
def test_repeated_traveler_details_keeps_every_named_traveler(html, names):
    value, = identify_details(traveler_details(names), html=html)
    assert value.ownership == "self"
    assert value.passenger_names == names
    assert all(item["complete"] for item in value.passenger_evidence)


@pytest.mark.parametrize("label", ["Traveler", "Traveller"])
def test_repeated_traveler_details_complete_other_list_excludes_payment_contact(label):
    value, = identify_details(traveler_details(["Morgan Other", "Jamie Other"], label=label))
    assert value.ownership == "other"
    assert value.passenger_names == ["Morgan Other", "Jamie Other"]


@pytest.mark.parametrize("ending", ["", "Unrecognized traveler row\nSY739 (DFW-PUJ)\nPayments", "Alex Avery"])
def test_incomplete_repeated_traveler_manifest_cannot_assert_exclusive_other(ending):
    value, = identify_details(traveler_details(["Morgan Other"], end=ending))
    assert value.ownership == "unknown"
    assert value.passenger_names == ["Morgan Other"]
    assert not any(item["complete"] for item in value.passenger_evidence)


def test_repeated_traveler_names_stay_with_their_booking_even_for_same_flight():
    text = traveler_details(["Morgan Other"], booking="OTHER1") + "\n" + traveler_details(["Alex Avery"], booking="OWN001")
    other, own = identify_details(text, bookings=("OTHER1", "OWN001"))
    assert other.ownership == "other" and other.passenger_names == ["Morgan Other"]
    assert own.ownership == "self" and own.passenger_names == ["Alex Avery"]


def test_mixed_repeated_manifest_preserves_existing_self_flight_id(account):
    db, user = account
    value, = identify_details(traveler_details(["Morgan Other", "Alex Avery"]))
    original = seed(db, user, value)
    original_id = original.id
    for _ in range(2):
        result = apply(db, user, [value])
        assert result.build.removed_other == result.build.inserted == 0
        assert db.query(Segment).one().id == original_id


def test_repeated_traveler_manifest_does_not_borrow_remote_booking_marker():
    text = "Booking confirmation: OTHER1\n" + "\n".join(["Airline information"] * 9)
    text += "\n" + traveler_details(["Alex Avery"], booking="OWN001").replace("Booking confirmation: OWN001\n", "")
    text += "\nBooking confirmation: OWN001"
    other, own = identify_details(text, bookings=("OTHER1", "OWN001"))
    assert other.ownership == own.ownership == "unknown"


@pytest.mark.parametrize("reverse", [False, True])
def test_malformed_repeated_section_invalidates_same_booking_manifest_completeness(reverse):
    sections = [traveler_details(["Morgan Other"]), traveler_details(["???"])]
    if reverse:
        sections.reverse()
    value, = identify_details("\n".join(sections))
    assert value.passenger_names == ["Morgan Other"]
    assert value.ownership == "unknown"
    assert not any(item["complete"] for item in value.passenger_evidence)


def test_malformed_repeated_section_does_not_change_other_booking_completeness():
    text = traveler_details(["Morgan Other"], booking="OTHER1") + "\n" + traveler_details(["???"], booking="OWN001")
    other, unknown = identify_details(text, bookings=("OTHER1", "OWN001"))
    assert other.ownership == "other"
    assert unknown.ownership == "unknown"


@pytest.mark.parametrize("value", ["BNA-IAH", "BNA – IAH", "BNA→IAH", "BNA to IAH", "Purchase Summary"])
def test_route_and_purchase_section_labels_are_not_people(value):
    assert _name(value) is None


@pytest.mark.parametrize("value", ["Lee Kim", "Ann May", "Morgan Purchase", "Summary Jones"])
def test_name_exclusions_do_not_blacklist_short_names_or_individual_words(value):
    assert _name(value) == value


def test_airline_traveler_table_does_not_collect_following_route_or_purchase_heading():
    value = flight()
    value.passenger_names = []
    value.passenger_evidence = []
    value.passenger_name = None
    apply_passenger_identity([value], plain_text="", user_name="Alex Avery", aliases=[],
        html="<div>Traveler Details</div><div>AVERY/ALEX</div><div>BNA-IAH</div><div>Purchase Summary</div>")
    assert value.ownership == "self"
    assert value.passenger_names == ["AVERY/ALEX"]
