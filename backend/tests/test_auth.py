from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.models import AuditLog
from tests.conftest import PASSWORD


def _login(client, api, email="user@test.io", password=PASSWORD):
    return client.post(f"{api}/auth/login", data={"username": email, "password": password})


def test_login_returns_token_and_httponly_refresh_cookie(client, api):
    response = _login(client, api)
    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_wrong_password_and_unknown_email_look_identical(client, api):
    wrong = _login(client, api, password="definitely-not-right")
    unknown = _login(client, api, email="ghost@test.io")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_failed_login_is_audited(client, api, db):
    _login(client, api, password="wrong-password-here")
    assert db.query(AuditLog).filter_by(action="auth.login_failed").count() == 1


def test_me_requires_a_token(client, api):
    assert client.get(f"{api}/auth/me").status_code == 401


def test_me_never_returns_the_password_hash(client, api, actors):
    body = client.get(f"{api}/auth/me", headers=actors.user).json()
    assert body["email"] == "user@test.io"
    assert "password_hash" not in body


def _claims(**overrides):
    settings = get_settings()
    now = datetime.now(UTC)
    return {
        "sub": "1",
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": now + timedelta(minutes=5),
        **overrides,
    }


def test_rejects_expired_token(client, api):
    token = jwt.encode(_claims(exp=datetime.now(UTC) - timedelta(minutes=1)), get_settings().jwt_secret, "HS256")
    assert client.get(f"{api}/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_rejects_token_signed_with_another_key(client, api):
    token = jwt.encode(_claims(), "x" * 40, "HS256")
    assert client.get(f"{api}/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_rejects_wrong_audience(client, api):
    token = jwt.encode(_claims(aud="another-service"), get_settings().jwt_secret, "HS256")
    assert client.get(f"{api}/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_rejects_unsigned_token(client, api):
    token = jwt.encode(_claims(), None, algorithm="none")
    assert client.get(f"{api}/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_refresh_rotates_the_token(client, api):
    _login(client, api)
    first = client.cookies["refresh_token"]
    response = client.post(f"{api}/auth/refresh")
    assert response.status_code == 200
    assert client.cookies["refresh_token"] != first


def test_replaying_a_rotated_token_ends_the_whole_session(client, api):
    _login(client, api)
    stolen = client.cookies["refresh_token"]
    client.post(f"{api}/auth/refresh")
    current = client.cookies["refresh_token"]

    client.cookies.set("refresh_token", stolen, path=f"{api}/auth")
    assert client.post(f"{api}/auth/refresh").status_code == 401

    client.cookies.clear()
    client.cookies.set("refresh_token", current, path=f"{api}/auth")
    assert client.post(f"{api}/auth/refresh").status_code == 401


def test_logout_revokes_the_refresh_token(client, api):
    _login(client, api)
    token = client.cookies["refresh_token"]
    assert client.post(f"{api}/auth/logout").status_code == 204
    client.cookies.set("refresh_token", token, path=f"{api}/auth")
    assert client.post(f"{api}/auth/refresh").status_code == 401


def test_deactivated_user_loses_access_immediately(client, api, actors):
    headers = actors.user
    me = client.get(f"{api}/auth/me", headers=headers).json()
    client.patch(f"{api}/users/{me['id']}", json={"is_active": False}, headers=actors.admin)
    assert client.get(f"{api}/auth/me", headers=headers).status_code == 401


def test_role_change_applies_to_existing_tokens(client, api, actors):
    headers = actors.manager
    assert client.get(f"{api}/analytics/dashboard", headers=headers).status_code == 200
    me = client.get(f"{api}/auth/me", headers=headers).json()
    client.patch(f"{api}/users/{me['id']}", json={"role": "requester"}, headers=actors.admin)
    assert client.get(f"{api}/analytics/dashboard", headers=headers).status_code == 403


def test_password_change_needs_the_current_password_and_revokes_sessions(client, api, actors):
    headers = actors.user
    bad = client.post(
        f"{api}/auth/me/password",
        json={"current_password": "wrong", "new_password": "a-brand-new-password"},
        headers=headers,
    )
    assert bad.status_code == 401
    good = client.post(
        f"{api}/auth/me/password",
        json={"current_password": PASSWORD, "new_password": "a-brand-new-password"},
        headers=headers,
    )
    assert good.status_code == 204
    assert _login(client, api).status_code == 401
    assert _login(client, api, password="a-brand-new-password").status_code == 200


def test_short_passwords_are_rejected(client, api, actors):
    response = client.post(
        f"{api}/users",
        json={"email": "new@test.io", "full_name": "New Person", "password": "short"},
        headers=actors.admin,
    )
    assert response.status_code == 422


def test_login_is_rate_limited(client, api):
    from app.api.rate_limit import limiter

    limiter.enabled = True
    limiter.reset()
    try:
        codes = [_login(client, api, password="wrong-password").status_code for _ in range(12)]
    finally:
        limiter.enabled = False
    assert codes[0] == 401
    assert 429 in codes


def test_password_hash_is_salted_and_verifies():
    first, second = hash_password("secret-value-1"), hash_password("secret-value-1")
    assert first != second
    assert first.startswith("$argon2id$")
    assert verify_password("secret-value-1", first)
    assert not verify_password("secret-value-2", first)
    assert not verify_password("anything", None)


def test_refresh_is_not_held_to_the_login_limit(client, api):
    """Reloading a page refreshes the session, so it must not lock a normal user out."""
    from app.api.rate_limit import limiter

    _login(client, api)
    limiter.enabled = True
    limiter.reset()
    try:
        codes = [client.post(f"{api}/auth/refresh").status_code for _ in range(15)]
    finally:
        limiter.enabled = False
    assert set(codes) == {200}
