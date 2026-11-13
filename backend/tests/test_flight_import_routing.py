from app.celery_app import create_celery_app


def test_real_celery_routes_separate_enrolled_imports_and_history(monkeypatch):
    monkeypatch.setenv("TROTTER_PARSER_PILOT_ROUTING", "1")
    monkeypatch.setenv("BOOKING_STRICT_ENRICHMENT_ENABLED", "true")
    monkeypatch.setenv("FLIGHT_IMPORT_RECOVERY_USER_IDS", "1,9,12")
    app = create_celery_app()
    def queue(task, args=(), kwargs=None):
        return app.amqp.router.route({}, task, args, kwargs or {})["queue"].name
    assert queue("gmail.import", kwargs={"job_id":"job","user_id":12}) == "flight_parser_pilot"
    assert queue("gmail.import", ("job", 9)) == "flight_parser_pilot"
    history = "app.tasks.gmail_history_tasks.scan_history_page"
    assert queue(history, (111, 1)) == "flight_parser_pilot"
    assert queue(history, (1, 111)) == "gmail_history"
    assert queue("gmail.import", kwargs={"user_id":22}) == "celery"
    assert queue("app.tasks.dream_location_tasks.lookup", kwargs={"user_id":12}) == "dream_locations"
    assert queue("app.tasks.gmail_history_tasks.discover_history") == "celery"
    monkeypatch.setenv("BOOKING_STRICT_ENRICHMENT_ENABLED", "false")
    assert queue("gmail.import", kwargs={"user_id":12}) == "celery"
    monkeypatch.delenv("TROTTER_PARSER_PILOT_ROUTING")
    assert isinstance(create_celery_app().conf.task_routes, dict)
