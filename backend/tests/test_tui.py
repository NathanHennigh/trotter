from app.services.tui import GmailImportReporter


def test_gmail_import_reporter_redacts_body_like_newlines(capsys):
    reporter = GmailImportReporter(
        job_id="12345678-aaaa",
        parser_version=18,
        limit=None,
        batch_size=10,
        workers=4,
        tiers=["fast_known_senders"],
    )

    reporter.start()
    reporter.tier_started("fast_known_senders")
    reporter.count("fast_known_senders", "metadata_pass", 1)
    reporter.count("fast_known_senders", "metadata_skip", 2)
    reporter.evidence("fast_known_senders", "parse")
    reporter.parser_timing(
        "fast_known_senders",
        seconds=1.25,
        sender="Airline <noreply@example.com>",
        subject="Slow confirmation",
    )
    reporter.parsed_flight(
        "fast_known_senders",
        segments=1,
        updated=0,
        skipped=0,
        sender="Airline <noreply@example.com>\nInjected",
        subject="Your flight confirmation\nraw body should not appear",
    )
    reporter.final_summary(
        scanned=1,
        parsed=1,
        segments=1,
        updated=0,
        skipped=0,
        canceled=0,
        enriched=0,
    )

    out = capsys.readouterr().out
    assert "fast_known_senders" in out
    assert "\nInjected" not in out
    assert "meta-pass=" in out
    assert "meta-skip=" in out
    assert "Slowest parser calls" in out
    assert "Tier stats" in out
