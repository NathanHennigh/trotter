import importlib.util
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, BookingObservation, TravelInboxItem, User


def test_backfill_command_preview_apply_and_repeat_are_additive(tmp_path, monkeypatch, capsys):
    database = tmp_path / "inbox.sqlite"
    url = "sqlite:///" + database.as_posix()
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(name="Alex Avery", email="alex@example.com")
        db.add(user)
        db.flush()
        user_id = user.id
        db.add(BookingObservation(
            user_id=user_id, evidence_key="e" * 64, ownership="unknown", facts={},
            source_message_id="saved", dep_airport="IAH", arr_airport="MCO",
            pnr="SAVED1", flight_number="F91418", travel_date="2025-02-21",
        ))
        db.commit()
    monkeypatch.setenv("DATABASE_URL", url)
    spec = importlib.util.spec_from_file_location("inbox_backfill_command", Path(__file__).parents[1] / "scripts/backfill_travel_inbox.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main(["--user-id", str(user_id)]) == 0
    assert json.loads(capsys.readouterr().out)["applied"] is False
    with Session(engine) as db:
        assert db.query(TravelInboxItem).count() == 0
        assert db.query(BookingObservation).count() == 1
    assert module.main(["--all-users", "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["users"][0]["items_added"] == 1
    with Session(engine) as db:
        item_id = db.query(TravelInboxItem).one().id
    assert module.main(["--all-users", "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["users"][0]["items_added"] == 0
    with Session(engine) as db:
        assert db.query(TravelInboxItem).one().id == item_id
        assert db.query(BookingObservation).count() == 1
    engine.dispose()
