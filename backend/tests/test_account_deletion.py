"""Destructive account actions use isolated fixtures with real FK enforcement."""
from datetime import datetime, timedelta, timezone
import importlib.util
import os
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
import jwt
import pytest
from sqlalchemy import create_engine, inspect

from app.auth import create_app_jwt
from app.crypto import encrypt_refresh_token
from app.models import (AccountErasureCleanup, AuthIdentity, Base, BookingObservation, Dream,
                        DreamItem, FlightShare, Message, TravelInboxEvidence, TravelInboxItem,
                        Trip, Segment, User)
from app.planner_models import (PlannerContribution, PlannerIdea, PlannerInvite, PlannerJob,
                               PlannerMember, PlannerRevision, PlannerTrip, PlannerVote)
from app.services import account_deletion, apple_auth

from test_apple_auth import env, db, client, headers, user  # noqa: F401


def trip(db, owner, title):
    row = PlannerTrip(owner_id=owner.id, client_request_id=str(uuid4()), request_hash="x", title=title,
                      destination="Morocco", start_date="2026-11-01", end_date="2026-11-07")
    db.add(row)
    db.flush()
    db.add(PlannerMember(trip_id=row.id, user_id=owner.id, role="owner"))
    db.flush()
    return row


def populate(db):
    owner, friend = user(db), user(db, "friend@example.com", subject="google-friend")
    own, others = trip(db, owner, "Owned group"), trip(db, friend, "Friend's group")
    db.add_all([PlannerMember(trip_id=own.id, user_id=friend.id, role="editor"),
                PlannerMember(trip_id=others.id, user_id=owner.id, role="contributor")])
    dream = Dream(user_id=owner.id, title="Morocco")
    db.add(dream)
    db.flush()
    item = DreamItem(user_id=owner.id, dream_id=dream.id, source_url="https://www.instagram.com/reel/fixture/")
    db.add(item)
    db.flush()
    idea = PlannerIdea(trip_id=others.id, created_by=owner.id, identity_key="place", title="Shared place")
    db.add(idea)
    db.flush()
    db.add_all([PlannerContribution(trip_id=others.id, idea_id=idea.id, user_id=owner.id,
                                   identity_key="dream:1", dream_item_id=item.id),
                PlannerVote(idea_id=idea.id, user_id=owner.id, value=1),
                Message(user_id=owner.id, provider_msg_id="private-mail")])
    flighttrip = Trip(user_id=owner.id, title="Private trip")
    db.add(flighttrip)
    db.flush()
    db.add(Segment(trip_id=flighttrip.id, mode="flight", dep_airport="ORD", arr_airport="JFK",
                   dep_time=datetime.now(timezone.utc), arr_time=datetime.now(timezone.utc)))
    obs = BookingObservation(user_id=owner.id, evidence_key="private-observation", ownership="owner", facts={})
    inbox = TravelInboxItem(user_id=owner.id, record_key="record", flight_key="flight", reason="companion")
    db.add_all([obs, inbox])
    db.flush()
    db.add(TravelInboxEvidence(item_id=inbox.id, observation_id=obs.id))
    rev = PlannerRevision(trip_id=others.id, created_by=owner.id, base_version=1,
                           plan={"days": [], "votes": [{"user_id": str(owner.id), "name": owner.name}, {"user_id": str(friend.id), "name": friend.name}]}, source="manual")
    db.add(rev)
    db.flush()
    job = PlannerJob(trip_id=others.id, user_id=friend.id, client_request_id="old-job", request_hash="hash",
                      base_version=1, input_json={"ideas": [{"contributors": [{"user_id": str(owner.id), "name": "Personal Name"}]}]},
                      use_ai=False, status="completed", revision_id=rev.id)
    db.add(job)
    db.commit()
    return owner, friend, own.id, others.id, idea.id, item.id, job.id, rev.id


def test_delete_requires_confirmation_and_recent_auth(client, db):
    row = user(db)
    assert client.request("DELETE", "/auth/account", headers=headers(row), json={"confirmation": "no"}).status_code == 422
    claims = jwt.decode(create_app_jwt(row.id, row.email), options={"verify_signature": False})
    claims["iat"] -= 601
    token = jwt.encode(claims, os.environ["JWT_SECRET"], algorithm="HS256")
    response = client.request("DELETE", "/auth/account", headers={"Authorization": "Bearer " + token}, json={"confirmation": "DELETE"})
    assert response.status_code == 403 and response.json()["detail"] == "reauthentication_required"
    assert db.get(User, row.id)


