from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import DB, AdminUser, CurrentUser, ManagerUser, Paging, StaffUser
from app.core.enums import Role
from app.core.security import hash_password
from app.models import Team, User
from app.schemas.api import Page, TeamCreate, TeamOut, UserCreate, UserOut, UserUpdate
from app.services import audit

router = APIRouter(tags=["users"])


def _require_team(db: Session, team_id: int | None) -> None:
    if team_id is not None and db.get(Team, team_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown team")


@router.get("/users", response_model=Page[UserOut])
def list_users(_: StaffUser, db: DB, paging: Paging, team_id: int | None = None, staff_only: bool = False) -> dict:
    stmt = select(User).where(User.is_active.is_(True))
    if team_id is not None:
        stmt = stmt.where(User.team_id == team_id)
    if staff_only:
        stmt = stmt.where(User.role != Role.REQUESTER)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(User.full_name).offset(paging.offset).limit(paging.page_size)).all()
    return {"items": items, "total": total, "page": paging.page, "page_size": paging.page_size}


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, admin: AdminUser, db: DB) -> User:
    _require_team(db, payload.team_id)
    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        team_id=payload.team_id,
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered") from exc
    audit.record(db, "user.created", admin, target_user=user.id, role=user.role)
    db.commit()
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(user_id: int, payload: UserUpdate, admin: AdminUser, db: DB) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == admin.id and (payload.role not in (None, Role.ADMIN) or payload.is_active is False):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot demote or deactivate yourself")
    _require_team(db, payload.team_id)
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(user, field, value)
    audit.record(db, "user.updated", admin, target_user=user.id, **changes)
    db.commit()
    return user


@router.get("/teams", response_model=list[TeamOut])
def list_teams(_: CurrentUser, db: DB) -> list[Team]:
    return list(db.scalars(select(Team).where(Team.is_active.is_(True)).order_by(Team.name)))


@router.post("/teams", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
def create_team(payload: TeamCreate, manager: ManagerUser, db: DB) -> Team:
    team = Team(name=payload.name, description=payload.description)
    db.add(team)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Team already exists") from exc
    audit.record(db, "team.created", manager, team=team.name)
    db.commit()
    return team
