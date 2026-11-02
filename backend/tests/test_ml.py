from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from app.core.config import get_settings
from app.ml import evaluation, inference, registry
from app.ml.features import FORBIDDEN_FEATURES, SLA_FEATURES, build_sla_frame, incident_features
from app.ml.synthetic import generate
from app.ml.train import inspect_dataset, prepare_text_data, purge_before, sla_splits, time_split, train_sla


@pytest.fixture(scope="module")
def history():
    return generate(days=120, daily_mean=20, seed=3)


def test_generator_is_deterministic():
    first = generate(days=20, daily_mean=10, seed=1)
    second = generate(days=20, daily_mean=10, seed=1)
    pd.testing.assert_frame_equal(first, second)
    assert not first.equals(generate(days=20, daily_mean=10, seed=2))


def test_generated_outcomes_are_uncertain(history):
    assert 0.05 < history["sla_breached"].mean() < 0.6
    assert history["category"].nunique() == 8


def test_backlog_only_counts_tickets_opened_earlier(history):
    # The first ticket for a team must see an empty queue.
    assert (history.groupby("team")["team_backlog"].first() == 0).all()


def test_no_feature_is_known_only_after_the_fact():
    assert not FORBIDDEN_FEATURES & set(SLA_FEATURES)


def test_training_refuses_a_leaky_feature(history, monkeypatch, tmp_path):
    from app.ml import train

    monkeypatch.setattr(train, "SLA_FEATURES", [*SLA_FEATURES, "resolution_minutes"])
    with pytest.raises(ValueError, match="leakage"):
        train_sla(history, "x", 1, tmp_path)


def test_outcome_columns_are_not_in_the_feature_frame(history):
    frame = build_sla_frame(history.head(5))
    assert "sla_breached" not in frame.columns
    assert "resolution_minutes" not in frame.columns
    assert list(frame.columns) == SLA_FEATURES


def test_changing_the_outcome_does_not_change_features(history):
    sample = history.head(30)
    altered = sample.assign(
        sla_breached=1 - sample["sla_breached"], resolution_minutes=0, resolved_at=sample["created_at"]
    )
    pd.testing.assert_frame_equal(build_sla_frame(sample), build_sla_frame(altered))


def test_sla_splits_are_ordered_in_time(history):
    train, validation, calibration, test = sla_splits(history)
    assert train["created_at"].max() < validation["created_at"].min()
    assert validation["created_at"].max() < calibration["created_at"].min()
    assert calibration["created_at"].max() < test["created_at"].min()


def test_training_labels_were_known_before_the_next_split(history):
    train, validation, _, _ = sla_splits(history)
    assert train["resolved_at"].max() < validation["created_at"].min() or (
        train["resolved_at"].max() < history.sort_values("created_at").iloc[int(len(history) * 0.6)]["created_at"]
    )


