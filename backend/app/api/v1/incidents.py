from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from app.api.deps import DB, CurrentUser, Paging, StaffUser
from app.api.rate_limit import limiter
from app.core.config import get_settings
from app.core.enums import Category, Priority, RemediationStatus, Status
from app.models import Incident, User
from app.rag import service as rag_service
from app.schemas.api import (
    AnswerOut,
    Assignment,
    AuditOut,
    CategoryCorrection,
    CommentCreate,
    CommentOut,
    Escalation,
    IncidentCreate,
    IncidentOut,
    IncidentUpdate,
    Page,
    PredictionOut,
    RelatedIncident,
    RemediationCreate,
    RemediationOut,
    StatusChange,
)
from app.services import incidents as service
from app.services import remediation
from app.services.access import is_staff

router = APIRouter(prefix="/incidents", tags=["incidents"])
settings = get_settings()


def _present(incident: Incident, user: User) -> IncidentOut:
    out = IncidentOut.model_validate(incident)
    if not is_staff(user):
        out.category_confidence = None
        out.sla_risk_score = None
    return out


@router.post("", response_model=IncidentOut, status_code=status.HTTP_201_CREATED)
def create_incident(payload: IncidentCreate, user: CurrentUser, db: DB) -> IncidentOut:
    incident = service.create_incident(db, user, **payload.model_dump())
    return _present(incident, user)


@router.get("", response_model=Page[IncidentOut])
def list_incidents(
    user: CurrentUser,
    db: DB,
    paging: Paging,
    status_filter: Annotated[list[Status] | None, Query(alias="status")] = None,
    priority: Annotated[list[Priority] | None, Query()] = None,
    category: Category | None = None,
    team_id: int | None = None,
    assignee_id: int | None = None,
    breached: bool | None = None,
    open_only: bool = False,
    q: Annotated[str | None, Query(max_length=200)] = None,
    sort: Annotated[
        str, Query(pattern="^(created_at|updated_at|priority|resolution_due_at|sla_risk_score)$")
    ] = "created_at",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
) -> dict:
    filters = service.IncidentFilters(
        status=status_filter or (),
        priority=priority or (),
        category=category,
        team_id=team_id,
        assignee_id=assignee_id,
        breached=breached,
        open_only=open_only,
        q=q,
        sort=sort,
        descending=order == "desc",
    )
    rows, total = service.list_incidents(db, user, filters, paging.offset, paging.page_size)
    return {
        "items": [_present(row, user) for row in rows],
        "total": total,
        "page": paging.page,
        "page_size": paging.page_size,
    }


@router.get("/{incident_id}", response_model=IncidentOut)
def get_incident(incident_id: int, user: CurrentUser, db: DB) -> IncidentOut:
    return _present(service.get_incident(db, user, incident_id), user)


@router.patch("/{incident_id}", response_model=IncidentOut)
def update_incident(incident_id: int, payload: IncidentUpdate, user: StaffUser, db: DB) -> IncidentOut:
    incident = service.update_details(db, user, incident_id, **payload.model_dump())
    return _present(incident, user)


@router.post("/{incident_id}/status", response_model=IncidentOut)
def change_status(incident_id: int, payload: StatusChange, user: StaffUser, db: DB) -> IncidentOut:
    incident = service.change_status(db, user, incident_id, payload.status, payload.resolution_notes)
    return _present(incident, user)


@router.post("/{incident_id}/assign", response_model=IncidentOut)
def assign(incident_id: int, payload: Assignment, user: StaffUser, db: DB) -> IncidentOut:
    incident = service.assign(db, user, incident_id, payload.team_id, payload.assignee_id)
    return _present(incident, user)


@router.post("/{incident_id}/escalate", response_model=IncidentOut)
def escalate(incident_id: int, payload: Escalation, user: StaffUser, db: DB) -> IncidentOut:
    return _present(service.escalate(db, user, incident_id, payload.reason), user)


@router.post("/{incident_id}/category", response_model=IncidentOut)
def correct_category(incident_id: int, payload: CategoryCorrection, user: StaffUser, db: DB) -> IncidentOut:
    return _present(service.correct_category(db, user, incident_id, payload.category), user)


@router.get("/{incident_id}/comments", response_model=list[CommentOut])
def list_comments(incident_id: int, user: CurrentUser, db: DB) -> list:
    return service.list_comments(db, user, incident_id)


@router.post("/{incident_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
def add_comment(incident_id: int, payload: CommentCreate, user: CurrentUser, db: DB) -> object:
    return service.add_comment(db, user, incident_id, payload.body, payload.is_internal)


@router.get("/{incident_id}/audit", response_model=list[AuditOut])
def audit_history(incident_id: int, user: StaffUser, db: DB) -> list:
    return service.audit_history(db, user, incident_id)


@router.get("/{incident_id}/predictions", response_model=list[PredictionOut])
def predictions(incident_id: int, user: StaffUser, db: DB) -> list:
    return service.list_predictions(db, user, incident_id)


@router.post("/{incident_id}/ai/suggest", response_model=AnswerOut)
@limiter.limit(settings.rate_limit_ai)
def suggest(request: Request, incident_id: int, user: StaffUser, db: DB) -> dict:
    return rag_service.suggest_for_incident(db, user, incident_id)


@router.get("/{incident_id}/ai/related", response_model=list[RelatedIncident])
@limiter.limit(settings.rate_limit_ai)
def related(request: Request, incident_id: int, user: StaffUser, db: DB) -> list:
    return rag_service.related_for_incident(db, user, incident_id)


@router.post("/{incident_id}/remediations", response_model=RemediationOut, status_code=status.HTTP_201_CREATED)
def request_remediation(incident_id: int, payload: RemediationCreate, user: StaffUser, db: DB) -> object:
    request = remediation.request_remediation(
        db, user, incident_id, payload.runbook_id, payload.target, payload.justification
    )
    return request


@router.get("/{incident_id}/remediations", response_model=list[RemediationOut])
def incident_remediations(
    incident_id: int, user: StaffUser, db: DB, status_filter: RemediationStatus | None = None
) -> list:
    service.get_incident(db, user, incident_id)
    return remediation.list_requests(db, user, status_filter, incident_id)
