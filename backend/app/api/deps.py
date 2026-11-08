import re
from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import Role
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{get_settings().api_prefix}/auth/login")

DB = Annotated[Session, Depends(get_db)]

_UNAUTHORIZED = HTTPException(
    status.HTTP_401_UNAUTHORIZED,
    "Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


# The demo visitor may look at everything and ask the assistant, and change nothing else.
# Checked here, where every signed-in request passes, so a new route is read-only by default.
# Matched on the request path: FastAPI records mounted routes without their prefix.
_DEMO_WRITES = re.compile(
    rf"^{re.escape(get_settings().api_prefix)}/("
    r"ai/chat|ai/recommendations/\d+/feedback|knowledge/search"
    r"|incidents/\d+/ai/suggest|notifications/read-all|notifications/\d+/read"
    r")$"
)
_READS = frozenset({"GET", "HEAD", "OPTIONS"})


def get_current_user(request: Request, db: DB, token: Annotated[str, Depends(oauth2_scheme)]) -> User:
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError) as exc:
        raise _UNAUTHORIZED from exc
    # The role comes from the database, so a demotion takes effect immediately.
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    if (
        request.method not in _READS
        and user.email == get_settings().demo_account_email
        and not _DEMO_WRITES.match(request.url.path)
    ):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "The demo account is read-only. Sign out and create your own account to make changes.",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role) -> Callable[[User], User]:
    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
        return user

    return checker


StaffUser = Annotated[User, Depends(require_roles(Role.AGENT, Role.MANAGER, Role.ADMIN))]
ManagerUser = Annotated[User, Depends(require_roles(Role.MANAGER, Role.ADMIN))]
AdminUser = Annotated[User, Depends(require_roles(Role.ADMIN))]


class Pagination:
    def __init__(
        self,
        page: Annotated[int, Query(ge=1, le=100000)] = 1,
        page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    ) -> None:
        self.page = page
        self.page_size = page_size
        self.offset = (page - 1) * page_size


Paging = Annotated[Pagination, Depends()]
