from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.site import CONTENT_SECURITY_POLICY, mount_site
from app.workers import scheduler


def _settings(**overrides) -> Settings:
    values = {"database_url": "postgresql://u:p@host/db", "jwt_secret": "x" * 32, **overrides}
    return Settings(_env_file=None, **values)


def test_a_hosted_database_address_uses_the_installed_driver():
    assert _settings().database_url == "postgresql+psycopg://u:p@host/db"
    assert _settings(database_url="postgresql+psycopg://a@b/c").database_url == "postgresql+psycopg://a@b/c"


def test_single_process_runs_background_work_inline():
    assert _settings(celery_task_always_eager=False).celery_task_always_eager is False
    assert _settings(celery_task_always_eager=False, single_process=True).celery_task_always_eager is True


@pytest.fixture
def site(tmp_path):
    root = tmp_path / "site"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("the app", encoding="utf-8")
    (root / "assets" / "main.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("private", encoding="utf-8")

    app = FastAPI()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    mount_site(app, root)
    return TestClient(app)


def test_site_serves_files_and_app_routes(site):
    assert site.get("/assets/main.js").text == "console.log(1)"
    assert site.get("/").text == "the app"
    assert site.get("/incidents/42").text == "the app"
    assert site.get("/").headers["content-security-policy"] == CONTENT_SECURITY_POLICY


def test_the_page_is_rechecked_and_built_files_are_kept(site):
    assert site.get("/").headers["cache-control"] == "no-cache"
    assert site.get("/incidents/42").headers["cache-control"] == "no-cache"
    assert "immutable" in site.get("/assets/main.js").headers["cache-control"]


def test_a_file_removed_by_a_deploy_is_missing_rather_than_the_page(site):
    response = site.get("/assets/old-build.js")
    assert response.status_code == 404
    assert "the app" not in response.text


def test_site_does_not_hide_the_routes_before_it(site):
    assert site.get("/health").json() == {"status": "ok"}


def test_an_unknown_api_path_is_not_answered_with_the_website(site):
    assert site.get("/api/v1/nothing-here").status_code == 404


def test_site_never_serves_a_file_outside_its_folder(site):
    assert "private" not in site.get("/%2e%2e/secret.txt").text
    assert "private" not in site.get("/..%2fsecret.txt").text


def _fake_jobs(monkeypatch, log, fail=()):
    def task(name):
        def apply(throw):
            log.append(name)
            if name in fail:
                raise RuntimeError("job failed")

        return SimpleNamespace(apply=apply)

    fake = SimpleNamespace(
        conf=SimpleNamespace(beat_schedule={"a": {"task": "a", "schedule": 60.0}, "b": {"task": "b", "schedule": 600.0}}),
        tasks={"a": task("a"), "b": task("b")},
    )
    monkeypatch.setattr(scheduler, "celery_app", fake)


def test_only_due_jobs_run_and_each_is_rescheduled(monkeypatch):
    log = []
    _fake_jobs(monkeypatch, log)
    next_run = {"a": 100.0, "b": 500.0}
    scheduler.run_due(next_run, 100.0)
    assert log == ["a"]
    assert next_run == {"a": 160.0, "b": 500.0}


def test_a_failing_job_does_not_stop_the_others(monkeypatch):
    log = []
    _fake_jobs(monkeypatch, log, fail={"a"})
    scheduler.run_due({"a": 0.0, "b": 0.0}, 1.0)
    assert log == ["a", "b"]
