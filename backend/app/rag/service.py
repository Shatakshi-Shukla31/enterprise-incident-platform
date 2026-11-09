"""Application-facing RAG operations: incident suggestions and the support assistant."""

import re
import time

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.enums import DocumentSource
from app.models import AIConversation, AIMessage, AIRecommendation, Incident, Runbook, User
from app.rag import retriever
from app.rag.generator import GeneratedAnswer, generate_answer
from app.services import attachments
from app.services.access import is_staff
from app.services.errors import NotFound
from app.services.incidents import get_incident

_FOLLOW_UP = re.compile(
    r"\b(it|that|this|those|them|else|another|again|still|instead|also|more|next|same"
    r"|didn'?t|doesn'?t|won'?t|fails?|failed)\b",
    re.IGNORECASE,
)
# A message that finds this much evidence by itself is a new question, even if it contains a
# word such as "won't". Set from a small hand-checked sample, not tuned on the golden set.
STANDS_ALONE_SIMILARITY = 0.55


def _store(db: Session, user: User, query: str, result: GeneratedAnswer, incident_id: int | None) -> AIRecommendation:
    recommendation = AIRecommendation(
        incident_id=incident_id,
        user_id=user.id,
        query=query[:4000],
        answer=result.answer,
        citations=result.citations,
        insufficient_evidence=result.insufficient_evidence,
        provider=result.provider,
        latency_ms=result.latency_ms,
    )
    db.add(recommendation)
    db.flush()
    return recommendation


def _related(chunks: list[retriever.RetrievedChunk], limit: int = 5) -> list[dict]:
    """Resolved incidents among the search hits, best match first, one row per ticket."""
    min_similarity = get_settings().rag_min_similarity
    rows: dict[str, dict] = {}
    for chunk in chunks:
        if (
            chunk.source_type == DocumentSource.RESOLVED_INCIDENT
            and chunk.similarity >= min_similarity
            and chunk.source_ref not in rows
        ):
            rows[chunk.source_ref] = {
                "incident_id": int(chunk.source_ref.removeprefix("INC")),
                "source_ref": chunk.source_ref,
                "title": chunk.title,
                "similarity": chunk.similarity,
            }
    return list(rows.values())[:limit]


def _suggested_actions(db: Session, user: User, result: GeneratedAnswer) -> list[dict]:
    """Runbooks matching the categories of the cited sources. These are proposals: running
    one still needs a request and a second person's approval."""
    if result.insufficient_evidence or not is_staff(user):
        return []
    categories = {chunk.category for chunk in result.used_chunks if chunk.category}
    if not categories:
        return []
    runbooks = db.scalars(select(Runbook).where(Runbook.is_active.is_(True), Runbook.category.in_(categories)))
    return [
        {"runbook_id": runbook.id, "name": runbook.name, "description": runbook.description} for runbook in runbooks
    ]


def _response(
    db: Session,
    user: User,
    result: GeneratedAnswer,
    recommendation: AIRecommendation,
    related: list[dict],
) -> dict:
    return {
        "recommendation_id": recommendation.id,
        "answer": result.answer,
        "citations": result.citations,
        "insufficient_evidence": result.insufficient_evidence,
        "provider": result.provider,
        "latency_ms": recommendation.latency_ms,
        "related_incidents": related,
        "suggested_actions": _suggested_actions(db, user, result),
    }


def suggest_for_incident(db: Session, user: User, incident_id: int) -> dict:
    incident = get_incident(db, user, incident_id)
    started = time.perf_counter()
    query = f"{incident.title}\n{incident.description}"
    chunks = retriever.retrieve(db, user, query, exclude_refs=(incident.number,))
    db.commit()  # an LLM call can take a minute; do not hold a connection open through it
    result = generate_answer(query, chunks)
    result.latency_ms = int((time.perf_counter() - started) * 1000)
    recommendation = _store(db, user, query, result, incident.id)
    response = _response(db, user, result, recommendation, _related(chunks))
    db.commit()
    return response


def related_for_incident(db: Session, user: User, incident_id: int) -> list[dict]:
    incident = get_incident(db, user, incident_id)
    chunks = retriever.retrieve(
        db,
        user,
        f"{incident.title}\n{incident.description}",
        top_k=10,
        source_type=DocumentSource.RESOLVED_INCIDENT,
        exclude_refs=(incident.number,),
    )
    return _related(chunks)


