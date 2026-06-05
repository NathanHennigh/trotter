from app.services.parse_audit import assess_parse_miss


def test_deal_newsletter_parse_miss_is_resolved_ignore():
    miss = assess_parse_miss(
        subject="United News & Deals: save on your next trip",
        sender="United Airlines <news@united.com>",
        body="Book now and save up to 40 percent. This newsletter includes fare deals.",
    )

    assert miss.reason == "ignored_nonflight_promo"
    assert miss.should_review is False


def test_generic_confirmation_code_is_not_a_strong_flight_miss():
    miss = assess_parse_miss(
        subject="Your VidAngel confirmation code",
        sender="VidAngel <support@vidangel.com>",
        body="Use verification code 123456 to finish signing in.",
    )

    assert miss.reason == "ignored_nonflight_promo"
    assert miss.should_review is False


def test_unparsed_transactional_flight_shape_still_needs_review():
    miss = assess_parse_miss(
        subject="Check in online for your flight EK208",
        sender="Emirates <checkin@emirates.com>",
        body="Booking reference NT24IF. Flight EK208 JFK to DXB on Dec 31 at 4:35 PM.",
    )

    assert miss.should_review is True


def test_newsletter_sender_is_not_review_required_without_booking_anchor():
    miss = assess_parse_miss(
        subject="Infinite Scroll",
        sender="The Pour Over <news@mail.thepourover.org>",
        body="A newsletter paragraph mentions JFK, LAX, flight delays, and AA100.",
    )

    assert "newsletter_sender" in miss.signals
    assert miss.reason == "ignored_nonflight_promo"
    assert miss.should_review is False


def test_united_newsletter_sender_is_not_review_required_from_incidental_codes():
    miss = assess_parse_miss(
        subject="MileagePlus Program: new ways to use your miles",
        sender="MileagePlus Program <MileagePlus@news.united.com>",
        body="Deals to JFK, LAX, and SFO. Flight offers and partner news.",
    )

    assert "newsletter_sender" in miss.signals
    assert miss.reason == "ignored_nonflight_promo"
    assert miss.should_review is False


def test_ancillary_seat_or_bag_email_is_not_review_required_without_itinerary():
    miss = assess_parse_miss(
        subject="Fly together, sit together: Choose your seats now!",
        sender="Spirit Airlines <booking@fly.spirit-airlines.com>",
        body="Add bags, choose your seats, and save. Your flight to Houston is coming up.",
    )

    assert "ancillary_noise" in miss.signals
    assert miss.reason == "ignored_nonflight_promo"
    assert miss.should_review is False


def test_bank_appointment_email_is_not_review_required():
    miss = assess_parse_miss(
        subject="Your appointment is scheduled",
        sender="Wells Fargo and Company <appointments@wellsfargo.com>",
        body="Your appointment confirmation includes a confirmation number, date, and time.",
    )

    assert "noisy_sender" in miss.signals
    assert miss.reason == "ignored_nonflight_promo"
    assert miss.should_review is False


def test_mileageplus_shopping_email_is_not_review_required():
    miss = assess_parse_miss(
        subject="Limited time - earn 1,500 bonus miles just for shopping",
        sender="MileagePlus Shopping <email@mileageplusshoppingnews.com>",
        body="Shop now and earn miles. These offers are not a flight itinerary.",
    )

    assert "newsletter_sender" in miss.signals
    assert miss.reason == "ignored_nonflight_promo"
    assert miss.should_review is False
