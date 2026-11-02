"""Notifications, remediation approvals and analytics."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import DB, CurrentUser, ManagerUser, StaffUser
from app.core.enums import RemediationStatus
from app.schemas.api import (
    NotificationOut,
    NotificationSummary,
    RemediationDecision,
    RemediationOut,
    RunbookOut,
)
from app.services import analytics, notifications, remediation

router = APIRouter(tags=["operations"])


@router.get("/notifications", response_model=list[NotificationOut])
def list_notifications(
    user: CurrentUser,
    db: DB,
    unread_only: bool = False,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> list:
    return notifications.list_for_user(db, user, unread_only, offset, limit)


@router.get("/notifications/summary", response_model=NotificationSummary)
def notification_summary(user: CurrentUser, db: DB) -> dict:
    return notifications.summary(db, user)


@router.post("/notifications/read-all", status_code=status.HTTP_204_NO_CONTENT)
def read_all(user: CurrentUser, db: DB) -> None:
    notifications.mark_read(db, user)


@router.post("/notifications/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def read_one(notification_id: int, user: CurrentUser, db: DB) -> None:
    notifications.mark_read(db, user, notification_id)


@router.get("/remediation/runbooks", response_model=list[RunbookOut])
def runbooks(_: StaffUser, db: DB) -> list:
    return remediation.list_runbooks(db)


@router.get("/remediation/requests", response_model=list[RemediationOut])
def remediation_requests(
    user: StaffUser, db: DB, status_filter: Annotated[RemediationStatus | None, Query(alias="status")] = None
) -> list:
    return remediation.list_requests(db, user, status_filter, None)


@router.post("/remediation/requests/{request_id}/decision", response_model=RemediationOut)
def decide(request_id: int, payload: RemediationDecision, user: ManagerUser, db: DB) -> object:
    return remediation.decide(db, user, request_id, payload.approve, payload.note)


@router.get("/analytics/dashboard")
def dashboard(_: ManagerUser, db: DB, days: Annotated[int, Query(ge=7, le=365)] = 30) -> dict:
    return analytics.dashboard(db, days)