def test_erasure_removes_private_graph_and_owned_group_preserves_friends_data(client, db, monkeypatch, tmp_path):
    owner, friend, owned_id, friends_id, idea_id, item_id, job_id, revision_id = populate(db)
    owner_id, friend_id = owner.id, friend.id
    bearer = headers(owner)
    monkeypatch.setenv("DREAM_THUMBNAIL_CACHE_DIR", str(tmp_path / "covers"))
    root = tmp_path / "covers"
    root.mkdir()
    for filename in (f"{item_id}.bin", f"{item_id}.json", f"{item_id}-hash-v1-w240.webp", "999.bin"):
        (root / filename).write_text("fixture")
    assert client.get("/auth/account/deletion-preview", headers=bearer).json() == {"owned_trips": 1, "shared_owned_trips": 1}
    response = client.request("DELETE", "/auth/account", headers=bearer, json={"confirmation": "DELETE"})
    assert response.status_code == 204, response.text
    db.expire_all()
    assert db.get(User, owner_id) is None
    assert db.get(User, friend_id)
    assert db.get(PlannerTrip, owned_id) is None
    assert db.get(PlannerTrip, friends_id).version == 2
    assert db.get(PlannerIdea, idea_id).created_by is None
    assert db.query(PlannerContribution).count() == 0
    assert db.query(PlannerVote).count() == 0
    assert db.query(PlannerMember).count() == 1
    assert db.get(PlannerJob, job_id).input_json == {"ideas": [{"contributors": []}]}
    assert db.get(PlannerRevision, revision_id).plan["votes"] == [{"user_id": str(friend_id), "name": friend.name}]
    for model in (Dream, DreamItem, Message, Trip, Segment, TravelInboxEvidence, TravelInboxItem, BookingObservation):
        assert db.query(model).count() == 0, model.__tablename__
    assert db.query(AuthIdentity).count() == 1
    assert list(root.iterdir()) == [root / "999.bin"]
    assert db.query(AccountErasureCleanup).count() == 1
    assert client.get("/auth/me", headers=bearer).status_code == 401


def test_apple_revocation_failure_preserves_account_and_retry_succeeds(client, db, monkeypatch):
    row = user(db, "relay@privaterelay.appleid.com", "apple", "apple-subject")
    identity = db.query(AuthIdentity).one()
    identity.refresh_token_encrypted = encrypt_refresh_token("retained-for-retry")
    db.commit()
    bearer = headers(row)
    revoke = AsyncMock(side_effect=HTTPException(503, "account_deletion_retry"))
    monkeypatch.setattr(apple_auth, "revoke_refresh_token", revoke)
    failed = client.request("DELETE", "/auth/account", headers=bearer, json={"confirmation": "DELETE"})
    assert failed.status_code == 503
    assert db.query(User).count() == 1
    assert db.query(AuthIdentity).count() == 1
    assert db.query(AccountErasureCleanup).count() == 0
    revoke.side_effect = None
    succeeded = client.request("DELETE", "/auth/account", headers=bearer, json={"confirmation": "DELETE"})
    assert succeeded.status_code == 204
    assert revoke.await_count == 2
    revoke.assert_awaited_with("retained-for-retry")
    db.expire_all()
    assert db.query(User).count() == 0


def test_thumbnail_cleanup_retries_late_writes_and_keeps_unrelated_files(db, monkeypatch, tmp_path):
    monkeypatch.setenv("DREAM_THUMBNAIL_CACHE_DIR", str(tmp_path))
    row = AccountErasureCleanup(thumbnail_item_ids=[3])
    db.add(row)
    db.commit()
    (tmp_path / "3.bin").write_text("late result")
    (tmp_path / "30.bin").write_text("other account")
    assert account_deletion.clean_thumbnails(db) == 1
    assert not (tmp_path / "3.bin").exists()
    assert (tmp_path / "30.bin").exists()
    row.created_at = datetime.now(timezone.utc) - timedelta(days=2)
    db.commit()
    account_deletion.clean_thumbnails(db)
    assert db.query(AccountErasureCleanup).count() == 0


def test_identity_migration_is_additive_and_downgrade_cannot_orphan_apple_accounts():
    path = Path(__file__).parents[1] / "alembic/versions/0022_ios_auth_identities.py"
    spec = importlib.util.spec_from_file_location("ios_identity_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0021_optional_gmail_connection"
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for table in ("apple_auth_challenges", "auth_identities", "account_erasure_cleanup"):
            conn.exec_driver_sql(f"DROP TABLE {table}")
        conn.exec_driver_sql("DROP INDEX ix_users_email_lower")
        conn.exec_driver_sql("INSERT INTO users (id,email,travel_name_aliases) VALUES (1,'legacy@example.com','[]')")
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            assert conn.exec_driver_sql("SELECT email FROM users WHERE id=1").scalar() == "legacy@example.com"
            assert {column["name"] for column in inspect(conn).get_columns("auth_identities")} == set(AuthIdentity.__table__.columns.keys())
            migration.downgrade()
            migration.upgrade()
            conn.exec_driver_sql("INSERT INTO auth_identities (user_id,provider,subject,created_at) VALUES (1,'apple','sub',CURRENT_TIMESTAMP)")
            with pytest.raises(RuntimeError, match="Apple identities"):
                migration.downgrade()
