import uuid
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    hash_password,
    hash_token,
    needs_rehash,
    new_refresh_token,
    verify_password,
)
from app.db.base import utcnow
from app.models import RefreshToken, User
from app.services import audit
from app.services.errors import ServiceError


class InvalidCredentials(ServiceError):
    status_code = 401


def authenticate(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.lower().strip()))
    if not verify_password(password, user.password_hash if user else None) or user is None:
        audit.record(db, "auth.login_failed", email=email[:255])
        db.commit()
        raise InvalidCredentials("Incorrect email or password")
    if not user.is_active:
        raise InvalidCredentials("Incorrect email or password")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    audit.record(db, "auth.login", user)
    return user


def issue_tokens(db: Session, user: User, family_id: str | None = None) -> tuple[str, int, str]:
    access, expires_in = create_access_token(user.id, user.role)
    raw_refresh, token_hash = new_refresh_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            family_id=family_id or uuid.uuid4().hex,
            token_hash=token_hash,
            expires_at=utcnow() + timedelta(days=get_settings().refresh_token_days),
        )
    )
    db.commit()
    return access, expires_in, raw_refresh


def rotate_refresh_token(db: Session, raw_token: str) -> tuple[User, tuple[str, int, str]]:
    stored = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)).with_for_update())
    if stored is None:
        raise InvalidCredentials("Invalid refresh token")
    if stored.revoked_at is not None:
        # A rotated token was replayed, so it may be stolen: end the whole session.
        revoke_family(db, stored.family_id)
        audit.record(db, "auth.refresh_reuse_detected", incident_id=None, user_id=stored.user_id)
        db.commit()
        raise InvalidCredentials("Invalid refresh token")
    if stored.expires_at < utcnow():
        raise InvalidCredentials("Refresh token expired")
    user = db.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise InvalidCredentials("Invalid refresh token")
    stored.revoked_at = utcnow()
    return user, issue_tokens(db, user, stored.family_id)


def revoke_family(db: Session, family_id: str) -> None:
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


def logout(db: Session, raw_token: str | None) -> None:
    if not raw_token:
        return
    stored = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(raw_token)))
    if stored is not None:
        revoke_family(db, stored.family_id)
        db.commit()


def change_password(db: Session, user: User, current: str, new: str) -> None:
    if not verify_password(current, user.password_hash):
        raise InvalidCredentials("Current password is incorrect")
    user.password_hash = hash_password(new)
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    audit.record(db, "auth.password_changed", user)
    db.commit()
