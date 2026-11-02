"""SLA model features. Training and inference both go through this module, so they cannot
disagree, and every feature here must be known at the moment an incident is created."""

from datetime import datetime

import pandas as pd

CATEGORICAL_FEATURES = ["category", "priority", "impact", "urgency", "channel", "team"]
NUMERIC_FEATURES = [
    "hour",
    "day_of_week",
    "is_weekend",
    "is_after_hours",
    "description_length",
    "team_backlog",
    "team_backlog_high",
]
SLA_FEATURES = CATEGORICAL_FEATURES + NUMERIC_FEATURES

# Outcomes and values only known after the incident progresses. Using any of these would
# inflate offline metrics and fail in production. Enforced at train time and by a test.
FORBIDDEN_FEATURES = frozenset(
    {
        "resolved_at",
        "closed_at",
        "resolution_minutes",
        "resolution_notes",
        "first_response_at",
        "status",
        "assignee_id",
        "escalation_level",
        "sla_breached",
        "sla_breached_at",
        "topic",
        "reassignment_count",
    }
)


def _time_features(created_at: datetime) -> dict[str, int]:
    weekend = created_at.weekday() >= 5
    return {
        "hour": created_at.hour,
        "day_of_week": created_at.weekday(),
        "is_weekend": int(weekend),
        "is_after_hours": int(weekend or not 8 <= created_at.hour < 18),
    }


def incident_features(
    *,
    category: str | None,
    priority: str,
    impact: str,
    urgency: str,
    channel: str,
    team: str | None,
    created_at: datetime,
    description_length: int,
    team_backlog: int,
    team_backlog_high: int,
) -> dict[str, object]:
    return {
        "category": str(category) if category else "unknown",
        "priority": str(priority),
        "impact": str(impact),
        "urgency": str(urgency),
        "channel": str(channel),
        "team": team or "unassigned",
        **_time_features(created_at),
        "description_length": description_length,
        "team_backlog": team_backlog,
        "team_backlog_high": team_backlog_high,
    }


def build_sla_frame(history: pd.DataFrame) -> pd.DataFrame:
    rows = [
        incident_features(
            category=row.category,
            priority=row.priority,
            impact=row.impact,
            urgency=row.urgency,
            channel=row.channel,
            team=row.team,
            created_at=row.created_at,
            description_length=len(row.description),
            team_backlog=row.team_backlog,
            team_backlog_high=row.team_backlog_high,
        )
        for row in history.itertuples()
    ]
    return pd.DataFrame(rows, columns=SLA_FEATURES, index=history.index)
