import pytest
from sqlalchemy import select

from app.models import Incident, Team


def _assign_team(db, incident_id: int, team_name: str) -> None:
    team = db.scalar(select(Team).where(Team.name == team_name))
    db.get(Incident, incident_id).team_id = team.id
    db.commit()


def test_requester_sees_only_their_own_incidents(client, api, actors, make_incident):
    mine = make_incident(actors.user)
    make_incident(actors.other)
    rows = client.get(f"{api}/incidents", headers=actors.user).json()
    assert [row["id"] for row in rows["items"]] == [mine["id"]]


def test_other_requesters_incident_is_a_404_not_a_403(client, api, actors, make_incident):
    theirs = make_incident(actors.other)
    assert client.get(f"{api}/incidents/{theirs['id']}", headers=actors.user).status_code == 404


def test_requester_cannot_read_ai_fields(client, api, actors, make_incident, trained_models):
    body = make_incident(actors.user)
    assert body["sla_risk_score"] is None
    assert body["category_confidence"] is None
    staff_view = client.get(f"{api}/incidents/{body['id']}", headers=actors.admin).json()
    assert staff_view["sla_risk_score"] is not None


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/incidents/{id}/status", {"status": "in_progress"}),
        ("post", "/incidents/{id}/assign", {"team_id": 1}),
        ("post", "/incidents/{id}/escalate", {"reason": "faster please"}),
        ("post", "/incidents/{id}/category", {"category": "network"}),
        ("get", "/incidents/{id}/audit", None),
        ("get", "/incidents/{id}/predictions", None),
        ("post", "/incidents/{id}/ai/suggest", None),
        ("patch", "/incidents/{id}", {"title": "Changed by the requester"}),
    ],
)
def test_requester_is_blocked_from_staff_actions(client, api, actors, make_incident, method, path, body):
    incident = make_incident(actors.user)
    url = f"{api}{path.format(id=incident['id'])}"
    response = client.request(method, url, json=body, headers=actors.user)
    assert response.status_code == 403


def test_requester_cannot_see_or_write_internal_notes(client, api, actors, make_incident):
    incident = make_incident(actors.user)
    url = f"{api}/incidents/{incident['id']}/comments"
    client.post(url, json={"body": "Staff only note", "is_internal": True}, headers=actors.admin)
    client.post(url, json={"body": "Visible reply", "is_internal": False}, headers=actors.admin)
    visible = [c["body"] for c in client.get(url, headers=actors.user).json()]
    assert visible == ["Visible reply"]
    denied = client.post(url, json={"body": "Sneaky", "is_internal": True}, headers=actors.user)
    assert denied.status_code == 403


def test_agent_cannot_see_another_teams_incident(client, api, actors, make_incident, db):
    incident = make_incident(actors.user)
    _assign_team(db, incident["id"], "Security Operations")
    assert client.get(f"{api}/incidents/{incident['id']}", headers=actors.agent).status_code == 404
    assert client.get(f"{api}/incidents/{incident['id']}", headers=actors.secagent).status_code == 200
    rows = client.get(f"{api}/incidents", headers=actors.agent).json()
    assert rows["total"] == 0


def test_agent_can_claim_but_not_assign_others(client, api, actors, make_incident, db):
    incident = make_incident(actors.user)
    _assign_team(db, incident["id"], "Network Operations")
    url = f"{api}/incidents/{incident['id']}/assign"
    me = client.get(f"{api}/auth/me", headers=actors.agent).json()
    manager = client.get(f"{api}/auth/me", headers=actors.manager).json()
    assert client.post(url, json={"assignee_id": manager["id"]}, headers=actors.agent).status_code == 403
    claimed = client.post(url, json={"assignee_id": me["id"]}, headers=actors.agent)
    assert claimed.status_code == 200
    assert claimed.json()["assignee"]["id"] == me["id"]
    assert claimed.json()["status"] == "assigned"


@pytest.mark.parametrize("who", ["user", "agent"])
def test_dashboard_is_manager_only(client, api, actors, who):
    assert client.get(f"{api}/analytics/dashboard", headers=getattr(actors, who)).status_code == 403


