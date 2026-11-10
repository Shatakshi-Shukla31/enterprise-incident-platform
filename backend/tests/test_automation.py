from datetime import timedelta

from sqlalchemy import func, select

from app.core.enums import NotificationType, Status
from app.db.base import utcnow
from app.models import AuditLog, Incident, KnowledgeDocument, Notification
from app.services import sla
from app.workers import tasks


def _make_overdue(db, incident_id: int) -> None:
    db.get(Incident, incident_id).resolution_due_at = utcnow() - timedelta(minutes=5)
    db.commit()


def test_breach_is_marked_escalated_and_notified(make_incident, db):
    incident = make_incident()
    _make_overdue(db, incident["id"])
    result = sla.run_sla_check(db)
    assert result["breached"] == 1
    db.expire_all()
    row = db.get(Incident, incident["id"])
    assert row.sla_breached is True
    assert row.escalation_level == 1
    assert db.scalar(select(AuditLog).where(AuditLog.action == "sla.breached")) is not None
    assert (
        db.scalar(
            select(func.count()).select_from(Notification).where(Notification.type == NotificationType.SLA_BREACH)
        )
        >= 1
    )


def test_sla_check_is_idempotent(make_incident, db):
    incident = make_incident()
    _make_overdue(db, incident["id"])
    sla.run_sla_check(db)
    count = db.scalar(select(func.count()).select_from(Notification))
    assert sla.run_sla_check(db)["breached"] == 0
    assert db.scalar(select(func.count()).select_from(Notification)) == count
    db.expire_all()
    assert db.get(Incident, incident["id"]).escalation_level == 1


def test_incident_on_hold_does_not_breach(make_incident, db):
    incident = make_incident()
    row = db.get(Incident, incident["id"])
    row.status = Status.ON_HOLD
    row.on_hold_since = utcnow()
    db.commit()
    _make_overdue(db, incident["id"])
    assert sla.run_sla_check(db)["breached"] == 0


def test_resolved_incident_does_not_breach(make_incident, db):
    incident = make_incident()
    db.get(Incident, incident["id"]).status = Status.RESOLVED
    db.commit()
    _make_overdue(db, incident["id"])
    assert sla.run_sla_check(db)["breached"] == 0


def test_high_risk_alerts_once(make_incident, db):
    incident = make_incident()
    db.get(Incident, incident["id"]).sla_risk_score = 0.95
    db.commit()
    assert sla.run_sla_check(db)["risk_alerts"] == 1
    assert sla.run_sla_check(db)["risk_alerts"] == 0


def test_overdue_response_notifies_once(make_incident, db):
    incident = make_incident()
    db.get(Incident, incident["id"]).response_due_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert sla.run_sla_check(db)["response_alerts"] >= 1
    assert sla.run_sla_check(db)["response_alerts"] == 0


def test_check_sla_task_runs(make_incident, db):
    incident = make_incident()
    _make_overdue(db, incident["id"])
    assert tasks.check_sla()["breached"] == 1


def test_auto_close_only_touches_old_resolutions(make_incident, db):
    old, recent = make_incident(), make_incident()
    for incident, age in ((old, 8), (recent, 1)):
        row = db.get(Incident, incident["id"])
        row.status = Status.RESOLVED
        row.resolved_at = utcnow() - timedelta(days=age)
    db.commit()
    assert tasks.auto_close_resolved() == 1
    db.expire_all()
    assert db.get(Incident, old["id"]).status == Status.CLOSED
    assert db.get(Incident, recent["id"]).status == Status.RESOLVED


def test_resolving_indexes_the_incident_and_reopening_removes_it(client, api, actors, make_incident, db):
    incident = make_incident()
    url = f"{api}/incidents/{incident['id']}/status"
    client.post(url, json={"status": "resolved", "resolution_notes": "Replaced the VPN client"}, headers=actors.admin)
    document = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.source_ref == incident["number"]))
    assert document is not None
    client.post(url, json={"status": "in_progress"}, headers=actors.admin)
    db.expire_all()
    assert db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.source_ref == incident["number"])) is None


def test_reconcile_indexes_tickets_whose_task_was_lost(make_incident, db):
    incident = make_incident()
    row = db.get(Incident, incident["id"])
    row.status = Status.RESOLVED
    row.resolved_at = utcnow()
    row.resolution_notes = "Rebuilt the tunnel profile"
    db.commit()
    assert tasks.reconcile_resolved_incidents() == 1
    assert tasks.reconcile_resolved_incidents() == 0


def test_hosted_reconcile_updates_bundled_articles_without_resetting_tickets(make_incident, db, tmp_path, monkeypatch):
    incident = make_incident()
    settings = tasks.get_settings()
    monkeypatch.setattr(settings, "single_process", True)
    monkeypatch.setattr(settings, "knowledge_dir", tmp_path)
    article = tmp_path / "owner.md"
    content = "---\nid: KB-OWNER\ntitle: Platform owner\naccess: public\n---\nThe owner is Shatakshi Shukla.\n"
    article.write_text(content, encoding="utf-8")
    assert tasks.reconcile_resolved_incidents() == 0
    document = db.scalar(select(KnowledgeDocument).where(KnowledgeDocument.source_ref == "KB-OWNER"))
    original_id, original_hash = document.id, document.content_hash
    article.write_text(content + "Open the + menu to attach files.\n", encoding="utf-8")
    tasks.reconcile_resolved_incidents()
    db.expire_all()
    document = db.get(KnowledgeDocument, original_id)
    assert document.content_hash != original_hash
    assert db.query(KnowledgeDocument).count() == 1
    assert db.get(Incident, incident["id"]) is not None


def test_a_broken_broker_does_not_fail_the_request(client, api, actors, make_incident, monkeypatch):
    from app.workers import celery_app as module

    def down(*_, **__):
        raise ConnectionError("broker unavailable")

    monkeypatch.setitem(module.celery_app.conf, "task_always_eager", False)
    monkeypatch.setattr(module.celery_app, "send_task", down)
    incident = make_incident()
    response = client.post(
        f"{api}/incidents/{incident['id']}/status",
        json={"status": "resolved", "resolution_notes": "Fixed anyway"},
        headers=actors.admin,
    )
    assert response.status_code == 200


def test_rolled_back_work_is_not_queued(monkeypatch, db):
    from app.workers import dispatch

    sent = []
    monkeypatch.setattr(dispatch, "_send", lambda name, args: sent.append(name))
    dispatch.enqueue("check_sla", after_commit_of=db)
    db.rollback()
    assert sent == []
    db.commit()


def test_health_and_ready(client):
    assert client.get("/health").json() == {"status": "ok"}
    body = client.get("/ready").json()
    assert body["database"] == "ok"


def test_metrics_require_the_token(client):
    assert client.get("/metrics").status_code == 404
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 404
    response = client.get("/metrics", headers={"Authorization": "Bearer metrics-test-token"})
    assert response.status_code == 200
    assert "http_requests_total" in response.text


def test_api_schema_is_available_outside_production(client):
    assert client.get("/openapi.json").status_code == 200


def test_security_headers_and_request_id(client):
    response = client.get("/health", headers={"x-request-id": "trace-123"})
    assert response.headers["x-request-id"] == "trace-123"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
