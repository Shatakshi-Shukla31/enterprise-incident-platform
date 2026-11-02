"""Knowledge ingestion: clean, chunk, screen, embed and store."""

import hashlib
import logging
import re
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import AccessLevel, Category, DocumentSource
from app.models import Incident, KnowledgeChunk, KnowledgeDocument, Team
from app.rag.embeddings import get_embedder
from app.rag.text import chunk_text, clean_text, looks_like_injection, redact_pii
from app.services.errors import ServiceError

logger = logging.getLogger(__name__)

_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)


def parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    match = _FRONT_MATTER.match(raw.replace("\r\n", "\n"))
    if match is None:
        return {}, raw
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, match.group(2)


def _upsert(
    db: Session,
    source_type: DocumentSource,
    source_ref: str,
    title: str,
    content: str,
    category: str | None,
    access_level: AccessLevel,
    team_id: int | None,
) -> dict:
    settings = get_settings()
    cleaned = clean_text(content)
    digest = hashlib.sha256(f"{title}\n{access_level}\n{team_id}\n{category}\n{cleaned}".encode()).hexdigest()
    document = db.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.source_type == source_type, KnowledgeDocument.source_ref == source_ref
        )
    )
    if document is not None and document.content_hash == digest:
        return {"document_id": document.id, "chunks": 0, "flagged_chunks": 0, "unchanged": True}

    chunks = chunk_text(cleaned, settings.rag_chunk_size, settings.rag_chunk_overlap)
    if not chunks:
        raise ValueError(f"No content to index for {source_ref}")
    # The title gives each chunk its topic, which matters for short chunks mid-document.
    vectors = get_embedder().embed([f"{title}\n{chunk}" for chunk in chunks])

    if document is None:
        document = KnowledgeDocument(source_type=source_type, source_ref=source_ref)
        db.add(document)
    document.title = title
    document.category = category
    document.access_level = access_level
    document.team_id = team_id
    document.content_hash = digest
    db.flush()
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id))

    flagged = 0
    for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
        suspicious = looks_like_injection(chunk)
        flagged += suspicious
        db.add(
            KnowledgeChunk(
                document_id=document.id,
                chunk_index=index,
                content=chunk,
                embedding=vector,
                flagged_injection=suspicious,
            )
        )
    if flagged:
        logger.warning("%s: %d chunk(s) quarantined as possible injection", source_ref, flagged)
    db.flush()
    return {"document_id": document.id, "chunks": len(chunks), "flagged_chunks": flagged, "unchanged": False}


def ingest_article(
    db: Session,
    source_ref: str,
    title: str,
    content: str,
    category: str | None,
    access_level: AccessLevel,
    team_id: int | None = None,
) -> dict:
    if access_level == AccessLevel.RESTRICTED and team_id is None:
        raise ServiceError("Restricted documents need an owning team")
    return _upsert(db, DocumentSource.KB_ARTICLE, source_ref, title, content, category, access_level, team_id)


def ingest_directory(db: Session, directory: Path | None = None) -> dict[str, int]:
    directory = directory or get_settings().knowledge_dir
    teams = {team.name: team.id for team in db.scalars(select(Team))}
    summary = {"documents": 0, "chunks": 0, "flagged_chunks": 0, "unchanged": 0}
    for path in sorted(directory.glob("*.md")):
        fields, body = parse_front_matter(path.read_text(encoding="utf-8"))
        result = ingest_article(
            db,
            source_ref=fields["id"],
            title=fields["title"],
            content=body,
            category=fields.get("category"),
            access_level=AccessLevel(fields.get("access", "internal")),
            team_id=teams.get(fields.get("team", "")),
        )
        summary["documents"] += 1
        summary["chunks"] += result["chunks"]
        summary["flagged_chunks"] += result["flagged_chunks"]
        summary["unchanged"] += int(result["unchanged"])
    db.commit()
    return summary


def index_resolved_incident(db: Session, incident: Incident) -> dict | None:
    """Make a resolved ticket searchable. Text is redacted and security tickets stay with
    the owning team, because their contents can describe active weaknesses."""
    if not incident.resolution_notes:
        return None
    content = redact_pii(f"Problem reported: {incident.description}\n\nResolution: {incident.resolution_notes}")
    is_sensitive = incident.category == Category.SECURITY and incident.team_id is not None
    return _upsert(
        db,
        DocumentSource.RESOLVED_INCIDENT,
        incident.number,
        redact_pii(incident.title),
        content,
        incident.category,
        AccessLevel.RESTRICTED if is_sensitive else AccessLevel.INTERNAL,
        incident.team_id,
    )


def remove_incident(db: Session, incident: Incident) -> None:
    document = db.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.source_type == DocumentSource.RESOLVED_INCIDENT,
            KnowledgeDocument.source_ref == incident.number,
        )
    )
    if document is not None:
        db.delete(document)
