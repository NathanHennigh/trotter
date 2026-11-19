from pathlib import Path

import pytest

from app.models import CarrierTravelEvidence, Segment, Trip
from test_carrier_travel_recovery import account, process, source


def messages():
    checkin = source("aa-checkin")
    checkin["text"] = checkin["text"].replace("Maya June", "Maya").replace("MAYA JUNE", "MAYA")
    body = (Path(__file__).parent / "fixtures/bilt-confirmation-evidence.txt").read_text()
    replacements = {"QZ8K2M": "AX7Q2M", "UA1234": "AA805", "SFO": "NAS", "LAX": "JFK",
                    "San Francisco": "Nassau", "Los Angeles": "New York", "Tue, 10 Nov 2026": "Wed, 17 Feb 2027",
                    "09:20am": "04:10pm", "10:55am": "07:25pm"}
    for original, new in replacements.items():
        body = body.replace(original, new)
    booking = dict(id="unnamed-bilt", sender="Bilt <notifications@members.bilt.com>",
                   subject="Your flight booking is confirmed!", received_at="2027-01-01T21:00:00Z", text=body)
    return booking, checkin


@pytest.mark.parametrize("reverse", [False, True])
def test_only_independent_matching_sources_assign_one_exact_leg(account, reverse):
    db, user = account
    booking, checkin = messages()
    ordered = [checkin, booking] if reverse else [booking, checkin]
    process(db, user, ordered[0])
    assert db.query(Segment).count() == 0
    process(db, user, ordered[1])
    segment = db.query(Segment).one()
    assert (segment.dep_airport, segment.arr_airport, segment.meta_json["ownership"]) == ("NAS", "JFK", "self")
    ids = segment.id, segment.trip_id
    for value in ordered:
        process(db, user, value)
    assert [(s.id, s.trip_id) for s in db.query(Segment)] == [ids]
    assert db.query(Trip).count() == 1
    assert {e.kind for e in db.query(CarrierTravelEvidence)} == {"bilt_single_booking", "checkin_given_name"}


@pytest.mark.parametrize("mismatch", ["traveler", "two_passengers", "wrong_booking", "different_leg", "unauthenticated"])
def test_unnamed_bilt_stays_held_without_matching_proof(account, mismatch):
    db, user = account
    booking, checkin = messages()
    if mismatch == "two_passengers":
        booking["text"] = booking["text"].replace("Passengers\n1", "Passengers\n2")
    if mismatch == "traveler":
        checkin["text"] = checkin["text"].replace("Maya", "Robin").replace("MAYA", "ROBIN")
    if mismatch == "wrong_booking":
        booking["text"] = booking["text"].replace("AX7Q2M", "ZZ1234")
    if mismatch == "different_leg":
        booking["text"] = booking["text"].replace("AA805", "AA811")
    process(db, user, booking)
    process(db, user, checkin, authentication=mismatch != "unauthenticated")
    assert db.query(Segment).count() == 0
