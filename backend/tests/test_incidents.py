from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.core.enums import Level, NotificationType, Priority, Status, compute_priority
from app.models import AuditLog, Incident, Notification, Prediction, Team


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value)


@pytest.mark.parametrize(
    "impact,urgency,expected",
    [
        ("high", "high", "P1"),
        ("high", "medium", "P2"),
        ("medium", "high", "P2"),
        ("high", "low", "P3"),
        ("medium", "medium", "P3"),
        ("low", "low", "P4"),
    ],
)
def test_priority_matrix(impact, urgency, expected):
    assert compute_priority(Level(impact), Level(urgency)) == Priority(expected)


def test_create_sets_priority_and_sla_targets(make_incident):
    body = make_incident(impact="high", urgency="high")
    assert body["number"] == f"INC{body['id']:07d}"
    assert body["priority"] == "P1"
    assert body["status"] == "new"
    created = _time(body["created_at"])
    assert _time(body["response_due_at"]) - created == timedelta(minutes=15)
    assert _time(body["resolution_due_at"]) - created == timedelta(hours=4)


@pytest.mark.parametrize(
    "payload",
    [
        {"title": "x", "description": "A long enough description here"},
        {"title": "A valid title", "description": "short"},
        {"title": "A valid title", "description": "A long enough description", "impact": "huge"},
        {"title": "A valid title", "description": "A long enough description", "priority": "P1", "impact": "bad"},
    ],
)
def test_invalid_payloads_are_rejected(client, api, actors, payload):
    assert client.post(f"{api}/incidents", json=payload, headers=actors.user).status_code == 422


def test_client_cannot_set_priority_directly(client, api, actors):
    body = client.post(
        f"{api}/incidents",
        json={
            "title": "A valid title",
            "description": "A long enough description",
            "impact": "low",
            "urgency": "low",
            "priority": "P1",
        },
        headers=actors.user,
    ).json()
    assert body["priority"] == "P4"


def _status(client, api, actors, incident_id, status, notes=None):
    return client.post(
        f"{api}/incidents/{incident_id}/status",
        json={"status": status, "resolution_notes": notes},
        headers=actors.admin,
    )


def test_lifecycle_and_timestamps(client, api, actors, make_incident):
    incident = make_incident()
    started = _status(client, api, actors, incident["id"], "in_progress").json()
    assert started["first_response_at"] is not None
    resolved = _status(client, api, actors, incident["id"], "resolved", "Replaced the client").json()
    assert resolved["resolved_at"] is not None
    closed = _status(client, api, actors, incident["id"], "closed").json()
    assert closed["closed_at"] is not None


def test_illegal_transition_is_a_conflict(client, api, actors, make_incident):
    incident = make_incident()
    _status(client, api, actors, incident["id"], "in_progress")
    _status(client, api, actors, incident["id"], "resolved", "done")
    _status(client, api, actors, incident["id"], "closed")
    assert _status(client, api, actors, incident["id"], "in_progress").status_code == 409


def test_resolving_requires_notes(client, api, actors, make_incident):
    incident = make_incident()
    assert _status(client, api, actors, incident["id"], "resolved", "   ").status_code == 400


def test_reopening_clears_the_resolution(client, api, actors, make_incident):
    incident = make_incident()
    _status(client, api, actors, incident["id"], "resolved", "Fixed it")
    reopened = _status(client, api, actors, incident["id"], "in_progress").json()
    assert reopened["resolved_at"] is None


def test_hold_stops_the_sla_clock(client, api, actors, make_incident, db):
    incident = make_incident()
    _status(client, api, actors, incident["id"], "assigned")
    _status(client, api, actors, incident["id"], "on_hold")
    row = db.get(Incident, incident["id"])
    original_due = row.resolution_due_at
    row.on_hold_since -= timedelta(hours=3)
    db.commit()
    _status(client, api, actors, incident["id"], "in_progress")
    db.expire_all()
    assert db.get(Incident, incident["id"]).resolution_due_at - original_due >= timedelta(hours=3)


def test_late_resolution_is_recorded_as_a_breach(client, api, actors, make_incident, db):
    incident = make_incident()
    row = db.get(Incident, incident["id"])
    row.resolution_due_at -= timedelta(days=5)
    db.commit()
    body = _status(client, api, actors, incident["id"], "resolved", "Fixed late").json()
    assert body["sla_breached"] is True


