"""Rendered roster sections must not absorb legal prose or a travel checklist."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.parser import ParsedFlight
from app.services.passenger_identity import _html_lines, _text_evidence, apply_passenger_identity


PNR = "ABC123"
CARD = ("<table><tr><td>Confirmation: ABC123<p>PASSENGER</p>"
        "<p>Alex Morgan</p><p>Jordan Quinn</p></td></tr></table>")
CHECKLIST = ("<table><tr><td><p>Travel Checklist</p><p>Before your trip:</p>"
             "<p>1. Review required documents</p><p>2. Check in before departure</p>"
             "</td></tr></table>")


def evidence(*, html="", plain=""):
    flight = SimpleNamespace(pnr=PNR, pnr_aliases=[], flight_number="WN123",
                             dep_airport="DFW", arr_airport="LAX")
    text = _html_lines(html) if html else plain
    return _text_evidence(text, "html_passenger_label" if html else "text_passenger_label", [flight])


def identify(html, user="Alex Morgan"):
    departure = datetime(2027, 8, 4, 14, tzinfo=timezone.utc)
    flight = ParsedFlight("DFW", "LAX", departure, departure + timedelta(hours=3),
                          airline="WN", flight_number="WN123", pnr=PNR)
    apply_passenger_identity([flight], html=html, plain_text="", user_name=user, aliases=[])
    return flight


@pytest.mark.parametrize("clause", [
    "Passengers on a journey involving an overseas destination and regulations apply and other factors, including delays.",
    "Passengers\non a journey involving an overseas destination; regulations apply",
    "Passengers on a journey\ninvolving an overseas destination and regulations apply",
    "PASSENGERS ON A JOURNEY INVOLVING an overseas destination and regulations apply",
])
@pytest.mark.parametrize("html", [False, True])
def test_typed_carrier_liability_clause_cannot_open_a_roster(clause, html):
    text = "Confirmation: ABC123\n" + clause + "\nPoint Purchase Offer Terms and Conditions"
    rows = evidence(html="<p>" + text.replace("\n", "</p><p>") + "</p>") if html else evidence(plain=text)
    assert rows == []


@pytest.mark.parametrize("roster", [
    "Passengers\nAlex Morgan\nJordan Quinn",
    "Passengers 2\nAlex Morgan\nJordan Quinn",
    "Passengers Alex Morgan and Jordan Quinn",
    "Passengers: Alex Morgan; Jordan Quinn",
])
def test_real_multiline_counted_and_inline_rosters_keep_all_people(roster):
    rows = evidence(plain="Confirmation: ABC123\n" + roster + "\nFlight details")
    assert {row["name"] for row in rows} == {"Alex Morgan", "Jordan Quinn"}
    assert all(row["complete"] for row in rows)


@pytest.mark.parametrize("label", ["Passengers:", "Passengers (2)", "Passenger 1", "Passenger Name"])
def test_explicit_partial_roster_keeps_named_evidence(label):
    rows = evidence(plain=f"Confirmation: ABC123\n{label} Alex Morgan; ???")
    assert [row["name"] for row in rows] == ["Alex Morgan"]
    assert rows[0]["complete"] is False


@pytest.mark.parametrize("delimiter", ["|", "and", "&", ";"])
def test_general_partial_roster_behavior_is_unchanged(delimiter):
    # This fix does not broaden the existing generic completeness predicate.
    rows = evidence(plain=f"Confirmation: ABC123\nPassengers Alex Morgan {delimiter} ???")
    assert [row["name"] for row in rows] == ["Alex Morgan"]
    assert rows[0]["complete"] is (delimiter != ";")


@pytest.mark.parametrize("depth", [0, 1, 6])
def test_proven_checklist_section_preserves_every_real_roster_member(depth):
    html = CARD + CHECKLIST
    for _ in range(depth):
        html = "<table><tr><td>" + html + "</td></tr></table>"
    row = identify(html, user="Jordan Quinn")
    assert row.ownership == "self"
    assert row.passenger_names == ["Alex Morgan", "Jordan Quinn"]
    assert all(item["complete"] for item in row.passenger_evidence)
    assert "Travel Checklist" not in row.passenger_names


def test_split_nested_tables_do_not_turn_second_self_traveler_into_exclusive_other():
    html = ("<table><tr><td><table><tr><td>Confirmation: ABC123<p>Passengers</p>"
            "<p>Jordan Quinn</p></td></tr></table><table><tr><td>Alex Morgan</td></tr></table>"
            "</td></tr></table><p>Flight details</p>")
    row = identify(html)
    assert row.ownership == "self"
    assert row.passenger_names == ["Jordan Quinn", "Alex Morgan"]
    assert all(item["complete"] for item in row.passenger_evidence)


def test_unreadable_sibling_row_stays_incomplete():
    html = ("<table><tr><td><table><tr><td>Confirmation: ABC123<p>Passengers</p>"
            "<p>Jordan Quinn</p></td></tr></table><table><tr><td>???</td></tr></table>"
            "</td></tr></table><p>Flight details</p>")
    row = identify(html)
    assert row.ownership == "unknown"
    assert row.passenger_names == ["Jordan Quinn"]
    assert all(not item["complete"] for item in row.passenger_evidence)


@pytest.mark.parametrize("change", [
    lambda html: html.replace("Before your trip:", "Other information"),
    lambda html: html.replace("1. Review required documents", "Review required documents"),
    lambda html: html.replace("2. Check in before departure", "3. Check in before departure"),
    lambda html: html.replace("<p>Travel Checklist</p>", "<p>Jordan Quinn</p><p>Travel Checklist</p>"),
])
def test_heading_or_arbitrary_table_end_alone_cannot_create_a_boundary(change):
    text = _html_lines(CARD + change(CHECKLIST))
    assert not getattr(text, "roster_boundaries", ())


@pytest.mark.parametrize("tag", ["template", "noscript", "script", "style"])
def test_inert_rosters_gain_no_authority(tag):
    assert evidence(html=f"<{tag}>" + CARD + CHECKLIST + f"</{tag}>") == []


def test_hidden_roster_gains_no_authority():
    assert evidence(html='<div hidden>' + CARD + CHECKLIST + '</div>') == []


@pytest.mark.parametrize("marker", ["__VISIBLE_ROSTER_CARD_END__", "__VISIBLE_ROSTER_CARD_END___"])
def test_literal_marker_cannot_complete_an_unreadable_roster(marker):
    html = ("<table><tr><td>Confirmation: ABC123<p>PASSENGER</p><p>Jordan Quinn</p><p>"
            + marker + "</p></td></tr></table>")
    row = identify(html)
    assert row.ownership == "unknown"
    assert row.passenger_names == ["Jordan Quinn"]
    assert all(not item["complete"] for item in row.passenger_evidence)


def test_literal_marker_with_actual_checklist_does_not_become_a_generated_boundary():
    html = CARD.replace("<p>Jordan Quinn</p>", "<p>__VISIBLE_ROSTER_CARD_END__</p>") + CHECKLIST
    row = identify(html, user="Jordan Quinn")
    assert row.ownership == "unknown"
    assert row.passenger_names == ["Alex Morgan"]
    assert all(not item["complete"] for item in row.passenger_evidence)


def test_same_table_valid_two_person_roster_is_not_cut_by_leaf_cell_end():
    html = ("<table><tr><td>Confirmation: ABC123</td></tr><tr><td>Passengers</td></tr>"
            "<tr><td>Jordan Quinn</td></tr><tr><td>Alex Morgan</td></tr></table><p>Flight details</p>")
    row = identify(html)
    assert row.ownership == "self" and row.passenger_names == ["Jordan Quinn", "Alex Morgan"]


def test_plaintext_checklist_cannot_manufacture_dom_authority():
    plain = "Confirmation: ABC123\nPassengers\nJordan Quinn\n__VISIBLE_ROSTER_CARD_END__\nTravel Checklist\nBefore your trip:\n1. Review documents\n2. Check in"
    rows = evidence(plain=plain)
    assert rows and all(not row["complete"] for row in rows)
