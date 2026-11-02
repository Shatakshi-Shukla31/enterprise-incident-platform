"""SLA clocks. Targets run on wall-clock time; the clock stops while an incident is on hold."""

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import OPEN_STATUSES, NotificationType, Priority, Status
from app.db.base import utcnow
from app.models import Incident, SLAPolicy
from app.services import audit
from app.services.notifications import notify, team_manager_ids

logger = logging.getLogger(__name__)

DEFAULT_TARGETS = {
    Priority.P1: (15, 4 * 60),
    Priority.P2: (30, 8 * 60),
    Priority.P3: (4 * 60, 24 * 60),
    Priority.P4: (8 * 60, 72 * 60),
}


def apply_due_dates(db: Session, incident: Incident, start: datetime) -> None:
    policy = db.get(SLAPolicy, incident.priority)
    if policy is None:
        raise RuntimeError(f"No SLA policy for {incident.priority}; run the seed script")
    incident.response_due_at = start + timedelta(minutes=policy.response_minutes)
    incident.resolution_due_at = start + timedelta(minutes=policy.resolution_minutes)


def pause(incident: Incident, now: datetime) -> None:
    incident.on_hold_since = now


def resume(incident: Incident, now: datetime) -> None:
    if incident.on_hold_since is None:
        return
    held = now - incident.on_hold_since
    incident.response_due_at += held
    incident.resolution_due_at += held
    incident.on_hold_since = None


def mark_breached(db: Session, incident: Incident, when: datetime) -> None:
    incident.sla_breached = True
    incident.sla_breached_at = when
    audit.record(db, "sla.breached", incident_id=incident.id, due=incident.resolution_due_at, at=when)


def run_sla_check(db: Session) -> dict[str, int]:
    """Mark breaches, escalate them, and alert on predicted risk. Safe to run concurrently."""
    now = utcnow()
    breached = _handle_breaches(db, now)
    response_alerts = _handle_response_overdue(db, now)
    risk_alerts = _handle_risk_alerts(db)
    db.commit()
    return {"breached": breached, "response_alerts": response_alerts, "risk_alerts": risk_alerts}


def _handle_breaches(db: Session, now: datetime) -> int:
    incidents = db.scalars(
        select(Incident)
        .where(
            Incident.status.in_(OPEN_STATUSES),
            Incident.status != Status.ON_HOLD,
            Incident.sla_breached.is_(False),
            Incident.resolution_due_at < now,
        )
        .with_for_update(skip_locked=True)
    ).all()
    for incident in incidents:
        mark_breached(db, incident, now)
        incident.escalation_level += 1
        audit.record(
            db,
            "incident.escalated",
            incident_id=incident.id,
            reason="sla_breach",
            level=incident.escalation_level,
        )
        notify(
            db,
            [incident.assignee_id, *team_manager_ids(db, incident.team_id)],
            NotificationType.SLA_BREACH,
            f"SLA breached: {incident.number}",
            f"{incident.priority} incident '{incident.title}' passed its resolution target.",
            incident.id,
            dedupe_key=f"breach:{incident.id}:{incident.resolution_due_at.timestamp():.0f}",
        )
    return len(incidents)


def _handle_response_overdue(db: Session, now: datetime) -> int:
    incidents = db.scalars(
        select(Incident).where(
            Incident.status.in_((Status.NEW, Status.ASSIGNED)),
            Incident.first_response_at.is_(None),
            Incident.response_due_at < now,
        )
    ).all()
    sent = 0
    for incident in incidents:
        sent += notify(
            db,
            [incident.assignee_id, *team_manager_ids(db, incident.team_id)],
            NotificationType.ESCALATED,
            f"Response overdue: {incident.number}",
            f"{incident.priority} incident '{incident.title}' has had no first response.",
            incident.id,
            dedupe_key=f"response:{incident.id}",
        )
    return sent


def _handle_risk_alerts(db: Session) -> int:
    threshold = get_settings().sla_risk_alert_threshold
    incidents = db.scalars(
        select(Incident)
        .where(
            Incident.status.in_(OPEN_STATUSES),
            Incident.sla_breached.is_(False),
            Incident.sla_risk_score >= threshold,
            Incident.sla_risk_alerted.is_(False),
        )
        .with_for_update(skip_locked=True)
    ).all()
    for incident in incidents:
        incident.sla_risk_alerted = True
        notify(
            db,
            [incident.assignee_id, *team_manager_ids(db, incident.team_id)],
            NotificationType.SLA_RISK,
            f"High SLA risk: {incident.number}",
            f"Estimated breach probability {incident.sla_risk_score:.0%}.",
            incident.id,
            dedupe_key=f"risk:{incident.id}",
        )
    return len(incidents)


def team_backlog(db: Session, team_id: int | None, before: datetime | None = None) -> tuple[int, int]:
    """(open incidents, open P1/P2 incidents) for a team. Used as a model feature."""
    if team_id is None:
        return 0, 0
    conditions = [Incident.team_id == team_id, Incident.status.in_(OPEN_STATUSES)]
    if before is not None:
        conditions.append(Incident.created_at < before)
    total, high = db.execute(
        select(
            func.count(),
            func.count().filter(Incident.priority.in_((Priority.P1, Priority.P2))),
        ).where(*conditions)
    ).one()
    return total, high