def test_changing_impact_recalculates_priority_and_due_date(client, api, actors, make_incident):
    incident = make_incident(impact="low", urgency="low")
    body = client.patch(
        f"{api}/incidents/{incident['id']}",
        json={"impact": "high", "urgency": "high"},
        headers=actors.admin,
    ).json()
    assert body["priority"] == "P1"
    assert _time(body["resolution_due_at"]) - _time(body["created_at"]) == timedelta(hours=4)


def test_every_change_appears_in_audit_history(client, api, actors, make_incident):
    incident = make_incident()
    _status(client, api, actors, incident["id"], "in_progress")
    client.post(f"{api}/incidents/{incident['id']}/escalate", json={"reason": "Customer impact"}, headers=actors.admin)
    history = client.get(f"{api}/incidents/{incident['id']}/audit", headers=actors.admin).json()
    actions = [entry["action"] for entry in history]
    assert actions[0] == "incident.created"
    assert "incident.status_changed" in actions
    assert "incident.escalated" in actions
    assert history[-1]["actor"]["full_name"] == "admin"


@pytest.mark.parametrize("statement", ["UPDATE audit_logs SET action = 'x'", "DELETE FROM audit_logs"])
def test_audit_log_is_append_only_in_the_database(db, make_incident, statement):
    make_incident()
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text(statement))
    db.rollback()


def test_pagination(client, api, actors, make_incident):
    for _ in range(5):
        make_incident()
    page = client.get(f"{api}/incidents?page=2&page_size=2", headers=actors.admin).json()
    assert page["total"] == 5
    assert page["page"] == 2
    assert len(page["items"]) == 2


def test_page_size_is_capped(client, api, actors):
    assert client.get(f"{api}/incidents?page_size=1000", headers=actors.admin).status_code == 422


def test_filters_combine(client, api, actors, make_incident):
    target = make_incident(impact="high", urgency="high")
    make_incident(impact="low", urgency="low")
    rows = client.get(f"{api}/incidents?priority=P1&status=new", headers=actors.admin).json()
    assert [row["id"] for row in rows["items"]] == [target["id"]]


def test_search_finds_text_and_ticket_numbers(client, api, actors, make_incident):
    target = make_incident(title="Printer on fire in the lobby")
    make_incident()
    by_text = client.get(f"{api}/incidents", params={"q": "printer"}, headers=actors.admin).json()
    by_number = client.get(f"{api}/incidents", params={"q": target["number"]}, headers=actors.admin).json()
    assert [r["id"] for r in by_text["items"]] == [target["id"]]
    assert [r["id"] for r in by_number["items"]] == [target["id"]]


def test_search_treats_wildcards_and_sql_as_text(client, api, actors, make_incident):
    make_incident()
    for query in ("%", "_", "'; DROP TABLE incidents; --"):
        rows = client.get(f"{api}/incidents", params={"q": query}, headers=actors.admin).json()
        assert rows["total"] == 0


def test_rejects_an_unknown_sort_column(client, api, actors):
    assert client.get(f"{api}/incidents?sort=password", headers=actors.admin).status_code == 422


def test_comment_notifies_the_requester_and_counts_as_first_response(client, api, actors, make_incident):
    incident = make_incident()
    client.post(
        f"{api}/incidents/{incident['id']}/comments",
        json={"body": "Looking into this now"},
        headers=actors.admin,
    )
    body = client.get(f"{api}/incidents/{incident['id']}", headers=actors.admin).json()
    assert body["first_response_at"] is not None
    notifications = client.get(f"{api}/notifications", headers=actors.user).json()
    assert any("New comment" in item["title"] for item in notifications)


def test_notifications_are_private_and_can_be_marked_read(client, api, actors, make_incident):
    incident = make_incident()
    client.post(f"{api}/incidents/{incident['id']}/comments", json={"body": "Hello"}, headers=actors.admin)
    assert client.get(f"{api}/notifications", headers=actors.other).json() == []
    client.post(f"{api}/notifications/read-all", headers=actors.user)
    assert client.get(f"{api}/notifications?unread_only=true", headers=actors.user).json() == []


def test_notification_summary_covers_every_type_and_status(client, api, actors, make_incident):
    incident = make_incident()
    client.post(f"{api}/incidents/{incident['id']}/comments", json={"body": "Hello"}, headers=actors.admin)

    body = client.get(f"{api}/notifications/summary", headers=actors.user).json()
    assert {item["key"] for item in body["by_type"]} == set(NotificationType)
    assert {item["key"] for item in body["by_status"]} == set(Status)
    assert next(item for item in body["by_type"] if item["key"] == "comment")["unread"] == 1
    assert body["unread"] == body["total"] == sum(item["unread"] for item in body["by_status"])

    client.post(f"{api}/notifications/read-all", headers=actors.user)
    after = client.get(f"{api}/notifications/summary", headers=actors.user).json()
    assert after["unread"] == 0
    assert after["total"] == body["total"] == sum(item["read"] for item in after["by_type"])


