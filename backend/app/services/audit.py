from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record(
    db: Session,
    action: str,
    actor: User | None = None,
    incident_id: int | None = None,
    **changes: object,
) -> None:
    db.add(
        AuditLog(
            action=action,
            actor_id=actor.id if actor else None,
            incident_id=incident_id,
            changes={key: _plain(value) for key, value in changes.items()},
        )
    )


def _plain(value: object) -> object:
    if isinstance(value, str | int | float | bool | type(None) | list | dict):
        return value
    return str(value)