def _retrieval_query(message: str, previous_user_messages: list[str]) -> str:
    """Add the earlier topic only to real follow-ups such as "what if that fails?". Merging
    every short message would let an unrelated question borrow the previous one's evidence
    and get an answer it has no support for."""
    if previous_user_messages and len(message) < 80 and _FOLLOW_UP.search(message):
        return f"{previous_user_messages[-1]}\n{message}"
    return message


def _chat_evidence(
    db: Session, user: User, message: str, previous: list[str], incident: Incident | None
) -> tuple[str, list[retriever.RetrievedChunk]]:
    prefix = f"{incident.title}\n" if incident else ""
    exclude = (incident.number,) if incident else ()
    chunks = retriever.retrieve(db, user, f"{prefix}{message}", exclude_refs=exclude)
    merged = _retrieval_query(message, previous)
    if merged == message or (chunks and chunks[0].similarity >= STANDS_ALONE_SIMILARITY):
        return f"{prefix}{message}", chunks
    return f"{prefix}{merged}", retriever.retrieve(db, user, f"{prefix}{merged}", exclude_refs=exclude)


def _conversation(db: Session, user: User, conversation_id: int) -> AIConversation:
    conversation = db.scalar(
        select(AIConversation)
        .options(
            selectinload(AIConversation.messages).selectinload(AIMessage.recommendation),
            selectinload(AIConversation.messages).selectinload(AIMessage.attachments),
        )
        .where(AIConversation.id == conversation_id, AIConversation.user_id == user.id)
    )
    if conversation is None:
        raise NotFound("Conversation not found")
    return conversation


def chat(
    db: Session,
    user: User,
    message: str,
    conversation_id: int | None,
    incident_id: int | None,
    attachment_ids: list[int] | None = None,
) -> dict:
    started = time.perf_counter()
    files = attachments.unsent(db, user, attachment_ids or [])
    incident: Incident | None = get_incident(db, user, incident_id) if incident_id else None
    if conversation_id is not None:
        conversation = _conversation(db, user, conversation_id)
    else:
        conversation = AIConversation(
            user_id=user.id, incident_id=incident.id if incident else None, title=message[:120]
        )
        db.add(conversation)
        db.flush()

    history = [(item.role, item.content) for item in conversation.messages]
    previous_user = [content for role, content in history if role == "user"]
    # Error lines from an attached log describe the problem better than most summaries do.
    file_text = attachments.evidence(files)
    question = f"{message}\n{file_text}" if file_text else message
    retrieval_query, chunks = _chat_evidence(db, user, question, previous_user, incident)
    db.commit()
    result = generate_answer(retrieval_query, chunks, history)
    result.latency_ms = int((time.perf_counter() - started) * 1000)

    recommendation = _store(db, user, message, result, incident.id if incident else None)
    asked = AIMessage(conversation_id=conversation.id, role="user", content=message)
    db.add(asked)
    db.flush()
    attachments.link(files, asked)
    db.add(
        AIMessage(
            conversation_id=conversation.id,
            role="assistant",
            content=result.answer,
            recommendation_id=recommendation.id,
        )
    )
    related = _related(chunks) if is_staff(user) else []
    response = {
        **_response(db, user, result, recommendation, related),
        "conversation_id": conversation.id,
    }
    db.commit()
    return response


def list_conversations(db: Session, user: User) -> list[AIConversation]:
    return list(
        db.scalars(
            select(AIConversation).where(AIConversation.user_id == user.id).order_by(AIConversation.id.desc()).limit(50)
        )
    )


def conversation_detail(db: Session, user: User, conversation_id: int) -> dict:
    conversation = _conversation(db, user, conversation_id)
    return {
        "id": conversation.id,
        "title": conversation.title,
        "incident_id": conversation.incident_id,
        "created_at": conversation.created_at,
        "messages": [
            {
                "role": message.role,
                "content": message.content,
                "created_at": message.created_at,
                "citations": message.recommendation.citations if message.recommendation else [],
                "insufficient_evidence": bool(message.recommendation and message.recommendation.insufficient_evidence),
                "attachments": [
                    {field: getattr(item, field) for field in ("id", "kind", "filename", "content_type", "size_bytes")}
                    for item in message.attachments
                ],
            }
            for message in conversation.messages
        ],
    }
