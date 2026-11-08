from collections.abc import Iterable

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.enums import NotificationType, Role, Status
from app.db.base import utcnow
from app.models import Incident, Notification, User
from app.workers.dispatch import enqueue

NO_TICKET = "no_ticket"


def notify(
    db: Session,
    user_ids: Iterable[int | None],
    type_: NotificationType,
    title: str,
    body: str = "",
    incident_id: int | None = None,
    dedupe_key: str | None = None,
) -> int:
    """Create in-app notifications and queue email. A repeated dedupe_key is a no-op."""
    recipients = sorted({user_id for user_id in user_ids if user_id is not None})
    created = 0
    for user_id in recipients:
        statement = (
            insert(Notification)
            .values(
                user_id=user_id,
                incident_id=incident_id,
                type=type_,
                title=title,
                body=body,
                dedupe_key=dedupe_key,
                created_at=utcnow(),
            )
            .on_conflict_do_nothing(
                index_elements=["user_id", "dedupe_key"],
                index_where=Notification.dedupe_key.is_not(None),
            )
            .returning(Notification.id)
        )
        notification_id = db.execute(statement).scalar_one_or_none()
        if notification_id is not None:
            created += 1
            enqueue("send_notification_email", notification_id, after_commit_of=db)
    return created


def team_manager_ids(db: Session, team_id: int | None) -> list[int]:
    """Managers on the team, or every manager when the incident has no team yet."""
    stmt = select(User.id).where(User.role == Role.MANAGER, User.is_active.is_(True))
    if team_id is not None:
        scoped = list(db.scalars(stmt.where(User.team_id == team_id)))
        if scoped:
            return scoped
    return list(db.scalars(stmt))


def copy_busiest_manager_inbox(db: Session, user: User) -> int:
    """Give a new account a copy of the busiest manager's alerts. The shared demo account
    uses it, so a visitor sees real alerts from the first visit rather than an empty page."""
    source = db.scalar(
        select(Notification.user_id)
        .join(User, User.id == Notification.user_id)
        .where(User.role == Role.MANAGER, User.id != user.id)
        .group_by(Notification.user_id)
        .order_by(func.count().desc())
        .limit(1)
    )
    if source is None:
        return 0
    originals = db.scalars(select(Notification).where(Notification.user_id == source)).all()
    db.add_all(
        Notification(
            user_id=user.id,
            incident_id=item.incident_id,
            type=item.type,
            title=item.title,
            body=item.body,
            dedupe_key=item.dedupe_key,
            created_at=item.created_at,
        )
        for item in originals
    )
    return len(originals)


def list_for_user(db: Session, user: User, unread_only: bool, offset: int, limit: int) -> list[Notification]:
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    return list(db.scalars(stmt.order_by(Notification.id.desc()).offset(offset).limit(limit)))


def summary(db: Session, user: User) -> dict:
    """Unread and read counts by type and by the linked ticket's current status. Counted in
    SQL because the list is paged. Every type and status is returned, even at zero, so a
    chart keeps the same rows from one day to the next."""
    rows = db.execute(
        select(Notification.type, Incident.status, func.count(), func.count(Notification.read_at))
        .outerjoin(Incident, Notification.incident_id == Incident.id)
        .where(Notification.user_id == user.id)
        .group_by(Notification.type, Incident.status)
    ).all()
    by_type = {item: {"key": item.value, "unread": 0, "read": 0} for item in NotificationType}
    by_status = {item: {"key": item.value, "unread": 0, "read": 0} for item in Status}
    for type_, status, total, read in rows:
        linked = by_status.setdefault(status or NO_TICKET, {"key": NO_TICKET, "unread": 0, "read": 0})
        for counts in (by_type[type_], linked):
            counts["unread"] += total - read
            counts["read"] += read
    return {
        "total": sum(total for *_, total, _ in rows),
        "unread": sum(total - read for *_, total, read in rows),
        "by_type": list(by_type.values()),
        "by_status": list(by_status.values()),
    }


def mark_read(db: Session, user: User, notification_id: int | None = None) -> None:
    stmt = update(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
    if notification_id is not None:
        stmt = stmt.where(Notification.id == notification_id)
    db.execute(stmt.values(read_at=utcnow()))
    db.commit()
