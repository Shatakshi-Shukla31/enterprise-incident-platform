"""Authorization rules, kept in one place so API and AI code paths cannot drift apart."""

from sqlalchemy import Select, or_

from app.core.enums import PRIVILEGED_ROLES, Role
from app.models import Incident, KnowledgeDocument, User


def is_staff(user: User) -> bool:
    return user.role != Role.REQUESTER


def scope_incidents(stmt: Select, user: User) -> Select:
    """Restrict an incident query to what `user` may see."""
    if user.role in PRIVILEGED_ROLES:
        return stmt
    if user.role == Role.AGENT:
        return stmt.where(
            or_(
                Incident.team_id == user.team_id,
                Incident.team_id.is_(None),
                Incident.assignee_id == user.id,
            )
        )
    return stmt.where(Incident.requester_id == user.id)


def can_view_incident(user: User, incident: Incident) -> bool:
    if user.role in PRIVILEGED_ROLES:
        return True
    if user.role == Role.AGENT:
        return incident.team_id is None or incident.team_id == user.team_id or incident.assignee_id == user.id
    return incident.requester_id == user.id


def can_work_incident(user: User, incident: Incident) -> bool:
    return is_staff(user) and can_view_incident(user, incident)


def scope_documents(stmt: Select, user: User) -> Select:
    """Restrict a knowledge query. Applied in SQL, before ranking, so that a document the
    user cannot read can never reach the prompt, the answer, or the citations."""
    if user.role == Role.ADMIN or user.role == Role.MANAGER:
        return stmt
    if user.role == Role.AGENT:
        return stmt.where(
            or_(
                KnowledgeDocument.access_level != "restricted",
                KnowledgeDocument.team_id == user.team_id,
            )
        )
    return stmt.where(KnowledgeDocument.access_level == "public")
