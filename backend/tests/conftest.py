"""Tests run against a real PostgreSQL with pgvector, migrated by Alembic, so that SQL,
constraints and triggers are exercised rather than mocked. Set TEST_DATABASE_URL."""

import os
import tempfile
from pathlib import Path

test_database_url = os.environ.get("TEST_DATABASE_URL")
if not test_database_url:
    raise RuntimeError("Set TEST_DATABASE_URL to a disposable PostgreSQL database")

_artifacts = tempfile.mkdtemp(prefix="eip-test-artifacts-")
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DATABASE_URL": test_database_url,
        "JWT_SECRET": "test-only-secret-with-at-least-thirty-two-characters",
        "EMBEDDING_PROVIDER": "hash",
        "CELERY_TASK_ALWAYS_EAGER": "true",
        "RATE_LIMIT_ENABLED": "false",
        "ARTIFACTS_DIR": _artifacts,
        "LLM_PROVIDER": "extractive",
        "METRICS_TOKEN": "metrics-test-token",
        "SMTP_HOST": "",
        "DB_POOL_SIZE": "3",
    }
)

import pytest  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from alembic import command  # noqa: E402
from app.core.config import BACKEND_DIR, get_settings  # noqa: E402
from app.core.enums import Role  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_engine, new_session  # noqa: E402
from app.main import app  # noqa: E402
from app.ml import inference  # noqa: E402
from app.models import Runbook, SLAPolicy, Team, User  # noqa: E402
from app.services.remediation import DEFAULT_RUNBOOKS  # noqa: E402
from app.services.sla import DEFAULT_TARGETS  # noqa: E402

PASSWORD = "correct-horse-battery"
PASSWORD_HASH = hash_password(PASSWORD)


@pytest.fixture(scope="session", autouse=True)
def migrated_database():
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    with get_engine().begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    command.upgrade(config, "head")
    yield


@pytest.fixture(autouse=True)
def clean_database(migrated_database):
    tables = ", ".join(table.name for table in Base.metadata.sorted_tables)
    with get_engine().begin() as connection:
        connection.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    with new_session() as db:
        db.add_all(
            SLAPolicy(priority=p, response_minutes=r, resolution_minutes=m) for p, (r, m) in DEFAULT_TARGETS.items()
        )
        db.add_all(Runbook(key=k, name=n, description=d, action=a, category=c) for k, n, d, a, c in DEFAULT_RUNBOOKS)
        network = Team(name="Network Operations")
        security = Team(name="Security Operations")
        db.add_all([network, security])
        db.flush()
        people = [
            ("admin@test.io", Role.ADMIN, None),
            ("manager@test.io", Role.MANAGER, network.id),
            ("manager2@test.io", Role.MANAGER, security.id),
            ("agent@test.io", Role.AGENT, network.id),
            ("secagent@test.io", Role.AGENT, security.id),
            ("user@test.io", Role.REQUESTER, None),
            ("other@test.io", Role.REQUESTER, None),
        ]
        db.add_all(
            User(email=e, full_name=e.split("@")[0], password_hash=PASSWORD_HASH, role=r, team_id=t)
            for e, r, t in people
        )
        db.commit()
    yield


@pytest.fixture
def db():
    """Autocommit, so a read here never holds a transaction open across an API call. A
    multiplexed test server such as PGlite would otherwise block that call forever."""
    engine = get_engine().execution_options(isolation_level="AUTOCOMMIT")
    with Session(bind=engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def login(client):
    def _login(email: str) -> dict[str, str]:
        response = client.post(
            f"{get_settings().api_prefix}/auth/login",
            data={"username": email, "password": PASSWORD},
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _login


class Actors:
    def __init__(self, login):
        self._login = login
        self._cache: dict[str, dict] = {}

    def __getattr__(self, name: str) -> dict:
        emails = {
            "admin": "admin@test.io",
            "manager": "manager@test.io",
            "manager2": "manager2@test.io",
            "agent": "agent@test.io",
            "secagent": "secagent@test.io",
            "user": "user@test.io",
            "other": "other@test.io",
        }
        if name not in emails:
            raise AttributeError(name)
        if name not in self._cache:
            self._cache[name] = self._login(emails[name])
        return self._cache[name]


@pytest.fixture
def actors(login):
    return Actors(login)


@pytest.fixture
def api():
    return get_settings().api_prefix


@pytest.fixture
def make_incident(client, actors, api):
    def _make(headers=None, **overrides) -> dict:
        payload = {
            "title": "VPN keeps dropping every few minutes",
            "description": "The tunnel disconnects constantly when working from home.",
            "impact": "medium",
            "urgency": "medium",
            **overrides,
        }
        response = client.post(f"{api}/incidents", json=payload, headers=headers or actors.user)
        assert response.status_code == 201, response.text
        return response.json()

    return _make


@pytest.fixture(scope="session")
def trained_models():
    """Train real, small models through the real pipeline."""
    from app.ml.synthetic import generate
    from app.ml.train import train_category, train_routing, train_sla

    root = Path(_artifacts)
    history = generate(days=240, daily_mean=20, seed=7)
    results = {
        "category": train_category(history, "test", 7, root),
        "routing": train_routing(history, "test", 7, root),
        "sla_risk": train_sla(history, "test", 7, root),
    }
    inference.reload_models()
    return results


@pytest.fixture
def similarity_floor(monkeypatch):
    """The token-hash test embedder scores lower than the real model."""
    from app.rag.llm import ExtractiveProvider

    monkeypatch.setattr(get_settings(), "rag_min_similarity", 0.15)
    monkeypatch.setattr(ExtractiveProvider, "min_sentence_similarity", 0.05)
