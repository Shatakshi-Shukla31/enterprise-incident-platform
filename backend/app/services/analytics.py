"""Dashboard figures. Everything is computed from stored records; offline model metrics are
read from the registry's metadata, so nothing here can drift from what training reported."""

from datetime import timedelta

from sqlalchemy import Float, Integer, case, cast, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import OPEN_STATUSES, PredictionKind, Status
from app.db.base import utcnow
from app.ml import registry
from app.models import AIRecommendation, Incident, Prediction, Team


def _rate(numerator: int | None, denominator: int | None) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def dashboard(db: Session, days: int) -> dict:
    since = utcnow() - timedelta(days=days)
    return {
        "days": days,
        "summary": _summary(db, since),
        "trend": _trend(db, since),
        "by_category": _by_category(db, since),
        "sla_by_priority": _sla_by_priority(db, since),
        "resolution_by_team": _resolution_by_team(db, since),
        "ml_live": _ml_live(db, since),
        "ml_offline": _ml_offline(),
        "ai_usage": _ai_usage(db, since),
    }


def _resolution_hours():
    return func.extract("epoch", Incident.resolved_at - Incident.created_at) / 3600


def _summary(db: Session, since) -> dict:
    created, resolved, breached_resolved, mean_hours = db.execute(
        select(
            func.count(),
            func.count(Incident.resolved_at),
            func.count().filter(Incident.resolved_at.is_not(None), Incident.sla_breached),
            func.avg(_resolution_hours()),
        ).where(Incident.created_at >= since)
    ).one()
    open_now, overdue, high_risk = db.execute(
        select(
            func.count(),
            func.count().filter(Incident.sla_breached),
            func.count().filter(Incident.sla_risk_score >= get_settings().sla_risk_alert_threshold),
        ).where(Incident.status.in_(OPEN_STATUSES))
    ).one()
    return {
        "created": created,
        "resolved": resolved,
        "open_now": open_now,
        "open_breached": overdue,
        "open_high_risk": high_risk,
        "sla_compliance": _rate(resolved - breached_resolved, resolved),
        "mean_resolution_hours": round(float(mean_hours), 2) if mean_hours is not None else None,
    }


def _trend(db: Session, since) -> list[dict]:
    created_day = func.date_trunc("day", Incident.created_at, "UTC")
    resolved_day = func.date_trunc("day", Incident.resolved_at, "UTC")
    created = dict(
        db.execute(select(created_day, func.count()).where(Incident.created_at >= since).group_by(created_day)).all()
    )
    resolved = dict(
        db.execute(select(resolved_day, func.count()).where(Incident.resolved_at >= since).group_by(resolved_day)).all()
    )
    return [
        {"date": day.date().isoformat(), "created": created.get(day, 0), "resolved": resolved.get(day, 0)}
        for day in sorted(set(created) | set(resolved))
    ]


def _by_category(db: Session, since) -> list[dict]:
    rows = db.execute(
        select(Incident.category, func.count())
        .where(Incident.created_at >= since)
        .group_by(Incident.category)
        .order_by(func.count().desc())
    ).all()
    return [{"category": category or "untriaged", "count": count} for category, count in rows]


def _sla_by_priority(db: Session, since) -> list[dict]:
    rows = db.execute(
        select(
            Incident.priority,
            func.count(),
            func.count().filter(Incident.sla_breached),
        )
        .where(Incident.created_at >= since, Incident.resolved_at.is_not(None))
        .group_by(Incident.priority)
        .order_by(Incident.priority)
    ).all()
    return [
        {"priority": priority, "resolved": total, "breached": breached, "compliance": _rate(total - breached, total)}
        for priority, total, breached in rows
    ]


def _resolution_by_team(db: Session, since) -> list[dict]:
    rows = db.execute(
        select(Team.name, func.count(), func.avg(_resolution_hours()))
        .join(Team, Incident.team_id == Team.id)
        .where(Incident.created_at >= since, Incident.resolved_at.is_not(None))
        .group_by(Team.name)
        .order_by(Team.name)
    ).all()
    return [{"team": name, "resolved": total, "mean_hours": round(float(hours), 2)} for name, total, hours in rows]


def _ml_live(db: Session, since) -> dict:
    """How predictions fared against what support staff decided."""
    rows = db.execute(
        select(
            Prediction.kind,
            func.count(),
            func.count(Prediction.accepted),
            func.count().filter(Prediction.accepted.is_(True)),
            func.avg(Prediction.confidence),
        )
        .where(Prediction.created_at >= since)
        .group_by(Prediction.kind)
    ).all()
    output = {
        kind: {
            "predictions": total,
            "reviewed": reviewed,
            "acceptance_rate": _rate(accepted, reviewed),
            "mean_confidence": round(float(confidence), 4),
        }
        for kind, total, reviewed, accepted, confidence in rows
    }
    breach_label = cast(Incident.sla_breached, Integer)
    high_risk = case((Incident.sla_risk_score >= 0.5, 1), else_=0)
    risk_rows = db.execute(
        select(high_risk, func.count(), func.avg(cast(breach_label, Float)))
        .where(
            Incident.created_at >= since,
            Incident.status.in_((Status.RESOLVED, Status.CLOSED)),
            Incident.sla_risk_score.is_not(None),
        )
        .group_by(high_risk)
    ).all()
    output[PredictionKind.SLA_RISK.value + "_outcomes"] = [
        {
            "bucket": "risk >= 50%" if bucket else "risk < 50%",
            "incidents": count,
            "observed_breach_rate": round(float(rate), 4),
        }
        for bucket, count, rate in risk_rows
    ]
    return output


def _ml_offline() -> dict:
    root = get_settings().artifacts_dir
    output = {}
    for kind in ("category", "routing", "sla_risk"):
        metadata = registry.load_metadata(root, kind)
        if metadata is None:
            output[kind] = None
            continue
        test = dict(metadata["metrics"]["test"])
        test.pop("calibration_bins", None)
        output[kind] = {
            "version": metadata["version"],
            "selected_model": metadata["selected_model"],
            "synthetic_data": metadata["data"]["synthetic"],
            "test": test,
        }
    return output


def _ai_usage(db: Session, since) -> dict:
    total, insufficient, rated, helpful, latency = db.execute(
        select(
            func.count(),
            func.count().filter(AIRecommendation.insufficient_evidence),
            func.count(AIRecommendation.helpful),
            func.count().filter(AIRecommendation.helpful.is_(True)),
            func.percentile_cont(0.95).within_group(AIRecommendation.latency_ms),
        ).where(AIRecommendation.created_at >= since)
    ).one()
    return {
        "recommendations": total,
        "insufficient_evidence_rate": _rate(insufficient, total),
        "rated": rated,
        "helpful_rate": _rate(helpful, rated),
        "p95_latency_ms": round(float(latency)) if latency is not None else None,
    }
