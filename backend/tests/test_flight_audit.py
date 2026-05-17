from app.services.flight_audit import (
    FlightAuditAiResult,
    classify_audit_bucket,
    make_safe_snippet,
    normalize_ai_classifier_response,
)


def test_normalize_ai_classifier_response_clamps_and_cleans_fields():
    result = normalize_ai_classifier_response(
        """
        {
          "label": "flight_confirmation",
          "confidence": 1.8,
          "has_actual_flight": true,
          "is_marketing": false,
          "is_cancellation": false,
          "is_change_notice": false,
          "detected_airlines": ["American Airlines"],
          "detected_flight_numbers": ["AA 123"],
          "detected_airports": ["dfw", "LAX"],
          "detected_dates": ["Jan 5"],
          "reason": "confirmation email"
        }
        """
    )

    assert result.label == "flight_confirmation"
    assert result.confidence == 1.0
    assert result.has_actual_flight is True
    assert result.detected_airports == ["DFW", "LAX"]
    assert result.raw_error is None


def test_normalize_ai_classifier_response_extracts_json_from_wrapped_text():
    result = normalize_ai_classifier_response(
        'Here is the result: {"label": "not_flight", "confidence": 0.91, "reason": "sale"}'
    )

    assert result.label == "not_flight"
    assert result.confidence == 0.91


def test_normalize_ai_classifier_response_handles_bad_json():
    result = normalize_ai_classifier_response("not json")

    assert result.label == "unsure"
    assert result.raw_error


def test_bucket_successful_v4_parser_match():
    bucket = classify_audit_bucket(
        in_v4_discovery=True,
        prefilter_result=True,
        parser_flight_count=1,
        ai_result=FlightAuditAiResult(label="flight_confirmation", confidence=0.9, has_actual_flight=True),
    )

    assert bucket == "parsed_ok"


def test_bucket_discovery_miss_when_ai_finds_flight_outside_v4():
    bucket = classify_audit_bucket(
        in_v4_discovery=False,
        prefilter_result=False,
        parser_flight_count=0,
        ai_result=FlightAuditAiResult(label="itinerary", confidence=0.82, has_actual_flight=True),
    )

    assert bucket == "likely_flight_discovery_missed"


def test_bucket_parser_miss_when_v4_found_but_parser_did_not():
    bucket = classify_audit_bucket(
        in_v4_discovery=True,
        prefilter_result=True,
        parser_flight_count=0,
        ai_result=FlightAuditAiResult(label="boarding_pass", confidence=0.88, has_actual_flight=True),
    )

    assert bucket == "likely_flight_parser_missed"


def test_bucket_boarding_pass_ancillary_when_no_segment_is_available():
    bucket = classify_audit_bucket(
        in_v4_discovery=True,
        prefilter_result=True,
        parser_flight_count=0,
        ai_result=FlightAuditAiResult(label="boarding_pass", confidence=0.95, has_actual_flight=True),
        subject="American Airlines Boarding Pass(es).",
        safe_snippet="Your boarding pass(es) are attached. Please print all pages before proceeding to the airport.",
    )

    assert bucket == "duplicate_or_reminder"


def test_bucket_receipt_ancillary_when_it_only_references_bags_or_payment():
    bucket = classify_audit_bucket(
        in_v4_discovery=True,
        prefilter_result=True,
        parser_flight_count=0,
        ai_result=FlightAuditAiResult(label="receipt", confidence=0.95, has_actual_flight=True),
        sender_domain="info.email.aa.com",
        subject="Your purchase receipt - ABC123",
        safe_snippet="We charged $30.00. You can check in via the American app 24 hours before your flight.",
    )

    assert bucket == "duplicate_or_reminder"


def test_bucket_document_validation_as_ancillary_when_no_segment_is_available():
    bucket = classify_audit_bucket(
        in_v4_discovery=True,
        prefilter_result=True,
        parser_flight_count=0,
        ai_result=FlightAuditAiResult(label="boarding_pass", confidence=0.95, has_actual_flight=True),
        sender_domain="comunicaciones.iberia.com",
        subject="Booking 2H38SZ - Online validation of your documents",
        safe_snippet="Upload your documents to make sure that you have a smooth journey.",
    )

    assert bucket == "duplicate_or_reminder"


def test_bucket_government_eticket_as_ancillary_not_flight_parser_miss():
    bucket = classify_audit_bucket(
        in_v4_discovery=True,
        prefilter_result=True,
        parser_flight_count=0,
        ai_result=FlightAuditAiResult(label="flight_confirmation", confidence=0.95, has_actual_flight=True),
        sender_domain="migracion.gob.do",
        subject="E-Ticket-2024.08.03 15:10:05.688",
        safe_snippet="This is your application code to access your form again.",
    )

    assert bucket == "duplicate_or_reminder"


def test_bucket_change_or_cancellation_wins_for_policy_review():
    bucket = classify_audit_bucket(
        in_v4_discovery=True,
        prefilter_result=True,
        parser_flight_count=1,
        ai_result=FlightAuditAiResult(label="cancellation", confidence=0.87, is_cancellation=True),
    )

    assert bucket == "change_or_cancellation"


def test_bucket_obvious_ground_transport_as_other_travel_despite_ai_confidence():
    bucket = classify_audit_bucket(
        in_v4_discovery=True,
        prefilter_result=True,
        parser_flight_count=0,
        ai_result=FlightAuditAiResult(label="itinerary", confidence=0.95, has_actual_flight=True),
        sender_domain="flixbus.com",
        subject="FlixBus Booking Confirmation #123",
        safe_snippet="Waco to Houston by bus",
    )

    assert bucket == "other_travel"


def test_bucket_ground_transport_subdomain_as_other_travel():
    bucket = classify_audit_bucket(
        in_v4_discovery=True,
        prefilter_result=True,
        parser_flight_count=0,
        ai_result=FlightAuditAiResult(label="flight_confirmation", confidence=0.95, has_actual_flight=True),
        parse_miss_score=14,
        sender_domain="booking.greyhound.com",
        subject="Booking Confirmation #3083666182",
        safe_snippet="Thanks for booking with Greyhound. Bus tracker and ticket details.",
    )

    assert bucket == "other_travel"


def test_bucket_reminders_separately_when_no_segment_is_available():
    bucket = classify_audit_bucket(
        in_v4_discovery=True,
        prefilter_result=True,
        parser_flight_count=0,
        ai_result=FlightAuditAiResult(label="reminder", confidence=0.95, has_actual_flight=True),
        subject="It's time to check in for your flight",
    )

    assert bucket == "duplicate_or_reminder"


def test_safe_snippet_redacts_urls_emails_and_codes():
    snippet = make_safe_snippet(
        "Email me at person@example.com",
        "View https://example.com/path",
        "Record locator ABC123",
    )

    assert "person@example.com" not in snippet
    assert "https://example.com" not in snippet
    assert "ABC123" not in snippet
    assert "[email]" in snippet
    assert "[url]" in snippet
    assert "[code]" in snippet
