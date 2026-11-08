from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import DB, CurrentUser
from app.api.rate_limit import limiter
from app.core.config import get_settings
from app.schemas.api import PasswordChange, Registration, TokenOut, UserOut
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

COOKIE_NAME = "refresh_token"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        max_age=settings.refresh_token_days * 86400,
        path=f"{settings.api_prefix}/auth",
    )


@router.post("/login", response_model=TokenOut)
@limiter.limit(settings.rate_limit_login)
def login(
    request: Request,
    response: Response,
    db: DB,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> TokenOut:
    user = auth_service.authenticate(db, form.username, form.password)
    access, expires_in, refresh = auth_service.issue_tokens(db, user)
    _set_refresh_cookie(response, refresh)
    return TokenOut(access_token=access, expires_in=expires_in)


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_register)
def register(request: Request, response: Response, payload: Registration, db: DB) -> TokenOut:
    user = auth_service.register(db, payload.email, payload.full_name, payload.password, payload.admin_code)
    access, expires_in, refresh = auth_service.issue_tokens(db, user)
    _set_refresh_cookie(response, refresh)
    return TokenOut(access_token=access, expires_in=expires_in)


@router.post("/demo", response_model=TokenOut)
@limiter.limit(settings.rate_limit_login)
def demo(request: Request, response: Response, db: DB) -> TokenOut:
    if not settings.demo_login_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The demo is switched off on this site")
    user = auth_service.demo_account(db)
    access, expires_in, refresh = auth_service.issue_tokens(db, user)
    _set_refresh_cookie(response, refresh)
    return TokenOut(access_token=access, expires_in=expires_in)


@router.post("/refresh", response_model=TokenOut)
@limiter.limit(settings.rate_limit_refresh)
def refresh(
    request: Request,
    response: Response,
    db: DB,
    refresh_token: Annotated[str | None, Cookie()] = None,
) -> TokenOut:
    if not refresh_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing refresh token")
    _, (access, expires_in, new_refresh) = auth_service.rotate_refresh_token(db, refresh_token)
    _set_refresh_cookie(response, new_refresh)
    return TokenOut(access_token=access, expires_in=expires_in)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, db: DB, refresh_token: Annotated[str | None, Cookie()] = None) -> None:
    auth_service.logout(db, refresh_token)
    response.delete_cookie(COOKIE_NAME, path=f"{settings.api_prefix}/auth")


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user).model_copy(update={"is_demo": auth_service.is_demo(user)})


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(payload: PasswordChange, user: CurrentUser, db: DB) -> None:
    auth_service.change_password(db, user, payload.current_password, payload.new_password)