def test_notification_summary_is_private(client, api, actors, make_incident):
    incident = make_incident()
    client.post(f"{api}/incidents/{incident['id']}/comments", json={"body": "Hello"}, headers=actors.admin)
    assert client.get(f"{api}/notifications/summary", headers=actors.other).json()["total"] == 0


def test_notification_summary_is_not_limited_to_one_page(client, api, actors, db):
    user_id = client.get(f"{api}/auth/me", headers=actors.user).json()["id"]
    db.add_all(Notification(user_id=user_id, type=NotificationType.ASSIGNED, title="No ticket") for _ in range(120))
    db.commit()

    body = client.get(f"{api}/notifications/summary", headers=actors.user).json()
    assert body["total"] == 120
    assert {"key": "no_ticket", "unread": 120, "read": 0} in body["by_status"]


def test_new_incident_is_triaged_by_trained_models(make_incident, client, api, actors, db, trained_models):
    incident = make_incident(
        title="Pods for orders-api are in CrashLoopBackOff",
        description="cluster nodes NotReady, deployment stuck and containers restart",
    )
    assert incident["category"] == "cloud_infrastructure"
    kinds = {row.kind for row in db.scalars(select(Prediction).where(Prediction.incident_id == incident["id"]))}
    assert kinds == {"category", "routing", "sla_risk"}
    staff = client.get(f"{api}/incidents/{incident['id']}", headers=actors.admin).json()
    assert 0 <= staff["sla_risk_score"] <= 1


def test_manual_category_correction_is_tracked(client, api, actors, make_incident, db, trained_models):
    incident = make_incident(
        title="Printer shows paper jam constantly", description="print jobs stay queued on the device"
    )
    predicted = incident["category"]
    corrected = "security" if predicted != "security" else "network"
    body = client.post(
        f"{api}/incidents/{incident['id']}/category",
        json={"category": corrected},
        headers=actors.admin,
    ).json()
    assert body["category"] == corrected
    assert body["category_corrected"] is True
    prediction = db.scalar(
        select(Prediction).where(Prediction.incident_id == incident["id"], Prediction.kind == "category")
    )
    assert prediction.accepted is False
    assert prediction.corrected_value == corrected
    assert db.scalar(select(AuditLog).where(AuditLog.action == "incident.category_corrected")) is not None


def test_routing_override_is_tracked(client, api, actors, make_incident, db, trained_models):
    incident = make_incident()
    other_team = db.scalar(select(Team).where(Team.name == "Security Operations"))
    client.post(f"{api}/incidents/{incident['id']}/assign", json={"team_id": other_team.id}, headers=actors.admin)
    prediction = db.scalar(
        select(Prediction).where(Prediction.incident_id == incident["id"], Prediction.kind == "routing")
    )
    assert prediction.accepted is (prediction.value == other_team.name)


def test_incidents_can_be_created_without_any_model(client, api, actors, make_incident, monkeypatch):
    from app.ml import inference

    for name in ("predict_category", "recommend_team", "predict_sla_risk"):
        monkeypatch.setattr(inference, name, lambda *_: None)
    incident = make_incident()
    assert incident["category"] is None


def test_a_crashing_model_does_not_block_ticket_creation(make_incident, monkeypatch):
    from app.ml import inference

    def explode(*_):
        raise RuntimeError("model file corrupted")

    for name in ("predict_category", "recommend_team", "predict_sla_risk"):
        monkeypatch.setattr(inference, name, explode)
    assert make_incident()["status"] == "new"


def test_dashboard_reports_real_values(client, api, actors, make_incident):
    incident = make_incident()
    _status(client, api, actors, incident["id"], "resolved", "Fixed")
    make_incident()
    body = client.get(f"{api}/analytics/dashboard?days=30", headers=actors.admin).json()
    assert body["summary"]["created"] == 2
    assert body["summary"]["resolved"] == 1
    assert body["summary"]["sla_compliance"] == 1.0
    assert body["summary"]["open_now"] == 1
    assert body["trend"][0]["created"] == 2
