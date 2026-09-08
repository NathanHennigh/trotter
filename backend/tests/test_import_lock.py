from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

from app.services.import_lock import ImportAlreadyRunning, user_import_lock


def test_separate_workers_cannot_import_same_user_simultaneously(tmp_path):
    url = f"sqlite:///{tmp_path / 'archive.sqlite'}"
    first, second = create_engine(url), create_engine(url)
    with user_import_lock(first, 7):
        with pytest.raises(ImportAlreadyRunning):
            with user_import_lock(second, 7):
                pytest.fail("A second writer entered the same archive")
        with user_import_lock(second, 8):
            pass
    with user_import_lock(second, 7):
        pass
    first.dispose()
    second.dispose()


def test_worker_failure_releases_import_lock(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'archive.sqlite'}")
    with pytest.raises(ValueError):
        with user_import_lock(engine, 7):
            raise ValueError("Injected worker failure")
    with user_import_lock(engine, 7):
        pass
    engine.dispose()


def test_postgresql_lock_is_held_on_dedicated_connection_until_exit():
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar.return_value = True
    with pytest.raises(ValueError):
        with user_import_lock(engine, 7):
            assert connection.execute.call_count == 1
            raise ValueError("Injected worker failure")
    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    assert statements == ["SELECT pg_try_advisory_lock(:key)", "SELECT pg_advisory_unlock(:key)"]
    assert connection.commit.call_count == 2


def test_postgresql_does_not_release_someone_elses_lock():
    engine = MagicMock()
    engine.dialect.name = "postgresql"
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalar.return_value = False
    with pytest.raises(ImportAlreadyRunning):
        with user_import_lock(engine, 7):
            pytest.fail("Lock was unavailable")
    assert connection.execute.call_count == 1
