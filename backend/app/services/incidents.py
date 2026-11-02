from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.enums import (
    ALLOWED_TRANSITIONS,
    OPEN_STATUSES,
    PRIVILEGED_ROLES,
    Category,
    Channel,
    Level,
    NotificationType,
    PredictionKind,
    Priority,
    Role,
    Status,
    compute_priority,
)
from app.db.base import utcnow
from app.models import AuditLog, Comment, Incident, Prediction, Team, User
from app.services import audit, sla, triage
from app.services.access import can_view_incident, can_work_incident, is_staff, scope_incidents
from app.services.errors import Conflict, Forbidden, NotFound, ServiceError
from app.services.notifications import notify, team_manager_ids
from app.workers.dispatch import enqueue

_RELATIONS = (
    joinedload(Incident.requester),
    joinedload(Incident.assignee),
    joinedload(Incident.team),
)
SORT_COLUMNS = {
    "created_at": Incident.created_at,
    "updated_at": Incident.updated_at,
    "priority": Incident.priority,
    "resolution_due_at": Incident.resolution_due_at,
    "sla_risk_score": Incident.sla_risk_score,
}


@dataclass(frozen=True)
class IncidentFilters:
    status: Sequence[Status] = ()
    priority: Sequence[Priority] = ()
    category: Category | None = None
    team_id: int | None = None
    assignee_id: int | None = None
    breached: bool | None = None
    open_only: bool = False
    q: str | None = None
    sort: str = "created_at"
    descending: bool = True


def create_incident(
    db: Session,
    actor: User,
    title: str,
    description: str,
    impact: Level,
    urgency: Level,
    channel: Channel = Channel.PORTAL,
) -> Incident:
    now = utcnow()
    incident = Incident(
        title=title,
        description=description,
        impact=impact,
        urgency=urgency,
        priority=compute_priority(impact, urgency),
        channel=channel,
        requester_id=actor.id,
        created_at=now,
    )
    sla.apply_due_dates(db, incident, now)
    db.add(incident)
    db.flush()
    audit.record(db, "incident.created", actor, incident.id, priority=incident.priority, channel=channel)
    triage.triage_incident(db, incident)
    if incident.priority in (Priority.P1, Priority.P2):
        notify(
            db,
            team_manager_ids(db, incident.team_id),
            NotificationType.ESCALATED,
            f"New {incident.priority}: {incident.number}",
            incident.title,
            incident.id,
        )
    db.commit()
    return get_incident(db, actor, incident.id)


def get_incident(db: Session, actor: User, incident_id: int) -> Incident:
    # populate_existing: sessions keep objects across commits, and this query is what
    # reloads relationships after an assignment changes them.
    incident = db.scalar(
        select(Incident)
        .options(*_RELATIONS)
        .where(Incident.id == incident_id)
        .execution_options(populate_existing=True)
    )
    # 404 rather than 403, so ids cannot be probed for existence.
    if incident is None or not can_view_incident(actor, incident):
        raise NotFound("Incident not found")
    return incident


def _get_workable(db: Session, actor: User, incident_id: int) -> Incident:
    incident = get_incident(db, actor, incident_id)
    if not can_work_incident(actor, incident):
        raise Forbidden("You cannot modify this incident")
    return incident


def list_incidents(
    db: Session, actor: User, filters: IncidentFilters, offset: int, limit: int
) -> tuple[list[Incident], int]:
    stmt = scope_incidents(select(Incident), actor)
    if filters.status:
        stmt = stmt.where(Incident.status.in_(filters.status))
    if filters.open_only:
        stmt = stmt.where(Incident.status.in_(OPEN_STATUSES))
    if filters.priority:
        stmt = stmt.where(Incident.priority.in_(filters.priority))
    if filters.category:
        stmt = stmt.where(Incident.category == filters.category)
    if filters.team_id is not None:
        stmt = stmt.where(Incident.team_id == filters.team_id)
    if filters.assignee_id is not None:
        stmt = stmt.where(Incident.assignee_id == filters.assignee_id)
    if filters.breached is not None:
        stmt = stmt.where(Incident.sla_breached.is_(filters.breached))
    if filters.q:
        stmt = stmt.where(_search_condition(filters.q))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    column = SORT_COLUMNS[filters.sort]
    order = desc(column).nulls_last() if filters.descending else asc(column).nulls_last()
    rows = db.scalars(stmt.options(*_RELATIONS).order_by(order, Incident.id.desc()).offset(offset).limit(limit)).all()
    return list(rows), total


