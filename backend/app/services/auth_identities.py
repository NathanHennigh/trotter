"""Identity linking is explicit; verified email only bootstraps legacy Google users."""
from fastapi import HTTPException
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from ..models import AuthIdentity, User


def providers(db: Session, user_id: int) -> list[str]:
    values = [row[0] for row in db.query(AuthIdentity.provider).filter_by(user_id=user_id).order_by(AuthIdentity.provider)]
    # Every pre-migration account was created through Google.
    return values or ["google"]


def identity(db: Session, provider: str, subject: str):
    return db.query(AuthIdentity).filter_by(provider=provider, subject=subject).first()


def subject_from(info: dict) -> str:
    subject = info.get("sub")
    if not isinstance(subject, str) or not subject or len(subject) > 255:
        raise HTTPException(400, "invalid_provider_subject")
    return subject


def email_owner(db: Session, email: str):
    linked = db.query(AuthIdentity).filter(func.lower(AuthIdentity.email) == email.lower()).first()
    if linked:
        return db.get(User, linked.user_id)
    # Primary email is an identity only for legacy users. After provider subjects
    # exist, the latest verified provider emails control email-bound invitations.
    return db.query(User).filter(func.lower(User.email) == email.lower(),
        ~exists(select(AuthIdentity.id).where(AuthIdentity.user_id == User.id))).first()


def verified_emails(db: Session, user: User) -> set[str]:
    rows = db.query(AuthIdentity).filter_by(user_id=user.id).all()
    return {row.email.casefold() for row in rows if row.email} if rows else {user.email.casefold()}


def resolve_google_user(db: Session, info: dict, *, expected_user_id: int | None = None) -> User:
    subject = subject_from(info)
    email = info.get("email")
    if not isinstance(email, str) or not email or len(email) > 255:
        raise HTTPException(400, "invalid_provider_email")
    linked = identity(db, "google", subject)
    if linked:
        user = db.get(User, linked.user_id)
        if expected_user_id is not None and user.id != expected_user_id:
            raise HTTPException(409, "reauth_wrong_account")
        owner = email_owner(db, email)
        if owner and owner.id != user.id:
            raise HTTPException(409, "account_link_required")
        if linked.email and user.email.casefold() == linked.email.casefold():
            user.email = email
        linked.email = email
        return user
    user = email_owner(db, email)
    if user and db.query(AuthIdentity).filter_by(user_id=user.id).first():
        # An Apple user's matching email is not permission to link Google.
        raise HTTPException(409, "account_link_required")
    if expected_user_id is not None and (not user or user.id != expected_user_id):
        raise HTTPException(409, "reauth_wrong_account")
    if user is None:
        user = User(email=email, name=info.get("name"))
        db.add(user)
        db.flush()
    db.add(AuthIdentity(user_id=user.id, provider="google", subject=subject, email=email))
    return user


def link_google_for_gmail(db: Session, user: User, info: dict) -> None:
    subject = subject_from(info)
    email = info.get("email") or ""
    linked = identity(db, "google", subject)
    owned = db.query(AuthIdentity).filter_by(user_id=user.id, provider="google").first()
    if (linked and linked.user_id != user.id) or (owned and owned.subject != subject):
        raise HTTPException(409, "gmail_wrong_account")
    other = email_owner(db, email)
    if other and other.id != user.id:
        raise HTTPException(409, "gmail_wrong_account")
    # Legacy / Google accounts retain their existing same-account behavior.
    apple = db.query(AuthIdentity).filter_by(user_id=user.id, provider="apple").first()
    if not owned and not apple and user.email.casefold() != email.casefold():
        raise HTTPException(409, "gmail_wrong_account")
    if not owned:
        db.add(AuthIdentity(user_id=user.id, provider="google", subject=subject, email=email))
    else:
        if owned.email and user.email.casefold() == owned.email.casefold():
            user.email = email
        owned.email = email
