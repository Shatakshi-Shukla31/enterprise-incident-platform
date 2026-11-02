from dataclasses import asdict, dataclass

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import KnowledgeChunk, KnowledgeDocument, User
from app.rag.embeddings import get_embedder
from app.services.access import scope_documents

MAX_CHUNKS_PER_DOCUMENT = 2


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: int
    document_id: int
    title: str
    source_type: str
    source_ref: str
    category: str | None
    similarity: float
    content: str

    def as_dict(self) -> dict:
        return asdict(self)


def retrieve(
    db: Session,
    user: User,
    query: str,
    top_k: int | None = None,
    category: str | None = None,
    source_type: str | None = None,
    exclude_refs: tuple[str, ...] = (),
) -> list[RetrievedChunk]:
    """Similarity search limited to documents `user` is allowed to read.

    The access filter is part of the SQL statement, so restricted text is never loaded,
    and chunks quarantined at ingestion are excluded here.
    """
    settings = get_settings()
    top_k = top_k or settings.rag_top_k
    vector = get_embedder().embed([query])[0]
    distance = KnowledgeChunk.embedding.cosine_distance(vector).label("distance")

    # Filtering after an HNSW scan can return too few rows. Iterative scanning keeps
    # reading the index until enough rows have passed the filters.
    db.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))

    stmt = (
        select(KnowledgeChunk, KnowledgeDocument, distance)
        .join(KnowledgeDocument)
        .where(KnowledgeChunk.flagged_injection.is_(False))
    )
    stmt = scope_documents(stmt, user)
    if category:
        stmt = stmt.where(KnowledgeDocument.category == category)
    if source_type:
        stmt = stmt.where(KnowledgeDocument.source_type == source_type)
    if exclude_refs:
        stmt = stmt.where(KnowledgeDocument.source_ref.not_in(exclude_refs))

    rows = db.execute(stmt.order_by(distance).limit(max(settings.rag_candidate_k, top_k))).all()

    per_document: dict[int, int] = {}
    results: list[RetrievedChunk] = []
    for chunk, document, chunk_distance in rows:
        seen = per_document.get(document.id, 0)
        if seen >= MAX_CHUNKS_PER_DOCUMENT:
            continue
        per_document[document.id] = seen + 1
        results.append(
            RetrievedChunk(
                chunk_id=chunk.id,
                document_id=document.id,
                title=document.title,
                source_type=str(document.source_type),
                source_ref=document.source_ref,
                category=document.category,
                similarity=round(1 - float(chunk_distance), 4),
                content=chunk.content,
            )
        )
        if len(results) == top_k:
            break
    return results
