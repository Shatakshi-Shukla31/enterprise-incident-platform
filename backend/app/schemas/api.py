from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.core.enums import (
    AccessLevel,
    Category,
    Channel,
    Level,
    NotificationType,
    Priority,
    RemediationStatus,
    Role,
    Status,
)

Title = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=200)]
LongText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=10000)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
Password = Annotated[str, StringConstraints(min_length=12, max_length=128)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TeamOut(ORMModel):
    id: int
    name: str
    description: str
    is_active: bool


class TeamCreate(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=100)]
    description: str = ""


class UserOut(ORMModel):
    id: int
    email: str
    full_name: str
    role: Role
    team_id: int | None
    is_active: bool


class UserCreate(BaseModel):
    email: EmailStr
    full_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
    password: Password
    role: Role = Role.REQUESTER
    team_id: int | None = None


class Registration(BaseModel):
    """Has no role field on purpose: the server decides the role."""

    email: EmailStr
    full_name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
    password: Password
    admin_code: str | None = Field(None, max_length=200)


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=120)
    role: Role | None = None
    team_id: int | None = None
    is_active: bool | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: Password


class PersonRef(ORMModel):
    id: int
    full_name: str


class TeamRef(ORMModel):
    id: int
    name: str


class IncidentCreate(BaseModel):
    title: Title
    description: LongText
    impact: Level = Level.MEDIUM
    urgency: Level = Level.MEDIUM
    channel: Channel = Channel.PORTAL


class IncidentUpdate(BaseModel):
    title: Title | None = None
    description: LongText | None = None
    impact: Level | None = None
    urgency: Level | None = None


class StatusChange(BaseModel):
    status: Status
    resolution_notes: str | None = Field(None, max_length=5000)


class Assignment(BaseModel):
    team_id: int | None = None
    assignee_id: int | None = None


class Escalation(BaseModel):
    reason: ShortText


class CategoryCorrection(BaseModel):
    category: Category


class IncidentOut(ORMModel):
    id: int
    number: str
    title: str
    description: str
    impact: Level
    urgency: Level
    priority: Priority
    status: Status
    channel: Channel
    category: Category | None
    requester: PersonRef
    assignee: PersonRef | None
    team: TeamRef | None
    created_at: datetime
    updated_at: datetime
    response_due_at: datetime
    resolution_due_at: datetime
    first_response_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    sla_breached: bool
    escalation_level: int
    resolution_notes: str | None
    # Staff only: blanked for requesters by the API layer.
    category_confidence: float | None = None
    category_corrected: bool = False
    sla_risk_score: float | None = None


class CommentCreate(BaseModel):
    body: ShortText
    is_internal: bool = False


class CommentOut(ORMModel):
    id: int
    body: str
    is_internal: bool
    created_at: datetime
    author: PersonRef


class AuditOut(ORMModel):
    id: int
    action: str
    changes: dict
    created_at: datetime
    actor: PersonRef | None


class PredictionOut(ORMModel):
    id: int
    kind: str
    model_version: str
    value: str
    confidence: float
    details: dict
    accepted: bool | None
    corrected_value: str | None
    created_at: datetime


class NotificationOut(ORMModel):
    id: int
    incident_id: int | None
    type: NotificationType
    title: str
    body: str
    created_at: datetime
    read_at: datetime | None


class NotificationCount(BaseModel):
    key: str
    unread: int
    read: int


class NotificationSummary(BaseModel):
    total: int
    unread: int
    by_type: list[NotificationCount]
    by_status: list[NotificationCount]


class RunbookOut(ORMModel):
    id: int
    key: str
    name: str
    description: str
    category: str | None


class RemediationCreate(BaseModel):
    runbook_id: int
    target: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    justification: Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2000)]


class RemediationDecision(BaseModel):
    approve: bool
    note: str | None = Field(None, max_length=2000)


class RemediationOut(ORMModel):
    id: int
    incident_id: int
    status: RemediationStatus
    target: str
    justification: str
    decision_note: str | None
    result: dict
    created_at: datetime
    decided_at: datetime | None
    finished_at: datetime | None
    runbook: RunbookOut
    requested_by: PersonRef
    decided_by: PersonRef | None


class Citation(BaseModel):
    id: str
    document_id: int
    chunk_id: int
    title: str
    source_type: str
    source_ref: str
    similarity: float
    excerpt: str


class RelatedIncident(BaseModel):
    incident_id: int | None
    source_ref: str
    title: str
    similarity: float


class SuggestedAction(BaseModel):
    runbook_id: int
    name: str
    description: str
    requires_approval: bool = True


class AnswerOut(BaseModel):
    recommendation_id: int
    answer: str
    citations: list[Citation]
    insufficient_evidence: bool
    provider: str
    latency_ms: int
    related_incidents: list[RelatedIncident] = []
    suggested_actions: list[SuggestedAction] = []


class ChatRequest(BaseModel):
    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=2000)]
    conversation_id: int | None = None
    incident_id: int | None = None


class ChatResponse(AnswerOut):
    conversation_id: int


class ChatMessageOut(BaseModel):
    role: str
    content: str
    created_at: datetime
    citations: list[Citation] = []
    insufficient_evidence: bool = False


class ConversationOut(ORMModel):
    id: int
    title: str
    incident_id: int | None
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[ChatMessageOut]


class FeedbackIn(BaseModel):
    helpful: bool


class KnowledgeDocumentOut(ORMModel):
    id: int
    source_type: str
    source_ref: str
    title: str
    category: str | None
    access_level: AccessLevel
    team_id: int | None
    created_at: datetime


class KnowledgeDocumentCreate(BaseModel):
    source_ref: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._-]{2,100}$")]
    title: Title
    content: Annotated[str, StringConstraints(strip_whitespace=True, min_length=20, max_length=100000)]
    category: Category | None = None
    access_level: AccessLevel = AccessLevel.INTERNAL
    team_id: int | None = None


class IngestResult(BaseModel):
    document_id: int
    chunks: int
    flagged_chunks: int
    unchanged: bool


class SearchRequest(BaseModel):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=2000)]
    top_k: int = Field(5, ge=1, le=20)
    category: Category | None = None
    source_type: str | None = None


class SearchHit(BaseModel):
    chunk_id: int
    document_id: int
    title: str
    source_type: str
    source_ref: str
    category: str | None
    similarity: float
    content: str
