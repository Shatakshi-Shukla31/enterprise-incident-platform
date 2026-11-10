from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request, Response, UploadFile, status
from sqlalchemy import select

from app.api.deps import DB, AdminUser, CurrentUser, ManagerUser, Paging, StaffUser
from app.api.rate_limit import limiter
from app.core.config import get_settings
from app.models import AIRecommendation, KnowledgeDocument, Team
from app.rag import ingest, retriever
from app.rag import service as rag_service
from app.schemas.api import (
    AttachmentOut,
    ChatRequest,
    ChatResponse,
    ConversationDetail,
    ConversationOut,
    FeedbackIn,
    IngestResult,
    KnowledgeDocumentCreate,
    KnowledgeDocumentOut,
    SearchHit,
    SearchRequest,
)
from app.services import access, attachments, audit

router = APIRouter(tags=["ai"])
settings = get_settings()


@router.post("/ai/chat", response_model=ChatResponse)
@limiter.limit(settings.rate_limit_ai)
def chat(request: Request, payload: ChatRequest, user: CurrentUser, db: DB) -> dict:
    return rag_service.chat(
        db, user, payload.message, payload.conversation_id, payload.incident_id, payload.attachment_ids
    )


@router.post("/ai/attachments", response_model=AttachmentOut, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.rate_limit_upload)
def upload_attachment(request: Request, file: UploadFile, user: CurrentUser, db: DB) -> object:
    # Read one byte past the limit, so an oversized file is refused without reading it all.
    data = file.file.read(attachments.MAX_BYTES + 1)
    return attachments.save(db, user, file.filename or "attachment", data)


@router.get("/ai/attachments/{attachment_id}")
def download_attachment(attachment_id: int, user: CurrentUser, db: DB) -> Response:
    item = attachments.for_download(db, user, attachment_id)
    # Images, audio and video play in the page. Anything else downloads, so a browser never
    # renders it as a page from this site.
    disposition = "inline" if item.kind in ("image", "audio", "video") else "attachment"
    return Response(
        item.data,
        media_type=item.content_type,
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(item.filename)}",
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/ai/conversations", response_model=list[ConversationOut])
def conversations(user: CurrentUser, db: DB) -> list:
    return rag_service.list_conversations(db, user)


@router.get("/ai/conversations/{conversation_id}", response_model=ConversationDetail)
def conversation(conversation_id: int, user: CurrentUser, db: DB) -> dict:
    return rag_service.conversation_detail(db, user, conversation_id)


@router.post("/ai/recommendations/{recommendation_id}/feedback", status_code=status.HTTP_204_NO_CONTENT)
def feedback(recommendation_id: int, payload: FeedbackIn, user: CurrentUser, db: DB) -> None:
    recommendation = db.get(AIRecommendation, recommendation_id)
    if recommendation is None or recommendation.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recommendation not found")
    recommendation.helpful = payload.helpful
    db.commit()


@router.get("/knowledge/documents", response_model=list[KnowledgeDocumentOut])
def list_documents(user: StaffUser, db: DB, paging: Paging) -> list:
    stmt = access.scope_documents(select(KnowledgeDocument), user)
    return list(db.scalars(stmt.order_by(KnowledgeDocument.id.desc()).offset(paging.offset).limit(paging.page_size)))


@router.post("/knowledge/documents", response_model=IngestResult, status_code=status.HTTP_201_CREATED)
def create_document(payload: KnowledgeDocumentCreate, manager: ManagerUser, db: DB) -> dict:
    if payload.team_id is not None and db.get(Team, payload.team_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown team")
    result = ingest.ingest_article(
        db,
        source_ref=payload.source_ref,
        title=payload.title,
        content=payload.content,
        category=payload.category,
        access_level=payload.access_level,
        team_id=payload.team_id,
    )
    audit.record(db, "knowledge.ingested", manager, source_ref=payload.source_ref, flagged=result["flagged_chunks"])
    db.commit()
    return result


@router.delete("/knowledge/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: int, admin: AdminUser, db: DB) -> None:
    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    audit.record(db, "knowledge.deleted", admin, source_ref=document.source_ref)
    db.delete(document)
    db.commit()


@router.post("/knowledge/search", response_model=list[SearchHit])
@limiter.limit(settings.rate_limit_ai)
def search(request: Request, payload: SearchRequest, user: CurrentUser, db: DB) -> list:
    hits = retriever.retrieve(
        db,
        user,
        payload.query,
        top_k=payload.top_k,
        category=payload.category,
        source_type=payload.source_type,
    )
    return [SearchHit(**hit.as_dict()) for hit in hits]
