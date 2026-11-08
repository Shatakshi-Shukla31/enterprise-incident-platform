"""Reproducible training: python -m app.ml.train [--days N] [--seed N] [--report-dir DIR]

Model selection uses the validation split only. The test split is scored once, for the
selected model, and every figure in the output is computed here, never entered by hand.
"""

import argparse
import hashlib
import json
import logging
import re
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.calibration import CalibratedClassifierCV
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.frozen import FrozenEstimator
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, f1_score
from sklearn.model_selection import GroupKFold
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.svm import LinearSVC

from app.core.config import get_settings
from app.ml import evaluation, registry
from app.ml.features import (
    CATEGORICAL_FEATURES,
    FORBIDDEN_FEATURES,
    NUMERIC_FEATURES,
    SLA_FEATURES,
    build_sla_frame,
    typical_ticket,
)
from app.ml.routing import RuleRouter
from app.ml.synthetic import generate

logger = logging.getLogger("train")

F1_TIE_MARGIN = 0.01
EMBARGO_QUANTILE = 0.95


def _normalise(text: str) -> str:
    return re.sub(r"\W+", " ", text.lower()).strip()


def inspect_dataset(history: pd.DataFrame) -> dict:
    """Reported before training, and stored with the model."""
    text = (history["title"] + " " + history["description"]).map(_normalise)
    return {
        "rows": len(history),
        "date_range": [str(history["created_at"].min()), str(history["created_at"].max())],
        "null_counts": {k: int(v) for k, v in history.isna().sum().items() if v},
        "exact_duplicate_text_rows": int(text.duplicated().sum()),
        "category_counts": history["category"].value_counts().to_dict(),
        "team_counts": history["team"].value_counts().to_dict(),
        "priority_counts": history["priority"].value_counts().to_dict(),
        "sla_breach_rate": round(float(history["sla_breached"].mean()), 4),
        "sla_breach_rate_by_priority": history.groupby("priority")["sla_breached"].mean().round(4).to_dict(),
    }


def prepare_text_data(history: pd.DataFrame) -> pd.DataFrame:
    """Chronological order with duplicate tickets removed. An identical ticket on both sides
    of a split would score the model on text it memorised."""
    frame = history.sort_values("created_at").copy()
    frame["text"] = frame["title"] + "\n" + frame["description"]
    frame["normalised"] = frame["text"].map(_normalise)
    return frame.drop_duplicates("normalised", keep="first").reset_index(drop=True)


def time_split(frame: pd.DataFrame, *fractions: float) -> list[pd.DataFrame]:
    boundaries = np.cumsum([int(len(frame) * fraction) for fraction in fractions])
    parts, start = [], 0
    for end in [*boundaries, len(frame)]:
        parts.append(frame.iloc[start:end])
        start = end
    return parts


def _vectoriser() -> FeatureUnion:
    return FeatureUnion(
        [
            ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, max_features=60000)),
            (
                "char",
                TfidfVectorizer(
                    analyzer="char_wb", ngram_range=(3, 5), min_df=3, sublinear_tf=True, max_features=60000
                ),
            ),
        ]
    )


def _text_candidates() -> dict[str, Pipeline]:
    return {
        "baseline_most_frequent": Pipeline(
            [("tfidf", TfidfVectorizer(max_features=10)), ("clf", DummyClassifier(strategy="most_frequent"))]
        ),
        "tfidf_naive_bayes": Pipeline([("tfidf", _vectoriser()), ("clf", MultinomialNB(alpha=0.3))]),
        "tfidf_logistic_regression": Pipeline(
            [("tfidf", _vectoriser()), ("clf", LogisticRegression(C=8.0, max_iter=1000, class_weight="balanced"))]
        ),
        "tfidf_linear_svc_calibrated": Pipeline(
            [
                ("tfidf", _vectoriser()),
                ("clf", CalibratedClassifierCV(LinearSVC(C=0.5, class_weight="balanced"), cv=3)),
            ]
        ),
    }


def _confidence_coverage(y_true, probabilities, classes) -> list[dict]:
    predicted = classes[probabilities.argmax(axis=1)]
    confidence = probabilities.max(axis=1)
    y_true = np.asarray(y_true)
    rows = []
    for threshold in (0.5, 0.6, 0.7, 0.8, 0.9):
        mask = confidence >= threshold
        rows.append(
            {
                "min_confidence": threshold,
                "coverage": round(float(mask.mean()), 4),
                "accuracy": round(float((predicted[mask] == y_true[mask]).mean()), 4) if mask.any() else None,
            }
        )
    return rows