def test_purging_does_not_distort_the_breach_rate(history):
    """Dropping only late resolvers would remove mostly breaches and flatter the label."""
    ordered = history.sort_values("created_at").reset_index(drop=True)
    part, next_part = ordered.iloc[: len(ordered) // 2], ordered.iloc[len(ordered) // 2 :]
    purged = purge_before(part, next_part["created_at"].min())
    assert purged["resolved_at"].max() < next_part["created_at"].min()
    assert abs(purged["sla_breached"].mean() - part["sla_breached"].mean()) < 0.05


def test_duplicates_are_removed_before_splitting():
    frame = pd.DataFrame(
        {
            "created_at": pd.date_range("2026-01-01", periods=4, tz="UTC"),
            "title": ["VPN down", "vpn   DOWN!", "Printer jam", "Disk full"],
            "description": ["no tunnel", "no tunnel", "paper", "volume"],
        }
    )
    assert len(prepare_text_data(frame)) == 3


def test_no_text_appears_in_both_train_and_test(history):
    frame = prepare_text_data(history)
    train, _, test = time_split(frame, 0.7, 0.15)
    assert not set(train["normalised"]) & set(test["normalised"])


def test_dataset_inspection_finds_duplicates(history):
    report = inspect_dataset(history)
    assert report["rows"] == len(history)
    assert report["exact_duplicate_text_rows"] > 0


def test_feature_function_matches_at_train_and_serve_time():
    created = datetime(2026, 3, 7, 22, 0, tzinfo=UTC)  # a Saturday night
    features = incident_features(
        category=None,
        priority="P2",
        impact="high",
        urgency="medium",
        channel="email",
        team=None,
        created_at=created,
        description_length=50,
        team_backlog=3,
        team_backlog_high=1,
    )
    assert features["is_weekend"] == 1
    assert features["is_after_hours"] == 1
    assert features["category"] == "unknown"
    assert features["team"] == "unassigned"
    assert set(features) == set(SLA_FEATURES)


def test_models_beat_their_baselines(trained_models):
    category = trained_models["category"]["metrics"]
    assert category["test"]["macro_f1"] > category["test_baseline_most_frequent"]["macro_f1"] + 0.3
    sla = trained_models["sla_risk"]["metrics"]
    assert sla["test"]["roc_auc"] > 0.55
    assert sla["test"]["pr_auc"] > sla["test_breach_rate"]
    routing = trained_models["routing"]["metrics"]
    assert routing["test"]["accuracy"] >= routing["test_rule_baseline"]["accuracy"] - 0.02


def test_scores_are_not_implausibly_perfect(trained_models):
    """Near-perfect results would mean the synthetic data or the split is leaking."""
    assert trained_models["category"]["metrics"]["test"]["macro_f1"] < 0.97
    assert trained_models["sla_risk"]["metrics"]["test"]["roc_auc"] < 0.98


def test_metadata_records_provenance(trained_models):
    metadata = trained_models["sla_risk"]
    assert metadata["data"]["synthetic"] is True
    assert metadata["selected_model"] in metadata["validation_comparison"]
    assert "resolution_minutes" in metadata["excluded_as_leakage"]


def test_saved_confusion_matrix_is_consistent(trained_models):
    metrics = trained_models["category"]["metrics"]
    matrix = np.array(metrics["confusion_matrix"]["matrix"])
    assert matrix.sum() == trained_models["category"]["data"]["splits"]["test"]


def test_inference_uses_the_model_not_fixed_answers(trained_models):
    network = inference.predict_category("VPN tunnel keeps dropping, packet loss on the WAN link")
    database = inference.predict_category("Replication lag on orders_prod, standby stopped applying logs")
    assert network.label == "network"
    assert database.label == "database"
    assert len(network.alternatives) == 3
    assert sum(item["confidence"] for item in network.alternatives) <= 1.0001


def test_routing_returns_ranked_teams(trained_models):
    result = inference.recommend_team("Suspicious mail asking me to confirm my password")
    assert result.label == "Security Operations"
    scores = [item["confidence"] for item in result.alternatives]
    assert scores == sorted(scores, reverse=True)


def test_sla_risk_responds_to_inputs(trained_models):
    base = dict(
        category="database",
        channel="portal",
        team="Database Administration",
        created_at=datetime(2026, 3, 3, 10, tzinfo=UTC),
        description_length=100,
        team_backlog=5,
        team_backlog_high=1,
    )
    medium = inference.predict_sla_risk(incident_features(**base, priority="P3", impact="medium", urgency="medium"))
    low = inference.predict_sla_risk(incident_features(**base, priority="P4", impact="low", urgency="low"))
    assert 0 <= low.confidence <= 1
    # P4 tickets have a 72 hour target, so they breach far less often in the training data.
    assert medium.confidence > low.confidence


def test_tampered_artifacts_are_refused(trained_models, tmp_path):
    version = registry.save_model(tmp_path, "category", {"model": 1}, {"data": {}})
    path = tmp_path / "category" / version / "model.joblib"
    path.write_bytes(path.read_bytes() + b"tampered")
    with pytest.raises(registry.ModelIntegrityError):
        registry.load_model(tmp_path, "category")


def test_missing_model_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "artifacts_dir", tmp_path)
    inference.reload_models()
    assert inference.predict_category("anything at all") is None
    monkeypatch.undo()
    inference.reload_models()


def test_ece_is_zero_for_a_perfectly_calibrated_bin():
    ece, _ = evaluation.expected_calibration_error([1, 0], [0.55, 0.55], bins=10)
    assert ece == pytest.approx(0.05)
    perfect, _ = evaluation.expected_calibration_error([1, 1], [1.0, 1.0], bins=10)
    assert perfect == 0


def test_threshold_metrics():
    result = evaluation.threshold_metrics([1, 1, 0, 0], [0.9, 0.2, 0.8, 0.1], 0.5)
    assert result["precision"] == 0.5
    assert result["recall"] == 0.5
    assert result["flag_rate"] == 0.5


def test_top_k_accuracy():
    classes = np.array(["a", "b", "c"])
    probabilities = np.array([[0.1, 0.2, 0.7], [0.5, 0.4, 0.1]])
    assert evaluation.top_k_accuracy(["b", "c"], probabilities, classes, 2) == 0.5
