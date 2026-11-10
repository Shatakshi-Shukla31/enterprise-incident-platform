"""Background jobs. Each one is idempotent, because a task can run more than once:
acknowledgement is late, and a worker can die between finishing and acknowledging."""

import logging
import smtplib
from datetime import timedelta
from email.message import EmailMessage

from sqlalchemy import select

from app.core.config import get_settings
from app.core.enums import DocumentSource, Status
from app.db.base import utcnow
from app.db.session import new_session
from app.models import Incident, KnowledgeDocument, Notification, User
from app.rag import ingest
from app.services import audit, remediation, sla, triage
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

AUTO_CLOSE_AFTER = timedelta(days=7)


@celery_app.task
def check_sla() -> dict:
    with new_session() as db:
        result = sla.run_sla_check(db)
    logger.info("SLA check %s", result, extra={"task": "check_sla"})
    return result


@celery_app.task
def rescore_open_incidents() -> int:
    with new_session() as db:
        incidents = db.scalars(
            select(Incident)
            .where(Incident.status.in_((Status.NEW, Status.ASSIGNED, Status.IN_PROGRESS)))
            .where(Incident.sla_breached.is_(False))
            .limit(500)
        ).all()
        for incident in incidents:
            triage.score_sla_risk(db, incident)
        db.commit()
    return len(incidents)


@celery_app.task(autoretry_for=(OSError,), retry_backoff=True, max_retries=3)
def index_resolved_incident(incident_id: int) -> None:
    with new_session() as db:
        incident = db.get(Incident, incident_id)
        if incident is None or incident.status not in (Status.RESOLVED, Status.CLOSED):
            return
        ingest.index_resolved_incident(db, incident)
        db.commit()


@celery_app.task
def remove_incident_from_knowledge(incident_id: int) -> None:
    with new_session() as db:
        incident = db.get(Incident, incident_id)
        if incident is not None:
            ingest.remove_incident(db, incident)
            db.commit()


@celery_app.task
def reconcile_resolved_incidents(limit: int = 200) -> int:
    """Index resolved tickets whose original task was lost, for example during a broker outage."""
    with new_session() as db:
        if get_settings().single_process:
            # A hosted deploy updates the bundled articles without rerunning the demo seed.
            # This job also runs shortly after startup, and unchanged articles are skipped.
            ingest.ingest_directory(db)
        indexed = select(KnowledgeDocument.source_ref).where(
            KnowledgeDocument.source_type == DocumentSource.RESOLVED_INCIDENT
        )
        known = set(db.scalars(indexed))
        candidates = db.scalars(
            select(Incident)
            .where(Incident.status.in_((Status.RESOLVED, Status.CLOSED)))
            .order_by(Incident.id.desc())
            .limit(limit * 5)
        ).all()
        missing = [incident for incident in candidates if incident.number not in known][:limit]
        for incident in missing:
            ingest.index_resolved_incident(db, incident)
        db.commit()
    return len(missing)


@celery_app.task
def auto_close_resolved() -> int:
    with new_session() as db:
        incidents = db.scalars(
            select(Incident)
            .where(Incident.status == Status.RESOLVED, Incident.resolved_at < utcnow() - AUTO_CLOSE_AFTER)
            .with_for_update(skip_locked=True)
        ).all()
        for incident in incidents:
            incident.status = Status.CLOSED
            incident.closed_at = utcnow()
            audit.record(db, "incident.auto_closed", None, incident.id)
        db.commit()
    return len(incidents)


@celery_app.task
def execute_remediation(request_id: int) -> None:
    with new_session() as db:
        remediation.execute(db, request_id)


@celery_app.task(autoretry_for=(OSError, smtplib.SMTPException), retry_backoff=True, max_retries=3)
def send_notification_email(notification_id: int) -> None:
    settings = get_settings()
    if not settings.smtp_host:
        return
    with new_session() as db:
        notification = db.get(Notification, notification_id)
        user = db.get(User, notification.user_id) if notification else None
        if notification is None or user is None:
            return
        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = user.email
        message["Subject"] = notification.title
        message.set_content(notification.body or notification.title)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as client:
        client.starttls()
        if settings.smtp_username:
            client.login(settings.smtp_username, settings.smtp_password or "")
        client.send_message(message)