def _unseen_phrasing_score(frame: pd.DataFrame, make_model, label: str) -> dict:
    """Score on sentence patterns absent from training. The time split shares templates
    across train and test, which real ticket text would not, so this is the fairer test."""
    scores = []
    for train_index, test_index in GroupKFold(n_splits=3).split(frame, groups=frame["phrase_id"]):
        model = make_model()
        model.fit(frame["text"].iloc[train_index], frame[label].iloc[train_index])
        predictions = model.predict(frame["text"].iloc[test_index])
        scores.append(f1_score(frame[label].iloc[test_index], predictions, average="macro"))
    return {
        "macro_f1_mean": round(float(np.mean(scores)), 4),
        "macro_f1_std": round(float(np.std(scores)), 4),
        "folds": 3,
    }


def train_category(history: pd.DataFrame, data_hash: str, seed: int, root: Path) -> dict:
    frame = prepare_text_data(history)
    train, validation, test = time_split(frame, 0.7, 0.15)
    assert not set(train["normalised"]) & set(test["normalised"]), "duplicate leakage"
    labels = sorted(frame["category"].unique())

    results = {}
    fitted = {}
    for name, model in _text_candidates().items():
        model.fit(train["text"], train["category"])
        fitted[name] = model
        results[name] = evaluation.classification_metrics(
            validation["category"], model.predict(validation["text"]), labels
        )
        probabilities = model.predict_proba(validation["text"])
        correct = model.classes_[probabilities.argmax(axis=1)] == validation["category"].to_numpy()
        results[name]["confidence_ece"] = evaluation.expected_calibration_error(correct, probabilities.max(axis=1))[0]
        logger.info("category %s validation %s", name, results[name])

    # Agents see the confidence and auto-routing depends on it, so among models tied on
    # macro F1 the one whose confidence can be believed wins.
    top_f1 = max(result["macro_f1"] for result in results.values())
    tied = [name for name, result in results.items() if top_f1 - result["macro_f1"] <= F1_TIE_MARGIN]
    best_name = min(tied, key=lambda name: results[name]["confidence_ece"])
    best = fitted[best_name]
    probabilities = best.predict_proba(test["text"])
    predictions = best.classes_[probabilities.argmax(axis=1)]
    confident = probabilities.max(axis=1)
    ece, _ = evaluation.expected_calibration_error(predictions == test["category"].to_numpy(), confident)
    baseline = fitted["baseline_most_frequent"].predict(test["text"])
    metrics = {
        "test": evaluation.classification_metrics(test["category"], predictions, labels),
        "test_baseline_most_frequent": evaluation.classification_metrics(test["category"], baseline, labels),
        "test_top3_accuracy": evaluation.top_k_accuracy(test["category"], probabilities, best.classes_, 3),
        "test_confidence_ece": ece,
        "test_confidence_coverage": _confidence_coverage(test["category"], probabilities, best.classes_),
        "unseen_phrasing": _unseen_phrasing_score(frame, lambda: _text_candidates()[best_name], "category"),
        **evaluation.full_classification_report(test["category"], predictions, labels),
    }
    metadata = {
        "selected_model": best_name,
        "selection_metric": f"lowest validation confidence ECE within {F1_TIE_MARGIN} of the best macro F1",
        "validation_comparison": results,
        "metrics": metrics,
        "data": {
            "sha256": data_hash,
            "seed": seed,
            "synthetic": True,
            "rows_after_dedup": len(frame),
            "splits": {"train": len(train), "validation": len(validation), "test": len(test)},
            "split_strategy": "chronological, deduplicated on normalised text",
        },
    }
    best.fit(pd.concat([train, validation])["text"], pd.concat([train, validation])["category"])
    metadata["version"] = registry.save_model(root, "category", best, metadata)
    return metadata


