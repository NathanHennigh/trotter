from app.services.flight_evidence import assess_flight_evidence


def test_route_airports_and_confirmation_evidence_recommend_parse():
    evidence = assess_flight_evidence(
        subject="Your flight confirmation",
        sender="Airline <receipt@example-air.com>",
        body="Record locator ABC123. Flight AA 100 DFW -> JFK on Jan 4 at 8:30 PM.",
        sender_confidence="airline",
    )

    assert evidence.verdict == "parse"
    assert evidence.airport_codes == ("DFW", "JFK")
    assert "route_airport_pair" in evidence.signals


def test_random_three_letter_words_do_not_create_airport_route():
    evidence = assess_flight_evidence(
        subject="Weekly rewards update",
        sender="Rewards <offers@example.com>",
        body="YOU CAN EARN AND SAVE with this newsletter deal.",
    )

    assert evidence.airport_codes == ()
    assert evidence.verdict == "skip"


def test_flight_deal_noise_is_observable_before_future_gating():
    evidence = assess_flight_evidence(
        subject="Flight Deal Alert: DFW to SEA from $48",
        sender="Deals <offers@example.com>",
        body="Book now and save up to 50 percent on your next route.",
        sender_confidence="mixed",
    )

    assert "promo_noise" in evidence.signals
    assert evidence.verdict in {"review", "skip"}


def test_noisy_deal_sender_needs_real_booking_anchor():
    evidence = assess_flight_evidence(
        subject="KAYAK Flight Deal Alert: Houston to Miami from $88",
        sender="KAYAK Deals <deals@kayak.com>",
        body="Book now and save up to 40 percent. Prices change fast.",
        sender_confidence="mixed",
    )

    assert "noisy_sender" in evidence.signals
    assert evidence.verdict == "skip"


def test_real_airline_transactional_shape_still_recommends_parse():
    evidence = assess_flight_evidence(
        subject="Check in online for your flight EK208 on 31 December",
        sender="Emirates <checkin@emirates.com>",
        body="Booking reference NT24IF. Flight EK208 JFK -> DXB on Dec 31 at 4:35 PM.",
        sender_confidence="airline",
    )

    assert evidence.verdict == "parse"


def test_confirmation_hash_counts_as_booking_identifier():
    evidence = assess_flight_evidence(
        subject="Fwd: Your 01/16 trip to Tampa is all set.",
        sender="David Hennigh <david@example.com>",
        body="January 16 PNS -> TPA Confirmation # 3WVTUA Complete your trip and save up to 30%.",
    )

    assert "booking_identifier" in evidence.signals


def test_newsletter_sender_is_skipped_despite_incidental_flight_words():
    evidence = assess_flight_evidence(
        subject="Leaving The Peacock's Nest",
        sender="The Pour Over <news@mail.thepourover.org>",
        body="Today's newsletter mentions JFK, LAX, AA100, flight delays, and current events.",
    )

    assert "newsletter_sender" in evidence.signals
    assert evidence.verdict == "skip"


def test_retail_order_noise_is_skipped():
    evidence = assess_flight_evidence(
        subject="Your Order is Ready for Pick Up at Waco Lowe's",
        sender="Lowe's Home Improvement <orders@lowes.com>",
        body="Your purchase receipt and pickup order are ready. Delivery date Dec 05.",
    )

    assert "non_flight_travel_noise" in evidence.signals
    assert "noisy_sender" in evidence.signals
    assert evidence.verdict == "skip"


def test_instacart_offer_noise_is_skipped():
    evidence = assess_flight_evidence(
        subject="Get $40 off on more than just groceries",
        sender="Instacart <no-reply@customeremail.instacartemail.com>",
        body="Delivery order deals and grocery savings.",
    )

    assert "non_flight_travel_noise" in evidence.signals
    assert "newsletter_sender" in evidence.signals
    assert evidence.verdict == "skip"


def test_capital_one_offer_noise_is_skipped():
    evidence = assess_flight_evidence(
        subject="New travel offer: Enjoy 30% off premium stays",
        sender='"Capital One | Venture X" <capitalone@message.capitalone.com>',
        body="Sponsored hotel offer and premium stays.",
    )

    assert "promo_noise" in evidence.signals
    assert "noisy_sender" in evidence.signals
    assert evidence.verdict == "skip"


def test_united_newsletter_domain_is_skipped():
    evidence = assess_flight_evidence(
        subject="MileagePlus Program: save on award travel",
        sender="MileagePlus Program <MileagePlus@news.united.com>",
        body="Deals to JFK and LAX, flight offers, and partner promotions.",
    )

    assert "newsletter_sender" in evidence.signals
    assert evidence.verdict == "skip"


