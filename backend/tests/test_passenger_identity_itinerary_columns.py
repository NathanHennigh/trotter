"""Explicit passenger columns bind only to complete, already dated flight rows."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.parser import ParsedFlight
from app.services.passenger_identity import apply_passenger_identity


HEADERS = ["Date", "Departs", "Arrives", "Flt #", "Route", "Passengers", "Seat", "Terminal"]


def row(name="Alex Avery", *, second=False):
    return (["Tue, May18", "10:00AM", "1:46PM", "AM456", "MEX to DFW", name, "", "TERMINAL2"]
            if second else ["Mon, May17", "7:00AM", "9:42AM", "AM123", "MGA to MEX", name, "6B", ""])


def table(rows, headers=HEADERS):
    return ("<table><tr>" + "".join(f"<th>{x}</th>" for x in headers) + "</tr>"
            + "".join("<tr>" + "".join(f"<td>{x}</td>" for x in values) + "</tr>" for values in rows)
            + "</table>")


def flights():
    return [ParsedFlight("MGA", "MEX", datetime(2027, 5, 17, 7, tzinfo=timezone.utc),
                         datetime(2027, 5, 17, 9, 42, tzinfo=timezone.utc), flight_number="AM123", pnr="TEST12"),
            ParsedFlight("MEX", "DFW", datetime(2027, 5, 18, 10, tzinfo=timezone.utc),
                         datetime(2027, 5, 18, 13, 46, tzinfo=timezone.utc), flight_number="AM456", pnr="TEST12")]


def identify(markup, *, candidates=None, plain="", user="Alex Avery"):
    candidates = candidates if candidates is not None else flights()
    apply_passenger_identity(candidates, html="<p>Confirmation code: TEST12</p>" + markup,
                             plain_text=plain, user_name=user, aliases=[])
    return candidates


def test_visible_table_binds_each_exact_dated_numbered_route():
    result = identify(table([row(), row("Morgan Blake", second=True)]))
    assert [(f.ownership, f.passenger_names) for f in result] == [
        ("self", ["Alex Avery"]), ("other", ["Morgan Blake"])]
    for flight in result:
        evidence = [e for e in flight.passenger_evidence if e["applies"]]
        assert len(evidence) == 1 and evidence[0]["complete"] is True
        assert evidence[0]["source"] == "html_itinerary_passenger_column"
        assert evidence[0]["scope"]["departure_date"] == flight.dep_time.date().isoformat()


def test_plain_and_html_presentations_do_not_duplicate_or_broaden_scope():
    data = [row(), row(second=True)]
    plain = "Confirmation code: TEST12\n" + "\n".join(" | ".join(r) for r in [HEADERS, *data])
    result = identify(table(data) + table(data), plain=plain)
    assert [f.ownership for f in result] == ["self", "self"]
    assert all(f.passenger_names == ["Alex Avery"] for f in result)
    assert all(len([e for e in f.passenger_evidence if e["applies"]]) == 1 for f in result)
    assert all(f.ownership == "unknown" for f in identify("", plain=plain))


@pytest.mark.parametrize("field,value", [
    (0, "Tue, May17"), (0, "Mon, May18"), (0, "Mon, Jun17"), (0, "May17"),
    (0, "Mon, May17 2028"), (1, "7:01AM"), (1, "7:00"), (2, "9:41AM"),
    (3, "AM124"), (3, "AM0"), (3, "AM123 and AM456"), (4, "MGA to DFW"),
    (4, "MGA/MEX"), (5, ""), (5, "Unavailable 123"),
])
def test_malformed_or_unmatched_row_cannot_establish_ownership(field, value):
    values = row()
    values[field] = value
    assert identify(table([values]))[0].ownership == "unknown"


@pytest.mark.parametrize("bad", [row(""), row("Unreadable 123"), row("?")[:5], row("Morgan Blake") + ["extra"]])
@pytest.mark.parametrize("separate_table", [False, True])
def test_unreadable_additional_passenger_prevents_exclusive_other(bad, separate_table):
    markup = (table([row("Morgan Blake")]) + table([bad]) if separate_table
              else table([row("Morgan Blake"), bad]))
    first = identify(markup)[0]
    assert first.ownership == "unknown"
    assert first.passenger_names == (["Morgan Blake"] if len(bad) == len(HEADERS) else [])
    assert all(not e["complete"] for e in first.passenger_evidence if e["applies"])


@pytest.mark.parametrize("attribute", ["colspan", "rowspan"])
def test_spanned_data_or_header_cells_cannot_establish_exclusive_other(attribute):
    valid = table([row("Morgan Blake")])
    for tag in ("td", "th"):
        malformed = valid.replace(f"<{tag}>", f'<{tag} {attribute}="2">', 1)
        assert identify(valid + malformed)[0].ownership == "unknown"


@pytest.mark.parametrize("wrapper", [
    '<template>{}</template>', '<div hidden>{}</div>', '<noscript>{}</noscript>',
    '<div style="display:none">{}</div>', '<head>{}</head>', '<!--{}-->',
])
def test_hidden_or_inert_table_is_not_a_passenger_manifest(wrapper):
    assert identify(wrapper.format(table([row()])))[0].ownership == "unknown"


def test_only_visible_body_is_retained_from_malformed_head():
    markup = "<head><title>Travel</title><body>" + table([row()]) + "</body></head>"
    assert identify(markup)[0].ownership == "self"


@pytest.mark.parametrize("extra", ["<p>Confirmation code: ELSE12</p>", "<p>Airline confirmation: ELSE12</p>"])
def test_multiple_booking_references_do_not_pick_one_passenger_manifest(extra):
    assert identify(table([row()]) + extra)[0].ownership == "unknown"


def test_ambiguous_matching_parsed_flights_cannot_choose_a_year_or_card():
    candidates = flights()
    duplicate = flights()[0]
    candidates.append(duplicate)
    assert all(f.ownership == "unknown" for f in identify(table([row()]), candidates=candidates))


def test_greeting_and_payer_column_are_not_traveler_authority():
    headings = ["Payer" if h == "Passengers" else h for h in HEADERS]
    assert identify("<p>Hello Alex Avery</p>" + table([row()], headings))[0].ownership == "unknown"


def test_explicit_conflicting_middle_name_remains_other():
    assert identify(table([row("Alex Jordan Avery")]), user="Alex Casey Avery")[0].ownership == "other"


def test_named_self_and_other_cells_retain_both_without_exclusive_other():
    first = identify(table([row("Morgan Blake<br>Alex Avery")]))[0]
    assert first.ownership == "self"
    assert first.passenger_names == ["Morgan Blake", "Alex Avery"]


def test_already_normalized_flight_uses_its_proven_local_clocks():
    candidates = flights()
    for f in candidates:
        f.time_provenance = {"status":"normalized", "departure":{"local":f.dep_time.replace(tzinfo=None).isoformat()},
                             "arrival":{"local":f.arr_time.replace(tzinfo=None).isoformat()}}
        f.dep_time += timedelta(hours=6)
        f.arr_time += timedelta(hours=6)
    assert [f.ownership for f in identify(table([row(), row(second=True)]), candidates=candidates)] == ["self", "self"]


def test_explicit_operator_annotation_does_not_change_flight_or_passenger_scope():
    values = row()
    values[3] += " Operated by EXAMPLE REGIONAL AIRLINES"
    assert identify(table([values]))[0].ownership == "self"


def connection_candidates():
    """A same-number stop has its own explicit clocks at the connection."""
    return [ParsedFlight("DFW", "DEN", datetime(2027, 5, 17, 7, tzinfo=timezone.utc),
                         datetime(2027, 5, 17, 9, tzinfo=timezone.utc), flight_number="AA123", pnr="TEST12"),
            ParsedFlight("DEN", "SEA", datetime(2027, 5, 17, 10, tzinfo=timezone.utc),
                         datetime(2027, 5, 17, 12, tzinfo=timezone.utc), flight_number="AA123", pnr="TEST12")]


def connection_rows():
    return [["Mon, May17", "7:00AM", "9:00AM", "AA123", "DFW to DEN", "Alex Avery", "", ""],
            ["Mon, May17", "10:00AM", "12:00PM", "AA123", "DEN to SEA", "Alex Avery", "", ""]]


def test_complete_same_number_connection_rows_have_exact_passenger_scope():
    candidates = identify(table(connection_rows()), candidates=connection_candidates())
    assert [f.ownership for f in candidates] == ["self", "self"]


@pytest.mark.parametrize("clock_shift", [0, 5, -5, 100])
def test_competing_through_summary_denies_only_new_table_authority(clock_shift):
    candidates = connection_candidates()
    candidates.append(ParsedFlight("DFW", "SEA", candidates[0].dep_time + timedelta(minutes=clock_shift),
                                   candidates[1].arr_time + timedelta(minutes=clock_shift),
                                   flight_number="AA123", pnr="TEST12"))
    before = [(f.dep_airport, f.arr_airport, f.dep_time, f.arr_time, f.flight_number, f.pnr) for f in candidates]
    result = identify(table(connection_rows()), candidates=candidates)
    assert all(f.ownership == "unknown" and not f.passenger_evidence for f in result)
    assert [(f.dep_airport, f.arr_airport, f.dep_time, f.arr_time, f.flight_number, f.pnr) for f in result] == before


def test_missing_printed_connection_candidate_cannot_promote_the_remaining_row():
    result = identify(table(connection_rows()), candidates=connection_candidates()[:1])
    assert result[0].ownership == "unknown" and not result[0].passenger_evidence


def test_unrelated_parallel_candidate_does_not_prevent_exact_table_ownership():
    candidates = connection_candidates() + flights()[:1]
    result = identify(table(connection_rows()), candidates=candidates)
    assert [f.ownership for f in result] == ["self", "self", "unknown"]


@pytest.mark.parametrize("field", ["date", "pnr", "number"])
def test_distinct_journey_summary_does_not_deny_exact_table_scope(field):
    candidates = connection_candidates()
    aggregate = ParsedFlight("DFW", "SEA", candidates[0].dep_time, candidates[1].arr_time,
                             flight_number="AA123", pnr="TEST12")
    if field == "date":
        aggregate.dep_time += timedelta(days=1)
        aggregate.arr_time += timedelta(days=1)
    elif field == "pnr":
        aggregate.pnr = "ELSE12"
    else:
        aggregate.flight_number = "AA456"
    assert [f.ownership for f in identify(table(connection_rows()), candidates=candidates + [aggregate])] == ["self", "self", "unknown"]


def test_review_candidate_cannot_supply_missing_timetable_leg_authority():
    candidates = connection_candidates()
    candidates[1].force_review = True
    result = identify(table(connection_rows()), candidates=candidates)
    assert all(f.ownership == "unknown" and not f.passenger_evidence for f in result)
