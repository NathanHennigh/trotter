"""Optional consent, durable revocation and additive schema checks (offline)."""
import importlib.util
import json
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
import httplib2
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.models import Account, Base, User
from app.services.gmail_connection import connection_status, is_gmail_authorization_error, mark_gmail_reconnect


def http_failure(status, reason):
    return HttpError(httplib2.Response({"status": str(status)}), json.dumps({"error": {
        "errors": [{"reason": reason}], "message": "offline fixture"}}).encode())


@pytest.mark.parametrize("exc,expected", [
    (RefreshError("invalid_grant: Token has been expired or revoked."), True),
    (RefreshError("invalid_scope"), True),
    (RefreshError("temporarily_unavailable"), False),
    (http_failure(401, "authError"), True),
    (http_failure(403, "insufficientPermissions"), True),
    (http_failure(403, "ACCESS_TOKEN_SCOPE_INSUFFICIENT"), True),
    (http_failure(403, "rateLimitExceeded"), False),
    (http_failure(403, "accessNotConfigured"), False),
    (http_failure(429, "rateLimitExceeded"), False),
    (http_failure(503, "backendError"), False),
    (ConnectionError("offline"), False),
])
def test_only_revocation_and_missing_permissions_require_reconnect(exc, expected):
    assert is_gmail_authorization_error(exc) is expected


def test_connection_status_requires_credential_and_readable_scope():
    assert connection_status(None) == "not_connected"
    for scopes in ("", "openid email profile", "https://www.googleapis.com/auth/gmail.metadata"):
        assert connection_status(Account(scopes=scopes, refresh_token_encrypted=b"token")) == "needs_reconnect"
    for scopes in ("https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.modify", "https://mail.google.com/"):
        assert connection_status(Account(scopes=scopes, refresh_token_encrypted=b"token")) == "connected"
        assert connection_status(Account(scopes=scopes, refresh_token_encrypted=b"")) == "needs_reconnect"


def test_old_failed_import_cannot_disconnect_replaced_credentials():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="reconnected@example.com")
        db.add(user)
        db.flush()
        account = Account(user_id=user.id, provider="google", scopes="https://www.googleapis.com/auth/gmail.readonly", refresh_token_encrypted=b"replacement")
        db.add(account)
        db.commit()
        assert not mark_gmail_reconnect(db, user.id, b"old-token", RefreshError("invalid_grant"))
        assert connection_status(account) == "connected"
        assert mark_gmail_reconnect(db, user.id, b"replacement", RefreshError("invalid_grant"))
        db.commit()
        db.refresh(account)
        assert connection_status(account) == "needs_reconnect"
        assert account.refresh_token_encrypted == b"replacement"
        assert account.scopes == "https://www.googleapis.com/auth/gmail.readonly"


def test_optional_gmail_migration_preserves_all_columns_rows_and_credentials():
    path = Path(__file__).parents[1] / "alembic/versions/0021_optional_gmail_connection.py"
    spec = importlib.util.spec_from_file_location("optional_gmail_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0020_planner_transport_modes"
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="existing@example.com", name="Preserve me")
        db.add(user)
        db.flush()
        db.add(Account(user_id=user.id, provider="google", scopes="openid https://www.googleapis.com/auth/gmail.readonly",
                       refresh_token_encrypted=b"opaque ciphertext must be unchanged"))
        db.commit()
    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE accounts DROP COLUMN gmail_connection_status")
        original = {table: ([c["name"] for c in inspect(conn).get_columns(table)], conn.exec_driver_sql(f'SELECT * FROM "{table}"').all())
                    for table in Base.metadata.tables}
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        for table, (columns, rows) in original.items():
            projection = ','.join(f'"{column}"' for column in columns)
            assert conn.exec_driver_sql(f'SELECT {projection} FROM "{table}"').all() == rows
        assert {c["name"] for c in inspect(conn).get_columns("accounts")} == set(Account.__table__.columns.keys())
        assert conn.exec_driver_sql("SELECT gmail_connection_status FROM accounts").scalar() is None
        with Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()
            migration.upgrade()
            conn.exec_driver_sql("UPDATE accounts SET gmail_connection_status='needs_reconnect'")
            with pytest.raises(RuntimeError, match="authorization state"):
                migration.downgrade()
