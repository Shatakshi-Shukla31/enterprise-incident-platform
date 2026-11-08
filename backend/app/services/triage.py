"""Applies ML predictions to incidents. If a model is unavailable the incident simply
stays untriaged: ticket creation must never depend on ML being healthy."""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import Category, PredictionKind
from app.db.base import utcnow
from app.ml import inference
from app.ml.features import incident_features
from app.models import Incident, Prediction, Team
from app.services import audit, sla

logger = logging.getLogger(__name__)

# Below this the ticket goes to manual triage instead of being routed automatically.
AUTO_ROUTE_MIN_CONFIDENCE = 0.6


def incident_text(incident: Incident) -> str:
    return f"{incident.title}\n{incident.description}"


def triage_incident(db: Session, incident: Incident) -> None:
    classify(db, incident)
    route(db, incident)
    score_sla_risk(db, incident)


def classify(db: Session, incident: Incident) -> None:
    try:
        result = inference.predict_category(incident_text(incident))
    except Exception:
        logger.exception("Classification failed", extra={"incident_id": incident.id})
        return
    if result is None:
        return
    incident.category = Category(result.label)
    incident.category_confidence = result.confidence
    db.add(
        Prediction(
            incident_id=incident.id,
            kind=PredictionKind.CATEGORY,
            model_version=result.version,
            value=result.label,
            confidence=result.confidence,
            details={"alternatives": result.alternatives},
        )
    )


def route(db: Session, incident: Incident) -> None:
    try:
        result = inference.recommend_team(incident_text(incident))
    except Exception:
        logger.exception("Routing failed", extra={"incident_id": incident.id})
        return
    if result is None:
        return
    db.add(
        Prediction(
            incident_id=incident.id,
            kind=PredictionKind.ROUTING,
            model_version=result.version,
            value=result.label,
            confidence=result.confidence,
            details={"alternatives": result.alternatives},
        )
    )
    if result.confidence >= AUTO_ROUTE_MIN_CONFIDENCE and incident.team_id is None:
        team = db.scalar(select(Team).where(Team.name == result.label, Team.is_active.is_(True)))
        if team is not None:
            incident.team_id = team.id
            audit.record(
                db,
                "incident.auto_routed",
                None,
                incident.id,
                team=team.name,
                confidence=round(result.confidence, 3),
                model_version=result.version,
            )


def record_routing_outcome(db: Session, incident: Incident) -> None:
    """Compare the human routing decision with the stored recommendation."""
    prediction = db.scalar(
        select(Prediction)
        .where(Prediction.incident_id == incident.id, Prediction.kind == PredictionKind.ROUTING)
        .order_by(Prediction.id.desc())
    )
    if prediction is None or incident.team_id is None:
        return
    team = db.get(Team, incident.team_id)
    prediction.accepted = team is not None and team.name == prediction.value
    prediction.corrected_value = None if prediction.accepted else (team.name if team else None)


def score_sla_risk(db: Session, incident: Incident, historical_backlog: tuple[int, int] | None = None) -> None:
    """Pass `historical_backlog` when scoring a past ticket, whose queue no longer exists."""
    now = utcnow()
    backlog, backlog_high = historical_backlog or sla.team_backlog(db, incident.team_id, before=incident.created_at)
    team = db.get(Team, incident.team_id) if incident.team_id else None
    features = incident_features(
        category=incident.category,
        priority=incident.priority,
        impact=incident.impact,
        urgency=incident.urgency,
        channel=incident.channel,
        team=team.name if team else None,
        created_at=incident.created_at,
        description_length=len(incident.description),
        team_backlog=backlog,
        team_backlog_high=backlog_high,
    )
    try:
        result = inference.predict_sla_risk(features)
        factors = inference.explain_sla_risk(features) if result else []
    except Exception:
        logger.exception("SLA scoring failed", extra={"incident_id": incident.id})
        return
    if result is None:
        return
    incident.sla_risk_score = result.confidence
    incident.sla_risk_scored_at = now
    db.add(
        Prediction(
            incident_id=incident.id,
            kind=PredictionKind.SLA_RISK,
            model_version=result.version,
            value="breach_risk",
            confidence=result.confidence,
            details={"features": features, "factors": factors},
        )
    )
