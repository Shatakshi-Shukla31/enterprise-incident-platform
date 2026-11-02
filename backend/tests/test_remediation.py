import pytest
from sqlalchemy import select

from app.core.enums import RemediationStatus
from app.models import RemediationRequest, Runbook
from app.services import remediation


@pytest.fixture
def runbook_id(db):
    return db.scalar(select(Runbook.id).where(Runbook.key == "restart-app-service"))


@pytest.fixture
def request_factory(client, api, actors, make_incident, runbook_id):
    def _make(headers=None, target="orders-api"):
        incident = make_incident()
        return client.post(
            f"{api}/incidents/{incident['id']}/remediations",
            json={"runbook_id": runbook_id, "target": target, "justification": "Service is hanging, restart required"},
            headers=headers or actors.admin,
        )

    return _make


def _decide(client, api, request_id, headers, approve=True):
    return client.post(
        f"{api}/remediation/requests/{request_id}/decision",
        json={"approve": approve, "note": "reviewed"},
        headers=headers,
    )


def test_a_request_waits_for_approval_and_runs_nothing(request_factory, db):
    body = request_factory().json()
    assert body["status"] == "pending_approval"
    assert db.get(RemediationRequest, body["id"]).result == {}


def test_managers_are_asked_to_approve(request_factory, client, api, actors):
    request_factory()
    notifications = client.get(f"{api}/notifications", headers=actors.manager).json()
    assert any(item["type"] == "approval_required" for item in notifications)


def test_approval_runs_the_task_and_records_the_result(request_factory, client, api, actors):
    created = request_factory(actors.manager).json()
    assert _decide(client, api, created["id"], actors.admin).status_code == 200
    rows = client.get(f"{api}/remediation/requests", headers=actors.admin).json()
    row = next(item for item in rows if item["id"] == created["id"])
    assert row["status"] == "succeeded"
    assert row["result"]["simulated"] is True
    history = client.get(f"{api}/incidents/{row['incident_id']}/audit", headers=actors.admin).json()
    actions = [entry["action"] for entry in history]
    assert "remediation.approved" in actions and "remediation.finished" in actions


def test_nobody_approves_their_own_request(request_factory, client, api, actors):
    created = request_factory(actors.admin).json()
    assert _decide(client, api, created["id"], actors.admin).status_code == 403


def test_agents_cannot_decide(request_factory, client, api, actors):
    created = request_factory(actors.admin).json()
    assert _decide(client, api, created["id"], actors.agent).status_code == 403


def test_rejected_requests_never_execute(request_factory, client, api, actors, db):
    created = request_factory(actors.admin).json()
    assert _decide(client, api, created["id"], actors.manager, approve=False).json()["status"] == "rejected"
    remediation.execute(db, created["id"])
    db.expire_all()
    assert db.get(RemediationRequest, created["id"]).status == RemediationStatus.REJECTED


def test_a_request_can_only_be_decided_once(request_factory, client, api, actors):
    created = request_factory(actors.admin).json()
    _decide(client, api, created["id"], actors.manager)
    assert _decide(client, api, created["id"], actors.manager2).status_code == 409


def test_running_twice_does_not_repeat_the_action(request_factory, client, api, actors, db, monkeypatch):
    created = request_factory(actors.manager).json()
    _decide(client, api, created["id"], actors.admin)
    calls = []
    monkeypatch.setitem(remediation.ACTION_HANDLERS, "restart_service", lambda t: calls.append(t) or {})
    remediation.execute(db, created["id"])
    assert calls == []


def test_a_failing_handler_is_recorded_as_failed(request_factory, client, api, actors, db, monkeypatch):
    def fail(_):
        raise RuntimeError("host unreachable")

    monkeypatch.setitem(remediation.ACTION_HANDLERS, "restart_service", fail)
    created = request_factory(actors.manager).json()
    _decide(client, api, created["id"], actors.admin)
    db.expire_all()
    row = db.get(RemediationRequest, created["id"])
    assert row.status == RemediationStatus.FAILED
    assert "host unreachable" in row.result["error"]


@pytest.mark.parametrize("target", ["host; rm -rf /", "$(whoami)", "a b", "../etc/passwd|cat", "`id`"])
def test_shell_style_targets_are_rejected(request_factory, target):
    assert request_factory(target=target).status_code == 400


def test_requesters_cannot_request_remediation(request_factory, actors):
    assert request_factory(actors.user).status_code == 403


def test_every_seeded_runbook_has_a_handler():
    assert {row[3] for row in remediation.DEFAULT_RUNBOOKS} <= set(remediation.ACTION_HANDLERS)
