"""Approval-gated remediation.

Only allow-listed runbooks can run, each needs approval by a second person, and nothing
the AI produces can start one. The handlers here are simulators: they validate the target
and report what would happen, because this demo has no infrastructure to act on. Replacing
one with a real integration means changing only its entry in ACTION_HANDLERS.
"""

import logging
import re
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.enums import PRIVILEGED_ROLES, NotificationType, RemediationStatus
from app.db.base import utcnow
from app.models import Incident, RemediationRequest, Runbook, User
from app.services import audit
from app.services.access import can_work_incident, scope_incidents
from app.services.errors import Conflict, Forbidden, NotFound, ServiceError
from app.services.incidents import get_incident
from app.services.notifications import notify, team_manager_ids
from app.workers.dispatch import enqueue

logger = logging.getLogger(__name__)

_TARGET_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:@/-]{0,199}$")


def _simulate(step: str) -> Callable[[str], dict]:
    def handler(target: str) -> dict:
        return {"simulated": True, "step": step, "target": target}

    return handler


ACTION_HANDLERS: dict[str, Callable[[str], dict]] = {
    "restart_service": _simulate("Service restart requested"),
    "flush_dns": _simulate("DNS cache flush requested"),
    "unlock_account": _simulate("Account unlock requested"),
    "rotate_credentials": _simulate("Credential rotation requested"),
    "failover_replica": _simulate("Replica failover requested"),
    "clear_mail_queue": _simulate("Mail queue retry requested"),
}

DEFAULT_RUNBOOKS = [
    (
        "restart-app-service",
        "Restart application service",
        "Rolling restart of a named application service.",
        "restart_service",
        "software_application",
    ),
    ("flush-dns-cache", "Flush DNS cache", "Flush the resolver cache on a named host.", "flush_dns", "network"),
    (
        "unlock-account",
        "Unlock user account",
        "Unlock a directory account after verifying the requester.",
        "unlock_account",
        "access_identity",
    ),
    (
        "rotate-service-credentials",
        "Rotate service credentials",
        "Rotate credentials for a compromised service account.",
        "rotate_credentials",
        "security",
    ),
    (
        "promote-read-replica",
        "Promote read replica",
        "Fail a database over to its healthy replica.",
        "failover_replica",
        "database",
    ),
    (
        "retry-mail-queue",
        "Retry mail queue",
        "Retry deferred messages on a mail transport host.",
        "clear_mail_queue",
        "email_collaboration",
    ),
]


def list_runbooks(db: Session) -> list[Runbook]:
    return list(db.scalars(select(Runbook).where(Runbook.is_active.is_(True)).order_by(Runbook.name)))


def request_remediation(
    db: Session, actor: User, incident_id: int, runbook_id: int, target: str, justification: str
) -> RemediationRequest:
    incident = get_incident(db, actor, incident_id)
    if not can_work_incident(actor, incident):
        raise Forbidden("You cannot act on this incident")
    runbook = db.get(Runbook, runbook_id)
    if runbook is None or not runbook.is_active:
        raise NotFound("Runbook not found")
    if not _TARGET_PATTERN.fullmatch(target):
        raise ServiceError("Target contains unsupported characters")
    request = RemediationRequest(
        incident_id=incident.id,
        runbook_id=runbook.id,
        requested_by_id=actor.id,
        target=target,
        justification=justification,
    )
    db.add(request)
    db.flush()
    audit.record(
        db,
        "remediation.requested",
        actor,
        incident.id,
        request_id=request.id,
        runbook=runbook.key,
        target=target,
    )
    notify(
        db,
        team_manager_ids(db, incident.team_id),
        NotificationType.APPROVAL_REQUIRED,
        f"Approval needed: {runbook.name}",
        f"{incident.number}: {justification[:150]}",
        incident.id,
    )
    db.commit()
    return _load(db, request.id)


def _load(db: Session, request_id: int, for_update: bool = False) -> RemediationRequest:
    stmt = select(RemediationRequest).where(RemediationRequest.id == request_id)
    if for_update:
        stmt = stmt.with_for_update()
    request = db.scalar(stmt)
    if request is None:
        raise NotFound("Remediation request not found")
    return request


def list_requests(
    db: Session, actor: User, status: RemediationStatus | None, incident_id: int | None
) -> list[RemediationRequest]:
    stmt = scope_incidents(
        select(RemediationRequest)
        .join(Incident)
        .options(
            joinedload(RemediationRequest.runbook),
            joinedload(RemediationRequest.requested_by),
            joinedload(RemediationRequest.decided_by),
            joinedload(RemediationRequest.incident),
        ),
        actor,
    )
    if status:
        stmt = stmt.where(RemediationRequest.status == status)
    if incident_id is not None:
        stmt = stmt.where(RemediationRequest.incident_id == incident_id)
    return list(db.scalars(stmt.order_by(RemediationRequest.id.desc()).limit(100)))


def decide(db: Session, actor: User, request_id: int, approve: bool, note: str | None) -> RemediationRequest:
    if actor.role not in PRIVILEGED_ROLES:
        raise Forbidden("Only managers can approve remediation")
    request = _load(db, request_id, for_update=True)
    if request.status != RemediationStatus.PENDING:
        raise Conflict("This request has already been decided")
    if request.requested_by_id == actor.id:
        raise Forbidden("You cannot decide your own request")

    request.status = RemediationStatus.APPROVED if approve else RemediationStatus.REJECTED
    request.decided_by_id = actor.id
    request.decided_at = utcnow()
    request.decision_note = note
    audit.record(
        db,
        f"remediation.{'approved' if approve else 'rejected'}",
        actor,
        request.incident_id,
        request_id=request.id,
    )
    if approve:
        enqueue("execute_remediation", request.id, after_commit_of=db)
    else:
        notify(
            db,
            [request.requested_by_id],
            NotificationType.REMEDIATION_RESULT,
            "Remediation rejected",
            note or "",
            request.incident_id,
        )
    db.commit()
    return _load(db, request.id)


def execute(db: Session, request_id: int) -> None:
    """Run an approved request once. Called by the worker."""
    request = _load(db, request_id, for_update=True)
    if request.status != RemediationStatus.APPROVED:
        logger.info("Skipping remediation %s in state %s", request_id, request.status)
        return
    request.status = RemediationStatus.RUNNING
    db.commit()

    runbook = db.get(Runbook, request.runbook_id)
    try:
        request.result = ACTION_HANDLERS[runbook.action](request.target)
        request.status = RemediationStatus.SUCCEEDED
    except Exception as exc:
        logger.exception("Remediation %s failed", request_id)
        request.result = {"error": str(exc)}
        request.status = RemediationStatus.FAILED
    request.finished_at = utcnow()
    audit.record(
        db,
        "remediation.finished",
        None,
        request.incident_id,
        request_id=request.id,
        status=request.status,
        result=request.result,
    )
    notify(
        db,
        [request.requested_by_id, request.decided_by_id],
        NotificationType.REMEDIATION_RESULT,
        f"{runbook.name}: {request.status}",
        request.target,
        request.incident_id,
    )
    db.commit()
