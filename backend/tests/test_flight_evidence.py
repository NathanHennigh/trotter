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
