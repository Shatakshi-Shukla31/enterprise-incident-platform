"""Runtime predictions. Functions return None when no trained model exists."""

import logging
import threading
from dataclasses import dataclass

import pandas as pd

from app.core.config import get_settings
from app.ml import registry
from app.ml.features import EXPLANATION_GROUPS, SLA_FEATURES

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: dict[str, registry.LoadedModel | None] = {}


@dataclass(frozen=True)
class Prediction:
    label: str
    confidence: float
    version: str
    alternatives: list[dict]


def _get(kind: str) -> registry.LoadedModel | None:
    with _lock:
        if kind not in _cache or _cache[kind] is None:
            _cache[kind] = registry.load_model(get_settings().artifacts_dir, kind)
            if _cache[kind] is None:
                logger.warning("No trained %s model; run python -m app.ml.train", kind)
        return _cache[kind]


def reload_models() -> None:
    with _lock:
        _cache.clear()


def status() -> dict[str, str | None]:
    root = get_settings().artifacts_dir
    versions = {}
    for kind in ("category", "routing", "sla_risk"):
        metadata = registry.load_metadata(root, kind)
        versions[kind] = metadata["version"] if metadata else None
    return versions


def _rank_text_model(kind: str, text: str, top: int = 3) -> Prediction | None:
    loaded = _get(kind)
    if loaded is None:
        return None
    probabilities = loaded.model.predict_proba([text])[0]
    ranked = sorted(zip(loaded.model.classes_, probabilities, strict=True), key=lambda p: p[1], reverse=True)
    best_label, best_score = ranked[0]
    return Prediction(
        label=str(best_label),
        confidence=round(float(best_score), 4),
        version=loaded.version,
        alternatives=[{"label": str(label), "confidence": round(float(score), 4)} for label, score in ranked[:top]],
    )


def predict_category(text: str) -> Prediction | None:
    return _rank_text_model("category", text)


def recommend_team(text: str) -> Prediction | None:
    return _rank_text_model("routing", text)


def predict_sla_risk(features: dict[str, object]) -> Prediction | None:
    loaded = _get("sla_risk")
    if loaded is None:
        return None
    frame = pd.DataFrame([features], columns=SLA_FEATURES)
    risk = float(loaded.model.predict_proba(frame)[0, 1])
    return Prediction("breach_risk", round(risk, 4), loaded.version, [])


def explain_sla_risk(features: dict[str, object], top: int = 3) -> list[dict]:
    """What moved a score: each group of facts is swapped for a typical ticket's values and
    the ticket is scored again. A positive effect means that group raised the risk. This
    works for any model, and explains the model's behaviour, not the real world's."""
    loaded = _get("sla_risk")
    reference = loaded.metadata.get("reference") if loaded else None
    if not reference:
        return []
    rows = [features] + [
        {**features, **{column: reference[column] for column in columns}} for columns in EXPLANATION_GROUPS.values()
    ]
    risks = loaded.model.predict_proba(pd.DataFrame(rows, columns=SLA_FEATURES))[:, 1]
    effects = [
        {"factor": name, "effect": round(float(risks[0] - risks[index]), 4)}
        for index, name in enumerate(EXPLANATION_GROUPS, start=1)
    ]
    effects = [item for item in effects if abs(item["effect"]) >= 0.01]
    return sorted(effects, key=lambda item: abs(item["effect"]), reverse=True)[:top]
