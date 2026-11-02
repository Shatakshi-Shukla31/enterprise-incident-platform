from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import Category, Channel, Level, Priority, Status
from app.db.base import Base, CreatedAtMixin, str_enum, utcnow
from app.models.user import Team, User


class SLAPolicy(Base):
    __tablename__ = "sla_policies"

    priority: Mapped[Priority] = mapped_column(str_enum(Priority), primary_key=True)
    response_minutes: Mapped[int] = mapped_column(Integer)
    resolution_minutes: Mapped[int] = mapped_column(Integer)


class Incident(Base, CreatedAtMixin):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_status_due", "status", "resolution_due_at"),
        Index("ix_incidents_team_status", "team_id", "status"),
        Index("ix_incidents_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    impact: Mapped[Level] = mapped_column(str_enum(Level, "impact"))
    urgency: Mapped[Level] = mapped_column(str_enum(Level, "urgency"))
    priority: Mapped[Priority] = mapped_column(str_enum(Priority), index=True)
    status: Mapped[Status] = mapped_column(str_enum(Status), default=Status.NEW, index=True)
    channel: Mapped[Channel] = mapped_column(str_enum(Channel), default=Channel.PORTAL)

    category: Mapped[Category | None] = mapped_column(str_enum(Category), index=True)
    category_confidence: Mapped[float | None] = mapped_column(Float)
    category_corrected: Mapped[bool] = mapped_column(Boolean, default=False)

    requester_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))

    response_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolution_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    on_hold_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    sla_breached: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    sla_breached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    resolution_notes: Mapped[str | None] = mapped_column(Text)

    sla_risk_score: Mapped[float | None] = mapped_column(Float)
    sla_risk_scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_risk_alerted: Mapped[bool] = mapped_column(Boolean, default=False)

    requester: Mapped[User] = relationship(foreign_keys=[requester_id])
    assignee: Mapped[User | None] = relationship(foreign_keys=[assignee_id])
    team: Mapped[Team | None] = relationship()

    @property
    def number(self) -> str:
        return f"INC{self.id:07d}"


class Comment(Base, CreatedAtMixin):
    __tablename__ = "incident_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False)

    author: Mapped[User] = relationship()


class AuditLog(Base, CreatedAtMixin):
    """Append-only. A database trigger rejects UPDATE and DELETE."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(64), index=True)
    changes: Mapped[dict] = mapped_column(JSONB, default=dict)

    actor: Mapped[User | None] = relationship()
