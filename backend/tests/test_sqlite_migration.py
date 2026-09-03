from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Message, MessageStatus, User
from scripts.migrate_sqlite_to_postgres import copy_database


def test_copy_database_moves_rows_between_empty_databases(tmp_path):
    source = create_engine(f"sqlite:///{tmp_path / 'source.db'}")
    target = create_engine(f"sqlite:///{tmp_path / 'target.db'}")
    Base.metadata.create_all(source)
    Base.metadata.create_all(target)

    with Session(source) as session:
        session.add(User(email="home-server@example.com", name="Home Server"))
        session.commit()

    copied = copy_database(source, target)

    assert copied["users"] == 1
    with Session(target) as session:
        user = session.query(User).one()
        assert user.email == "home-server@example.com"


def test_copy_database_refuses_nonempty_target(tmp_path):
    source = create_engine(f"sqlite:///{tmp_path / 'source.db'}")
    target = create_engine(f"sqlite:///{tmp_path / 'target.db'}")
    Base.metadata.create_all(source)
    Base.metadata.create_all(target)

    with Session(target) as session:
        session.add(User(email="existing@example.com"))
        session.commit()

    try:
        copy_database(source, target)
    except RuntimeError as exc:
        assert "not empty" in str(exc)
    else:
        raise AssertionError("Expected a nonempty target to be rejected")


def test_copy_database_normalizes_legacy_enum_names(tmp_path):
    source = create_engine(f"sqlite:///{tmp_path / 'source.db'}")
    target = create_engine(f"sqlite:///{tmp_path / 'target.db'}")
    Base.metadata.create_all(source)
    Base.metadata.create_all(target)

    with Session(source) as session:
        session.add(User(id=1, email="legacy@example.com"))
        session.add(
            Message(
                id=1,
                user_id=1,
                provider_msg_id="legacy-message",
                status=MessageStatus.ACCEPTED,
            )
        )
        session.commit()
    with source.begin() as connection:
        connection.exec_driver_sql("UPDATE messages SET status = 'ACCEPTED' WHERE id = 1")

    copy_database(source, target)

    with Session(target) as session:
        assert session.get(Message, 1).status is MessageStatus.ACCEPTED