def _search_condition(query: str):
    digits = query.upper().removeprefix("INC")
    if digits.isdigit() and int(digits) < 2**31:
        return Incident.id == int(digits)
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped}%"
    return or_(
        Incident.title.ilike(pattern, escape="\\"),
        Incident.description.ilike(pattern, escape="\\"),
    )


def update_details(
    db: Session,
    actor: User,
    incident_id: int,
    title: str | None,
    description: str | None,
    impact: Level | None,
    urgency: Level | None,
) -> Incident:
    incident = _get_workable(db, actor, incident_id)
    if incident.status == Status.CLOSED:
        raise Conflict("Closed incidents cannot be edited")
    changes: dict[str, object] = {}
    for field, value in (
        ("title", title),
        ("description", description),
        ("impact", impact),
        ("urgency", urgency),
    ):
        if value is not None and value != getattr(incident, field):
            changes[field] = {"from": getattr(incident, field), "to": value}
            setattr(incident, field, value)
    if "impact" in changes or "urgency" in changes:
        new_priority = compute_priority(incident.impact, incident.urgency)
        if new_priority != incident.priority:
            changes["priority"] = {"from": incident.priority, "to": new_priority}
            incident.priority = new_priority
            sla.apply_due_dates(db, incident, incident.created_at)
    if changes:
        audit.record(db, "incident.updated", actor, incident.id, **changes)
        if "description" in changes or "title" in changes or "priority" in changes:
            triage.score_sla_risk(db, incident)
    db.commit()
    return get_incident(db, actor, incident.id)


def change_status(
    db: Session,
    actor: User,
    incident_id: int,
    new_status: Status,
    resolution_notes: str | None = None,
) -> Incident:
    incident = _get_workable(db, actor, incident_id)
    old_status = incident.status
    if new_status == old_status:
        return incident
    if new_status not in ALLOWED_TRANSITIONS[old_status]:
        raise Conflict(f"Cannot move an incident from {old_status} to {new_status}")
    if new_status == Status.RESOLVED and not (resolution_notes and resolution_notes.strip()):
        raise ServiceError("Resolution notes are required to resolve an incident")

    now = utcnow()
    if old_status == Status.ON_HOLD:
        sla.resume(incident, now)
    if new_status == Status.ON_HOLD:
        sla.pause(incident, now)
    if new_status == Status.IN_PROGRESS and incident.first_response_at is None:
        incident.first_response_at = now
    if new_status == Status.RESOLVED:
        incident.resolved_at = now
        incident.resolution_notes = resolution_notes.strip()
        incident.first_response_at = incident.first_response_at or now
        if now > incident.resolution_due_at and not incident.sla_breached:
            sla.mark_breached(db, incident, now)
    if old_status == Status.RESOLVED and new_status == Status.IN_PROGRESS:
        incident.resolved_at = None
    if new_status == Status.CLOSED:
        incident.closed_at = now

    incident.status = new_status
    audit.record(db, "incident.status_changed", actor, incident.id, **{"from": old_status, "to": new_status})
    notify(
        db,
        [incident.requester_id, incident.assignee_id],
        NotificationType.STATUS_CHANGED,
        f"{incident.number} is now {new_status.replace('_', ' ')}",
        incident.title,
        incident.id,
    )
    if new_status == Status.RESOLVED:
        enqueue("index_resolved_incident", incident.id, after_commit_of=db)
    elif old_status == Status.RESOLVED and new_status == Status.IN_PROGRESS:
        enqueue("remove_incident_from_knowledge", incident.id, after_commit_of=db)
    db.commit()
    return get_incident(db, actor, incident.id)


def assign(
    db: Session,
    actor: User,
    incident_id: int,
    team_id: int | None,
    assignee_id: int | None,
) -> Incident:
    incident = _get_workable(db, actor, incident_id)
    if incident.status in (Status.RESOLVED, Status.CLOSED):
        raise Conflict("Resolved incidents cannot be reassigned")
    if team_id is None and assignee_id is None:
        raise ServiceError("Provide a team, an assignee, or both")

    assignee = db.get(User, assignee_id) if assignee_id is not None else None
    if assignee_id is not None and (assignee is None or not assignee.is_active or not is_staff(assignee)):
        raise ServiceError("Assignee must be an active support user")
    target_team = team_id if team_id is not None else (assignee.team_id if assignee else None)
    if target_team is not None:
        team = db.get(Team, target_team)
        if team is None or not team.is_active:
            raise ServiceError("Unknown team")
    if assignee and team_id is not None and assignee.team_id not in (None, team_id):
        raise ServiceError("Assignee is not a member of that team")
    if actor.role == Role.AGENT:
        if assignee_id not in (None, actor.id):
            raise Forbidden("Agents can only assign incidents to themselves")
        if target_team not in (None, actor.team_id) and team_id is not None:
            raise Forbidden("Agents cannot move incidents to other teams")

    before = {"team_id": incident.team_id, "assignee_id": incident.assignee_id}
    if target_team is not None:
        incident.team_id = target_team
    if assignee is not None:
        incident.assignee_id = assignee.id
        if incident.status == Status.NEW:
            incident.status = Status.ASSIGNED
    audit.record(
        db,
        "incident.assigned",
        actor,
        incident.id,
        before=before,
        after={"team_id": incident.team_id, "assignee_id": incident.assignee_id},
    )
    triage.record_routing_outcome(db, incident)
    triage.score_sla_risk(db, incident)
    if assignee is not None and assignee.id != actor.id:
        notify(
            db,
            [assignee.id],
            NotificationType.ASSIGNED,
            f"{incident.number} assigned to you",
            incident.title,
            incident.id,
        )
    db.commit()
    return get_incident(db, actor, incident.id)


