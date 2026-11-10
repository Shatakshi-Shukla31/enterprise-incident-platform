"""Files people add to assistant messages: images, audio, video, PDFs and text or log files.

The type comes from the file's own bytes, never from its name or the browser's claim, and
there are caps per file, per person and in total, so a public demo cannot fill a small free
database. Only text files are read: nothing here can see a photo or hear a recording.
"""

import re
from pathlib import PurePath

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AIMessage, Attachment, User
from app.services.errors import NotFound, ServiceError

MAX_BYTES = 5 * 2**20
PER_USER_BYTES = 25 * 2**20
TOTAL_BYTES = 300 * 2**20
MAX_PER_MESSAGE = 3
TEXT_SUFFIXES = frozenset({".txt", ".log", ".csv", ".json", ".md", ".xml", ".yaml", ".yml", ".ini", ".conf", ".cfg"})
_STORED_TEXT_CHARS = 20_000
_EVIDENCE_CHARS = 600
_PROBLEM_LINE = re.compile(
    r"error|exception|fail|fatal|denied|refused|timed? ?out|cannot|unable|invalid|unreachable"
    r"|\b[45]\d\d\b|0x[0-9a-f]{6,}",
    re.IGNORECASE,
)


class TooLarge(ServiceError):
    status_code = 413


class Unsupported(ServiceError):
    status_code = 415


def _detect(data: bytes, filename: str) -> tuple[str, str] | None:
    """(kind, content type) from the leading bytes. SVG and HTML are refused, because a
    browser can run script inside them."""
    signatures = (
        (b"\x89PNG\r\n\x1a\n", "image", "image/png"),
        (b"\xff\xd8\xff", "image", "image/jpeg"),
        (b"GIF87a", "image", "image/gif"),
        (b"GIF89a", "image", "image/gif"),
        (b"%PDF-", "document", "application/pdf"),
        (b"ID3", "audio", "audio/mpeg"),
    )
    for prefix, kind, content_type in signatures:
        if data.startswith(prefix):
            return kind, content_type
    if data.startswith(b"\x1aE\xdf\xa3"):
        # WebM TrackType=1 and video codec identifiers distinguish video from voice notes.
        video = b"\x83\x81\x01" in data or b"V_VP" in data or b"V_AV1" in data
        return ("video", "video/webm") if video else ("audio", "audio/webm")
    if data.startswith(b"OggS"):
        return ("video", "video/ogg") if b"\x80theora" in data else ("audio", "audio/ogg")
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image", "image/webp"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "audio", "audio/wav"
    if data[:4] == b"RIFF" and data[8:12] == b"AVI ":
        return "video", "video/x-msvideo"
    if data[4:8] == b"ftyp":
        audio = data[8:12] in (b"M4A ", b"M4B ") or (b"soun" in data and b"vide" not in data)
        kind = "audio" if audio else "video"
        return kind, f"{kind}/mp4"
    if PurePath(filename).suffix.lower() in TEXT_SUFFIXES and b"\x00" not in data:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return "text", "text/plain; charset=utf-8"
    return None


def _clean_name(filename: str) -> str:
    name = PurePath(filename.replace("\\", "/")).name
    name = re.sub(r"[\x00-\x1f\x7f\"]", "", name).strip() or "attachment"
    return name[-255:]


def _bytes_used(db: Session, user: User | None = None) -> int:
    stmt = select(func.coalesce(func.sum(Attachment.size_bytes), 0))
    if user is not None:
        stmt = stmt.where(Attachment.user_id == user.id)
    return int(db.scalar(stmt))


def save(db: Session, user: User, filename: str, data: bytes) -> Attachment:
    if not data:
        raise ServiceError("The file is empty")
    if len(data) > MAX_BYTES:
        raise TooLarge("Files can be up to 5 MB")
    detected = _detect(data, filename)
    if detected is None:
        raise Unsupported("Attach an image, audio, video, PDF, or a text or log file")
    if _bytes_used(db, user) + len(data) > PER_USER_BYTES:
        raise TooLarge("You have used your 25 MB of attachments")
    if _bytes_used(db) + len(data) > TOTAL_BYTES:
        raise TooLarge("Attachment storage on this site is full")
    kind, content_type = detected
    attachment = Attachment(
        user_id=user.id,
        kind=kind,
        filename=_clean_name(filename),
        content_type=content_type,
        size_bytes=len(data),
        data=data,
        extracted_text=data.decode("utf-8")[:_STORED_TEXT_CHARS] if kind == "text" else None,
    )
    db.add(attachment)
    db.commit()
    return attachment


def unsent(db: Session, user: User, ids: list[int]) -> list[Attachment]:
    """The person's own uploads that are not yet part of a message, in the order given."""
    wanted = list(dict.fromkeys(ids))
    if len(wanted) > MAX_PER_MESSAGE:
        raise ServiceError(f"Attach up to {MAX_PER_MESSAGE} files to a message")
    if not wanted:
        return []
    found = {
        item.id: item
        for item in db.scalars(
            select(Attachment).where(
                Attachment.id.in_(wanted), Attachment.user_id == user.id, Attachment.message_id.is_(None)
            )
        )
    }
    if len(found) != len(wanted):
        raise NotFound("Attachment not found")
    return [found[item_id] for item_id in wanted]


def link(items: list[Attachment], message: AIMessage) -> None:
    for item in items:
        item.message_id = message.id


def evidence(items: list[Attachment]) -> str:
    """The lines of attached text most likely to describe the problem, to add to the search.
    A log is mostly noise, so lines that look like errors are preferred."""
    picked: list[str] = []
    for item in items:
        lines = [line.strip() for line in (item.extracted_text or "").splitlines() if line.strip()]
        problems = [line for line in lines if _PROBLEM_LINE.search(line)] or lines[:3]
        picked.extend(line[:200] for line in problems[:6])
    return "\n".join(dict.fromkeys(picked))[:_EVIDENCE_CHARS]


def for_download(db: Session, user: User, attachment_id: int) -> Attachment:
    attachment = db.get(Attachment, attachment_id)
    # Someone else's file reads as missing, so ids cannot be probed.
    if attachment is None or attachment.user_id != user.id:
        raise NotFound("Attachment not found")
    return attachment
