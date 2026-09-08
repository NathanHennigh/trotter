"""Serialize one user's itinerary projection across import workers and repairs."""
from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import os
from pathlib import Path
import tempfile

from sqlalchemy import text


class ImportAlreadyRunning(RuntimeError):
    pass


@contextmanager
def user_import_lock(engine, user_id: int):
    # A dedicated PostgreSQL connection keeps the advisory lock across the
    # per-message commits on the worker's separate ORM session.
    identity = f"trotter-booking-import:{user_id}"
    if engine.dialect.name == "postgresql":
        key = int.from_bytes(sha256(identity.encode()).digest()[:8], "big", signed=True)
        with engine.connect() as connection:
            acquired = connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}).scalar()
            connection.commit()
            if not acquired:
                raise ImportAlreadyRunning("Another flight import is already running for this account")
            try:
                yield
            finally:
                # Never return a session-level lock to the connection pool.
                try:
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                    connection.commit()
                except BaseException:
                    connection.invalidate()
                    raise
        return

    if engine.dialect.name != "sqlite":
        raise RuntimeError("Flight import locking is not configured for this database")
    database = engine.url.database
    database_key = os.path.normcase(str(Path(database).resolve())) if database and database != ":memory:" else f"memory:{id(engine)}"
    lock_key = sha256(f"{database_key}:{identity}".encode()).hexdigest()
    lock_path = Path(tempfile.gettempdir()) / f"trotter-import-{lock_key}.lock"
    # Leave the lock file in place: unlinking it can let two processes lock
    # different inodes. OS locks are released automatically if a worker exits.
    with lock_path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ImportAlreadyRunning("Another flight import is already running for this account") from exc
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ImportAlreadyRunning("Another flight import is already running for this account") from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