@pytest.mark.parametrize("who", ["user", "agent", "manager"])
def test_only_admins_create_users(client, api, actors, who):
    response = client.post(
        f"{api}/users",
        json={"email": "x@test.io", "full_name": "New User", "password": "long-enough-password"},
        headers=getattr(actors, who),
    )
    assert response.status_code == 403


def test_admin_cannot_lock_themselves_out(client, api, actors):
    me = client.get(f"{api}/auth/me", headers=actors.admin).json()
    response = client.patch(f"{api}/users/{me['id']}", json={"is_active": False}, headers=actors.admin)
    assert response.status_code == 400


def test_requester_cannot_list_users_or_knowledge(client, api, actors):
    assert client.get(f"{api}/users", headers=actors.user).status_code == 403
    assert client.get(f"{api}/knowledge/documents", headers=actors.user).status_code == 403


def test_user_cannot_read_anothers_conversation(client, api, actors, similarity_floor):
    conversation = client.post(f"{api}/ai/chat", json={"message": "my vpn keeps dropping"}, headers=actors.user).json()
    url = f"{api}/ai/conversations/{conversation['conversation_id']}"
    assert client.get(url, headers=actors.user).status_code == 200
    assert client.get(url, headers=actors.other).status_code == 404


def test_user_cannot_chat_about_an_incident_they_cannot_see(client, api, actors, make_incident):
    incident = make_incident(actors.other)
    response = client.post(
        f"{api}/ai/chat",
        json={"message": "summarise this ticket", "incident_id": incident["id"]},
        headers=actors.user,
    )
    assert response.status_code == 404


def test_admin_creates_a_user_who_can_sign_in(client, api, actors):
    created = client.post(
        f"{api}/users",
        json={
            "email": "New.Agent@test.io",
            "full_name": "New Agent",
            "password": "a-long-enough-password",
            "role": "agent",
        },
        headers=actors.admin,
    )
    assert created.status_code == 201
    assert created.json()["email"] == "new.agent@test.io"
    assert "password" not in created.text
    login = client.post(
        f"{api}/auth/login", data={"username": "new.agent@test.io", "password": "a-long-enough-password"}
    )
    assert login.status_code == 200


def test_unknown_team_is_rejected_for_users(client, api, actors):
    payload = {"email": "t@test.io", "full_name": "Team Test", "password": "a-long-enough-password", "team_id": 99999}
    assert client.post(f"{api}/users", json=payload, headers=actors.admin).status_code == 400
    me = client.get(f"{api}/auth/me", headers=actors.user).json()
    update = client.patch(f"{api}/users/{me['id']}", json={"team_id": 99999}, headers=actors.admin)
    assert update.status_code == 400


def test_duplicate_email_is_a_conflict(client, api, actors):
    response = client.post(
        f"{api}/users",
        json={"email": "user@test.io", "full_name": "Copy", "password": "a-long-enough-password"},
        headers=actors.admin,
    )
    assert response.status_code == 409


def test_staff_can_filter_users_and_requesters_are_excluded(client, api, actors):
    body = client.get(f"{api}/users?staff_only=true&page_size=100", headers=actors.agent).json()
    assert body["total"] == 5
    assert all(person["role"] != "requester" for person in body["items"])


def test_updating_an_unknown_user_is_a_404(client, api, actors):
    assert client.patch(f"{api}/users/99999", json={"is_active": False}, headers=actors.admin).status_code == 404


def test_managers_create_teams_and_duplicates_conflict(client, api, actors):
    assert client.post(f"{api}/teams", json={"name": "Service Desk"}, headers=actors.manager).status_code == 201
    assert client.post(f"{api}/teams", json={"name": "Service Desk"}, headers=actors.manager).status_code == 409
    assert client.post(f"{api}/teams", json={"name": "Nope"}, headers=actors.agent).status_code == 403
    names = [team["name"] for team in client.get(f"{api}/teams", headers=actors.user).json()]
    assert "Service Desk" in names
