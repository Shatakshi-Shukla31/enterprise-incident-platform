from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import NotificationType, RemediationStatus
from app.db.base import Base, CreatedAtMixin, str_enum
from app.models.incident import Incident
from app.models.user import User


class Notification(Base, CreatedAtMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("ix_notifications_user_unread", "user_id", "read_at"),
        # Scheduled jobs can run twice; this makes each alert fire once per recipient.
        Index(
            "uq_notifications_dedupe",
            "user_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("dedupe_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"))
    type: Mapped[NotificationType] = mapped_column(str_enum(NotificationType))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    dedupe_key: Mapped[str | None] = mapped_column(String(100))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Runbook(Base, CreatedAtMixin):
    """An allow-listed remediation. `action` must name a handler in services/remediation.py."""

    __tablename__ = "runbooks"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(64))
    category: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class RemediationRequest(Base, CreatedAtMixin):
    __tablename__ = "remediation_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    runbook_id: Mapped[int] = mapped_column(ForeignKey("runbooks.id"))
    requested_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[RemediationStatus] = mapped_column(
        str_enum(RemediationStatus), default=RemediationStatus.PENDING, index=True
    )
    target: Mapped[str] = mapped_column(String(200))
    justification: Mapped[str] = mapped_column(Text)
    decision_note: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    incident: Mapped[Incident] = relationship()
    runbook: Mapped[Runbook] = relationship()
    requested_by: Mapped[User] = relationship(foreign_keys=[requested_by_id])
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_id])