def escalate(db: Session, actor: User, incident_id: int, reason: str) -> Incident:
    incident = _get_workable(db, actor, incident_id)
    if incident.status in (Status.RESOLVED, Status.CLOSED):
        raise Conflict("Resolved incidents cannot be escalated")
    incident.escalation_level += 1
    audit.record(
        db,
        "incident.escalated",
        actor,
        incident.id,
        reason=reason,
        level=incident.escalation_level,
    )
    notify(
        db,
        team_manager_ids(db, incident.team_id),
        NotificationType.ESCALATED,
        f"{incident.number} escalated to level {incident.escalation_level}",
        reason,
        incident.id,
    )
    db.commit()
    return get_incident(db, actor, incident.id)


def correct_category(db: Session, actor: User, incident_id: int, category: Category) -> Incident:
    incident = _get_workable(db, actor, incident_id)
    previous = incident.category
    incident.category = category
    incident.category_corrected = True
    prediction = db.scalar(
        select(Prediction)
        .where(
            Prediction.incident_id == incident.id,
            Prediction.kind == PredictionKind.CATEGORY,
        )
        .order_by(Prediction.id.desc())
    )
    if prediction is not None:
        prediction.accepted = prediction.value == category
        prediction.corrected_value = None if prediction.accepted else category
    audit.record(db, "incident.category_corrected", actor, incident.id, **{"from": previous, "to": category})
    triage.score_sla_risk(db, incident)
    db.commit()
    return get_incident(db, actor, incident.id)


def add_comment(db: Session, actor: User, incident_id: int, body: str, is_internal: bool) -> Comment:
    incident = get_incident(db, actor, incident_id)
    if incident.status == Status.CLOSED:
        raise Conflict("Closed incidents cannot take new comments")
    staff = is_staff(actor)
    if is_internal and not staff:
        raise Forbidden("Only support staff can write internal notes")
    comment = Comment(incident_id=incident.id, author_id=actor.id, body=body, is_internal=is_internal)
    db.add(comment)
    if staff and not is_internal and incident.first_response_at is None:
        incident.first_response_at = utcnow()
    audit.record(db, "incident.commented", actor, incident.id, internal=is_internal)
    recipients = [incident.assignee_id] if is_internal else [incident.assignee_id, incident.requester_id]
    notify(
        db,
        [user_id for user_id in recipients if user_id != actor.id],
        NotificationType.COMMENT,
        f"New comment on {incident.number}",
        body[:200],
        incident.id,
    )
    db.commit()
    db.refresh(comment, ["author"])
    return comment


def list_comments(db: Session, actor: User, incident_id: int) -> list[Comment]:
    incident = get_incident(db, actor, incident_id)
    stmt = (
        select(Comment)
        .options(joinedload(Comment.author))
        .where(Comment.incident_id == incident.id)
        .order_by(Comment.id)
    )
    if not is_staff(actor):
        stmt = stmt.where(Comment.is_internal.is_(False))
    return list(db.scalars(stmt))


def audit_history(db: Session, actor: User, incident_id: int) -> list[AuditLog]:
    incident = _get_workable(db, actor, incident_id)
    return list(
        db.scalars(
            select(AuditLog)
            .options(joinedload(AuditLog.actor))
            .where(AuditLog.incident_id == incident.id)
            .order_by(AuditLog.id)
        )
    )


def list_predictions(db: Session, actor: User, incident_id: int) -> list[Prediction]:
    incident = _get_workable(db, actor, incident_id)
    return list(
        db.scalars(select(Prediction).where(Prediction.incident_id == incident.id).order_by(Prediction.id.desc()))
    )


def can_see_all(actor: User) -> bool:
    return actor.role in PRIVILEGED_ROLES