def train_routing(history: pd.DataFrame, data_hash: str, seed: int, root: Path) -> dict:
    frame = prepare_text_data(history)
    train, validation, test = time_split(frame, 0.7, 0.15)
    labels = sorted(frame["team"].unique())

    classifier = Pipeline(
        [("tfidf", _vectoriser()), ("clf", LogisticRegression(C=8.0, max_iter=1000, class_weight="balanced"))]
    ).fit(train["text"], train["category"])
    shares = train.groupby("category")["team"].value_counts(normalize=True)
    category_teams = {
        category: {team: float(value) for team, value in shares[category].items()}
        for category in train["category"].unique()
    }
    rule = RuleRouter(classifier, category_teams, labels)
    text_model = Pipeline(
        [("tfidf", _vectoriser()), ("clf", LogisticRegression(C=8.0, max_iter=1000, class_weight="balanced"))]
    ).fit(train["text"], train["team"])

    candidates = {"category_rule_baseline": rule, "tfidf_logistic_regression": text_model}
    comparison = {}
    for name, model in candidates.items():
        probabilities = model.predict_proba(validation["text"].tolist())
        predictions = model.classes_[probabilities.argmax(axis=1)]
        comparison[name] = {
            **evaluation.classification_metrics(validation["team"], predictions, labels),
            "top3_accuracy": evaluation.top_k_accuracy(validation["team"], probabilities, model.classes_, 3),
        }
    best_name = max(comparison, key=lambda name: comparison[name]["accuracy"])
    best = candidates[best_name]

    probabilities = best.predict_proba(test["text"].tolist())
    predictions = best.classes_[probabilities.argmax(axis=1)]
    rule_probabilities = rule.predict_proba(test["text"].tolist())
    metrics = {
        "test": evaluation.classification_metrics(test["team"], predictions, labels),
        "test_top3_accuracy": evaluation.top_k_accuracy(test["team"], probabilities, best.classes_, 3),
        "test_rule_baseline": evaluation.classification_metrics(
            test["team"], rule.classes_[rule_probabilities.argmax(axis=1)], labels
        ),
        "test_confidence_coverage": _confidence_coverage(test["team"], probabilities, best.classes_),
        **evaluation.full_classification_report(test["team"], predictions, labels),
    }
    metadata = {
        "selected_model": best_name,
        "selection_metric": "validation accuracy",
        "validation_comparison": comparison,
        "metrics": metrics,
        "data": {
            "sha256": data_hash,
            "seed": seed,
            "synthetic": True,
            "splits": {"train": len(train), "validation": len(validation), "test": len(test)},
            "split_strategy": "chronological, deduplicated on normalised text",
        },
    }
    metadata["version"] = registry.save_model(root, "routing", best, metadata)
    return metadata


def _sla_preprocessor() -> ColumnTransformer:
    return ColumnTransformer(
        [
            ("categorical", OneHotEncoder(handle_unknown="ignore", min_frequency=5), CATEGORICAL_FEATURES),
            ("numeric", StandardScaler(), NUMERIC_FEATURES),
        ]
    )


def _sla_candidates(seed: int) -> dict[str, Pipeline]:
    return {
        "baseline_prior": Pipeline([("features", _sla_preprocessor()), ("clf", DummyClassifier(strategy="prior"))]),
        "logistic_regression": Pipeline(
            [("features", _sla_preprocessor()), ("clf", LogisticRegression(max_iter=2000, C=1.0))]
        ),
        "lightgbm": Pipeline(
            [
                ("features", _sla_preprocessor()),
                (
                    "clf",
                    LGBMClassifier(
                        n_estimators=250,
                        learning_rate=0.04,
                        num_leaves=15,
                        min_child_samples=40,
                        subsample=0.8,
                        subsample_freq=1,
                        colsample_bytree=0.8,
                        random_state=seed,
                        n_jobs=2,
                        verbose=-1,
                    ),
                ),
            ]
        ),
    }


def purge_before(part: pd.DataFrame, cutoff: pd.Timestamp, opened_column: str = "created_at") -> pd.DataFrame:
    """Keep rows whose outcome was known at `cutoff`, without biasing the label.

    Removing only the rows that resolved after the cutoff would stop future outcomes leaking
    in, but slow tickets are disproportionately breaches, so it would also delete the very
    cases being predicted. An embargo removes every row opened within the usual resolution
    time of the cutoff, whatever its outcome. The long tail is still removed individually.
    """
    embargo = (part["resolved_at"] - part[opened_column]).quantile(EMBARGO_QUANTILE)
    return part[(part[opened_column] < cutoff - embargo) & (part["resolved_at"] < cutoff)]


def sla_splits(history: pd.DataFrame) -> list[pd.DataFrame]:
    """Chronological train, validation, calibration and test splits, each purged so that
    a row's label was already known when the following split begins."""
    frame = history.sort_values("created_at").reset_index(drop=True)
    parts = time_split(frame, 0.6, 0.15, 0.1)
    cleaned = [purge_before(part, parts[index + 1]["created_at"].min()) for index, part in enumerate(parts[:-1])]
    return [*cleaned, parts[-1]]


