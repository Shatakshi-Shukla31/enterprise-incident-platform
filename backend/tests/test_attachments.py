import pytest

from app.core.config import get_settings
from app.models import Attachment
from app.services import attachments

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
WEBM = b"\x1aE\xdf\xa3" + b"\x00" * 64
LOG = b"2026-11-10 10:01 INFO starting client\n2026-11-10 10:02 ERROR tunnel to vpn gateway timed out\nbye\n"


def _upload(client, api, headers, name, data, content_type="application/octet-stream"):
    return client.post(f"{api}/ai/attachments", files={"file": (name, data, content_type)}, headers=headers)


@pytest.mark.parametrize(
    ("name", "data", "kind"),
    [("photo.png", PNG, "image"), ("note.webm", WEBM, "audio"), ("client.log", LOG, "text"), ("report.pdf", b"%PDF-1.7\n", "document")],
)
def test_photos_voice_notes_logs_and_pdfs_are_accepted(client, api, actors, name, data, kind):
    response = _upload(client, api, actors.user, name, data)
    assert response.status_code == 201, response.text
    assert response.json()["kind"] == kind
    assert response.json()["size_bytes"] == len(data)


@pytest.mark.parametrize(
    ("name", "data"),
    [
        ("photo.png", b"<svg onload=alert(1)>"),  # a name does not make a file a photo
        ("page.html", b"<html><script>alert(1)</script></html>"),
        ("tool.exe", b"MZ\x90\x00binary"),
        ("notes.txt", b"\xff\xfe not utf-8 \x00"),
    ],
)
def test_the_type_comes_from_the_bytes_not_the_name(client, api, actors, name, data):
    assert _upload(client, api, actors.user, name, data).status_code == 415


def test_empty_and_oversized_files_are_refused(client, api, actors, monkeypatch):
    assert _upload(client, api, actors.user, "empty.log", b"").status_code == 400
    monkeypatch.setattr(attachments, "MAX_BYTES", 10)
    assert _upload(client, api, actors.user, "photo.png", PNG).status_code == 413


def test_each_person_has_a_storage_limit(client, api, actors, monkeypatch):
    monkeypatch.setattr(attachments, "PER_USER_BYTES", len(PNG) + 10)
    assert _upload(client, api, actors.user, "one.png", PNG).status_code == 201
    assert _upload(client, api, actors.user, "two.png", PNG).status_code == 413
    assert _upload(client, api, actors.other, "theirs.png", PNG).status_code == 201


def test_only_the_uploader_can_download(client, api, actors):
    attachment_id = _upload(client, api, actors.user, "photo.png", PNG).json()["id"]
    mine = client.get(f"{api}/ai/attachments/{attachment_id}", headers=actors.user)
    assert mine.status_code == 200
    assert mine.content == PNG
    assert mine.headers["content-type"] == "image/png"
    assert mine.headers["content-disposition"].startswith("inline")
    assert client.get(f"{api}/ai/attachments/{attachment_id}", headers=actors.other).status_code == 404
    assert client.get(f"{api}/ai/attachments/{attachment_id}", headers=actors.admin).status_code == 404


def test_documents_download_rather_than_open(client, api, actors):
    attachment_id = _upload(client, api, actors.user, "report.pdf", b"%PDF-1.7\n").json()["id"]
    response = client.get(f"{api}/ai/attachments/{attachment_id}", headers=actors.user)
    assert response.headers["content-disposition"].startswith("attachment")


def test_a_file_name_cannot_carry_a_path_or_break_the_header(client, api, actors):
    name = _upload(client, api, actors.user, '..\\..\\secret"name.log', LOG).json()["filename"]
    assert name.startswith("secret") and name.endswith("name.log")
    assert not any(character in name for character in '/\\"')


def test_an_attached_log_shapes_the_answer_and_stays_with_the_message(client, api, actors, db, monkeypatch):
    seen = []
    from app.rag import service

    real = service._chat_evidence
    monkeypatch.setattr(service, "_chat_evidence", lambda db_, user, message, *rest: seen.append(message) or real(db_, user, message, *rest))
    log_id = _upload(client, api, actors.user, "client.log", LOG).json()["id"]
    photo_id = _upload(client, api, actors.user, "screen.png", PNG).json()["id"]

    response = client.post(
        f"{api}/ai/chat", json={"message": "my vpn stopped working", "attachment_ids": [log_id, photo_id]}, headers=actors.user
    )
    assert response.status_code == 200, response.text
    assert "ERROR tunnel to vpn gateway timed out" in seen[0]
    assert "starting client" not in seen[0], "error lines are preferred over the rest of the log"

    detail = client.get(f"{api}/ai/conversations/{response.json()['conversation_id']}", headers=actors.user).json()
    names = [item["filename"] for item in detail["messages"][0]["attachments"]]
    assert names == ["client.log", "screen.png"]


def test_a_file_can_be_sent_only_once_and_only_by_its_owner(client, api, actors):
    photo_id = _upload(client, api, actors.user, "screen.png", PNG).json()["id"]
    theirs = client.post(f"{api}/ai/chat", json={"message": "look at this", "attachment_ids": [photo_id]}, headers=actors.other)
    assert theirs.status_code == 404
    first = client.post(f"{api}/ai/chat", json={"message": "look at this", "attachment_ids": [photo_id]}, headers=actors.user)
    assert first.status_code == 200
    again = client.post(f"{api}/ai/chat", json={"message": "and again", "attachment_ids": [photo_id]}, headers=actors.user)
    assert again.status_code == 404


def test_at_most_three_files_per_message(client, api, actors):
    ids = [_upload(client, api, actors.user, f"{n}.png", PNG).json()["id"] for n in range(4)]
    assert client.post(f"{api}/ai/chat", json={"message": "four files", "attachment_ids": ids}, headers=actors.user).status_code == 422


def test_the_demo_can_attach_files(client, api):
    token = client.post(f"{api}/auth/demo").json()["access_token"]
    response = _upload(client, api, {"Authorization": f"Bearer {token}"}, "screen.png", PNG)
    assert response.status_code == 201


def test_uploads_need_an_account(client, api):
    assert _upload(client, api, {}, "photo.png", PNG).status_code == 401


def test_the_cleaner_drops_paths_and_quotes():
    assert attachments._clean_name('..\\..\\secret"name.log') == "secretname.log"
    assert attachments._clean_name("/etc/passwd") == "passwd"
    assert attachments._clean_name("") == "attachment"


def test_file_bytes_are_not_loaded_with_the_list(db, client, api, actors):
    _upload(client, api, actors.user, "photo.png", PNG)
    item = db.query(Attachment).first()
    assert "data" not in item.__dict__, "the bytes load only when asked for"
    assert get_settings().rate_limit_upload
