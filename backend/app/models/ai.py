from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AccessLevel, DocumentSource, PredictionKind
from app.db.base import Base, CreatedAtMixin, str_enum

EMBEDDING_DIM = 384


class Prediction(Base, CreatedAtMixin):
    """Every model output shown to a user, so corrections can be measured against it."""

    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id"), index=True)
    kind: Mapped[PredictionKind] = mapped_column(str_enum(PredictionKind), index=True)
    model_version: Mapped[str] = mapped_column(String(64))
    value: Mapped[str] = mapped_column(String(100))
    confidence: Mapped[float] = mapped_column(Float)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    accepted: Mapped[bool | None] = mapped_column(Boolean)
    corrected_value: Mapped[str | None] = mapped_column(String(100))


class KnowledgeDocument(Base, CreatedAtMixin):
    __tablename__ = "knowledge_documents"
    __table_args__ = (UniqueConstraint("source_type", "source_ref"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[DocumentSource] = mapped_column(str_enum(DocumentSource))
    source_ref: Mapped[str] = mapped_column(String(100))
    title: Mapped[str] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(32), index=True)
    access_level: Mapped[AccessLevel] = mapped_column(str_enum(AccessLevel))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    content_hash: Mapped[str] = mapped_column(String(64))

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )


class KnowledgeChunk(Base, CreatedAtMixin):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
        Index(
            "ix_knowledge_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(EMBEDDING_DIM))
    # Instruction-like text. Stays retrievable for review but is never sent to the LLM.
    flagged_injection: Mapped[bool] = mapped_column(Boolean, default=False)

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")


class AIRecommendation(Base, CreatedAtMixin):
    """One generated answer, with enough detail to evaluate grounding later."""

    __tablename__ = "ai_recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    query: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    insufficient_evidence: Mapped[bool] = mapped_column(Boolean, default=False)
    provider: Mapped[str] = mapped_column(String(64))
    latency_ms: Mapped[int] = mapped_column(Integer)
    helpful: Mapped[bool | None] = mapped_column(Boolean)


class AIConversation(Base, CreatedAtMixin):
    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"))
    title: Mapped[str] = mapped_column(String(120))

    messages: Mapped[list["AIMessage"]] = relationship(
        back_populates="conversation", order_by="AIMessage.id", cascade="all, delete-orphan"
    )


class AIMessage(Base, CreatedAtMixin):
    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("ai_conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    recommendation_id: Mapped[int | None] = mapped_column(ForeignKey("ai_recommendations.id"))

    conversation: Mapped[AIConversation] = relationship(back_populates="messages")
    recommendation: Mapped[AIRecommendation | None] = relationship()