def train_sla(history: pd.DataFrame, data_hash: str, seed: int, root: Path) -> dict:
    leaked = FORBIDDEN_FEATURES & set(SLA_FEATURES)
    if leaked:
        raise ValueError(f"Target leakage: {sorted(leaked)}")

    train, validation, calibration, test = sla_splits(history)
    X_train, y_train = build_sla_frame(train), train["sla_breached"]
    X_validation, y_validation = build_sla_frame(validation), validation["sla_breached"]

    comparison = {}
    fitted = {}
    for name, model in _sla_candidates(seed).items():
        model.fit(X_train, y_train)
        fitted[name] = model
        comparison[name] = evaluation.binary_risk_metrics(y_validation, model.predict_proba(X_validation)[:, 1])
        comparison[name].pop("calibration_bins")
        logger.info("sla %s validation %s", name, comparison[name])

    best_name = max(comparison, key=lambda name: comparison[name]["pr_auc"])
    X_calibration, y_calibration = build_sla_frame(calibration), calibration["sla_breached"]
    calibration_options = {"none": fitted[best_name]}
    for method in ("sigmoid", "isotonic"):
        calibration_options[method] = CalibratedClassifierCV(FrozenEstimator(fitted[best_name]), method=method).fit(
            X_calibration, y_calibration
        )
    # Calibration is kept only if it improves probabilities on data it did not see.
    calibration_brier = {
        name: round(float(brier_score_loss(y_validation, option.predict_proba(X_validation)[:, 1])), 5)
        for name, option in calibration_options.items()
    }
    best_calibration = min(calibration_brier, key=calibration_brier.get)
    calibrated = calibration_options[best_calibration]

    X_test, y_test = build_sla_frame(test), test["sla_breached"]
    scores = calibrated.predict_proba(X_test)[:, 1]
    alert_threshold = get_settings().sla_risk_alert_threshold

    validation_scores = calibrated.predict_proba(X_validation)[:, 1]
    grid = np.arange(0.1, 0.9, 0.05)
    f1s = [f1_score(y_validation, validation_scores >= value, zero_division=0) for value in grid]
    tuned_threshold = round(float(grid[int(np.argmax(f1s))]), 2)
    prior = fitted["baseline_prior"].predict_proba(X_test)[:, 1]

    metrics = {
        "test": evaluation.binary_risk_metrics(y_test, scores),
        "test_baseline_prior": {
            "pr_auc": round(float(average_precision_score(y_test, prior)), 4),
            "brier": round(float(np.mean((prior - y_test) ** 2)), 4),
        },
        "test_breach_rate": round(float(y_test.mean()), 4),
        "at_alert_threshold": evaluation.threshold_metrics(y_test, scores, alert_threshold),
        "at_validation_tuned_threshold": evaluation.threshold_metrics(y_test, scores, tuned_threshold),
    }
    metadata = {
        "selected_model": best_name,
        "selection_metric": "validation pr_auc",
        "calibration": {
            "selected": best_calibration,
            "validation_brier": calibration_brier,
            "fitted_on": "a dedicated chronological split",
        },
        "validation_comparison": comparison,
        "metrics": metrics,
        "features": SLA_FEATURES,
        "reference": typical_ticket(X_train),
        "excluded_as_leakage": sorted(FORBIDDEN_FEATURES),
        "data": {
            "sha256": data_hash,
            "seed": seed,
            "synthetic": True,
            "splits": {
                "train": len(train),
                "validation": len(validation),
                "calibration": len(calibration),
                "test": len(test),
            },
            "split_strategy": "chronological; rows with labels unknown at the split boundary removed",
        },
    }
    metadata["version"] = registry.save_model(root, "sla_risk", calibrated, metadata)
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=540)
    parser.add_argument("--daily-mean", type=float, default=34)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--report-dir", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    history = generate(days=args.days, daily_mean=args.daily_mean, seed=args.seed)
    data_hash = hashlib.sha256(
        pd.util.hash_pandas_object(history[["title", "category", "team", "sla_breached"]]).values.tobytes()
    ).hexdigest()
    inspection = inspect_dataset(history)
    logger.info("dataset %s", json.dumps(inspection, indent=2, default=str))

    root = get_settings().artifacts_dir
    results = {
        "category": train_category(history, data_hash, args.seed, root),
        "routing": train_routing(history, data_hash, args.seed, root),
        "sla_risk": train_sla(history, data_hash, args.seed, root),
    }
    for kind, result in results.items():
        logger.info(
            "%s selected=%s test=%s",
            kind,
            result["selected_model"],
            {k: v for k, v in result["metrics"]["test"].items() if k != "calibration_bins"},
        )
    if args.report_dir:
        args.report_dir.mkdir(parents=True, exist_ok=True)
        (args.report_dir / "dataset.json").write_text(json.dumps(inspection, indent=2, default=str), encoding="utf-8")
        for kind, result in results.items():
            (args.report_dir / f"{kind}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