def test_bank_appointment_noise_is_skipped():
    evidence = assess_flight_evidence(
        subject="Your appointment is scheduled",
        sender="Wells Fargo and Company <appointments@wellsfargo.com>",
        body="Your appointment confirmation includes a confirmation number, date, and time.",
    )

    assert "noisy_sender" in evidence.signals
    assert evidence.verdict == "skip"


def test_mileageplus_shopping_noise_is_skipped():
    evidence = assess_flight_evidence(
        subject="Limited time - earn 1,500 bonus miles just for shopping",
        sender="MileagePlus Shopping <email@mileageplusshoppingnews.com>",
        body="Shop now and earn miles. These offers are not a flight itinerary.",
    )

    assert "newsletter_sender" in evidence.signals
    assert evidence.verdict == "skip"


def test_operational_itinerary_survives_generic_footer_and_24_hour_date():
    evidence = assess_flight_evidence(subject="Your flight SY739 is delayed", sender="Sun Country <updates@example.com>",
        body="Booking reference ABC123. DFW -> PUJ. Flight SY739. Departure 2026/06/19 10:00. Arrival 15:30. Add bags. Choose your seats. Deals and parking.")
    assert evidence.verdict == "parse"
    assert "operational_itinerary" in evidence.signals


def test_sender_hostname_cannot_supply_a_flight_number():
    evidence = assess_flight_evidence(subject="Mileage statement", sender="EVA <eservice@mh1.evaair.com>", body="Your account balance is 500 miles.")
    assert evidence.flight_numbers == ()


def test_review_decision_agrees_with_gate_for_real_and_nonflight_messages():
    from app.services.parse_audit import assess_parse_miss
    cases = [
        ("Check in for your flight", "Record locator ABC123. UA100 DFW -> JFK on June 1. Choose seats and add bags."),
        ("Mileage statement", "New service TPE -> DFW on Oct 1. Book now and earn bonus miles."),
        ("Your hotel confirmation", "Hotel only reservation. Confirmation code ABC123. June 1."),
    ]
    for subject, body in cases:
        gate = assess_flight_evidence(subject=subject, sender="mail@example.com", body=body)
        miss = assess_parse_miss(subject=subject, sender="mail@example.com", body=body)
        assert miss.should_review == (gate.verdict != "skip")


def test_gate_change_city_labels_and_flight_number_label_are_operational():
    evidence = assess_flight_evidence(subject="Important Travel Information: Your gate has been changed", sender="Frontier <mail@example.com>",
        body="New flight itinerary. Confirmation code: ABC123. IAH - Houston, TX to MCO - Orlando, FL. Frontier flight number: #1418. Estimated departure: February 21, 2025, 4:16 PM. Book flight | Deals | Manage travel.")
    assert evidence.verdict == "parse"
    assert evidence.airport_codes == ("IAH", "MCO")
    assert evidence.flight_numbers == ("FLIGHT1418",)


def test_mileage_statement_ad_is_not_a_booked_flight():
    evidence = assess_flight_evidence(subject="EVA Air Infinity MileageLands E-Mileage Statement", sender="eservice@mh1.evaair.com",
        body="Miles balance 500. New service TPE -> DFW October 3, 2025. BR06 TPE -> LAX upgrade offer. Book now. Customer total.")
    assert evidence.verdict == "skip"
    assert "statement_noise" in evidence.signals
    assert "MH1" not in evidence.flight_numbers
    assert not {"CUS", "MER", "TAL"} & set(evidence.airport_codes)


def test_ticket_with_city_names_and_seat_offer_footer_is_not_rejected():
    evidence = assess_flight_evidence(subject="Your e-ticket receipt ABC123: 16 Nov 2023", sender="travel@example.com",
        body="Booking reference ABC123. Your itinerary AA1555 American Airlines. 16 Nov 2023 21:20 Dallas Ft Worth. 16 Nov 2023 23:13 Nashville International. Passenger MADAME ALEX AVERY. Pay to choose your seat in advance.")
    assert evidence.verdict == "parse"


def test_numbered_confirmation_with_separate_airport_lines_survives_bag_footer():
    evidence = assess_flight_evidence(subject="Fwd: View your travel confirmation", sender="traveler@example.com",
        body="Confirmed. February 21, 2025. Frontier F91418. Houston\n*IAH*\n4:16 p.m.\nOrlando\n*MCO*\n7:40 p.m. Confirmation code ABC123. Check-in and Boarding Pass. Add bags and seats.")
    assert evidence.verdict == "parse"
