from enum import StrEnum


class Role(StrEnum):
    REQUESTER = "requester"
    AGENT = "agent"
    MANAGER = "manager"
    ADMIN = "admin"


class Category(StrEnum):
    NETWORK = "network"
    ACCESS = "access_identity"
    HARDWARE = "hardware"
    SOFTWARE = "software_application"
    DATABASE = "database"
    CLOUD = "cloud_infrastructure"
    SECURITY = "security"
    EMAIL = "email_collaboration"


class Level(StrEnum):
    """Shared scale for impact and urgency."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Priority(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class Status(StrEnum):
    NEW = "new"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    ON_HOLD = "on_hold"
    RESOLVED = "resolved"
    CLOSED = "closed"


class Channel(StrEnum):
    PORTAL = "portal"
    EMAIL = "email"
    PHONE = "phone"
    MONITORING = "monitoring"


class AccessLevel(StrEnum):
    PUBLIC = "public"  # every authenticated user
    INTERNAL = "internal"  # support staff
    RESTRICTED = "restricted"  # members of the owning team, managers and admins


class DocumentSource(StrEnum):
    KB_ARTICLE = "kb_article"
    RESOLVED_INCIDENT = "resolved_incident"


class PredictionKind(StrEnum):
    CATEGORY = "category"
    SLA_RISK = "sla_risk"
    ROUTING = "routing"


class RemediationStatus(StrEnum):
    PENDING = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class NotificationType(StrEnum):
    ASSIGNED = "assigned"
    STATUS_CHANGED = "status_changed"
    COMMENT = "comment"
    SLA_RISK = "sla_risk"
    SLA_BREACH = "sla_breach"
    ESCALATED = "escalated"
    APPROVAL_REQUIRED = "approval_required"
    REMEDIATION_RESULT = "remediation_result"


STAFF_ROLES = (Role.AGENT, Role.MANAGER, Role.ADMIN)
PRIVILEGED_ROLES = (Role.MANAGER, Role.ADMIN)
OPEN_STATUSES = (Status.NEW, Status.ASSIGNED, Status.IN_PROGRESS, Status.ON_HOLD)

ALLOWED_TRANSITIONS: dict[Status, frozenset[Status]] = {
    Status.NEW: frozenset({Status.ASSIGNED, Status.IN_PROGRESS, Status.RESOLVED}),
    Status.ASSIGNED: frozenset({Status.IN_PROGRESS, Status.ON_HOLD, Status.RESOLVED}),
    Status.IN_PROGRESS: frozenset({Status.ON_HOLD, Status.RESOLVED}),
    Status.ON_HOLD: frozenset({Status.IN_PROGRESS, Status.RESOLVED}),
    Status.RESOLVED: frozenset({Status.IN_PROGRESS, Status.CLOSED}),
    Status.CLOSED: frozenset(),
}

_PRIORITY_MATRIX = {
    (Level.HIGH, Level.HIGH): Priority.P1,
    (Level.HIGH, Level.MEDIUM): Priority.P2,
    (Level.MEDIUM, Level.HIGH): Priority.P2,
    (Level.HIGH, Level.LOW): Priority.P3,
    (Level.LOW, Level.HIGH): Priority.P3,
    (Level.MEDIUM, Level.MEDIUM): Priority.P3,
    (Level.MEDIUM, Level.LOW): Priority.P4,
    (Level.LOW, Level.MEDIUM): Priority.P4,
    (Level.LOW, Level.LOW): Priority.P4,
}


def compute_priority(impact: Level, urgency: Level) -> Priority:
    """ITIL impact/urgency matrix. Priority is always derived, never set directly."""
    return _PRIORITY_MATRIX[(impact, urgency)]
