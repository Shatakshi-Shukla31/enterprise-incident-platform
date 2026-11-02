"""SLA-risk benchmark on real, public data: python -m app.ml.benchmark_uci --csv PATH

Applies the leakage rules used by the production model to the UCI "Incident management
process enriched event log", an anonymised ServiceNow export. The result is a validation of
the method only. The served model uses different features and is not trained on this data.

The source is an event log with several traps, each handled here:

* `made_sla` changes during the life of many incidents, so the label comes from the last
  event, and every incident contributes one row.
* The export is backfilled: a row in state New can already show closed_code and resolved_by.
  Only fields set when a ticket is opened are used, and they are read from its first event.
* Counters such as sys_mod_count rise as work happens, so they are excluded.

A deliberately leaky model is trained alongside, to measure what these rules prevent.
"""

import argparse
import json
from pathlib import Path

import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.ml import evaluation
from app.ml.train import purge_before, time_split

OPENING_CATEGORICAL = [
    "contact_type",
    "location",
    "category",
    "subcategory",
    "u_symptom",
    "impact",
    "urgency",
    "priority",
    "assignment_group",
]
OPENING_NUMERIC = ["hour", "day_of_week", "is_weekend", "is_after_hours"]
LEAKY_NUMERIC = ["final_sys_mod_count", "final_reassignment_count", "final_reopen_count", "resolution_hours"]
LEAKY_CATEGORICAL = ["closed_code"]
SEED = 42


def load_incidents(csv_path: Path) -> pd.DataFrame:
    """One row per incident: opening fields from the first event, outcome from the last."""
    events = pd.read_csv(csv_path, na_values=["?"], low_memory=False)
    for column in ("opened_at", "sys_updated_at", "resolved_at"):
        events[column] = pd.to_datetime(events[column], format="%d/%m/%Y %H:%M", errors="coerce")
    events = events.sort_values(["number", "sys_mod_count", "sys_updated_at"])
    grouped = events.groupby("number", sort=False)
    first, last = grouped.head(1).set_index("number"), grouped.tail(1).set_index("number")

    frame = first[["opened_at", *OPENING_CATEGORICAL]].copy()
    frame["sla_breached"] = (~last["made_sla"]).astype(int)
    frame["resolved_at"] = last["resolved_at"]
    frame["final_sys_mod_count"] = last["sys_mod_count"]
    frame["final_reassignment_count"] = last["reassignment_count"]
    frame["final_reopen_count"] = last["reopen_count"]
    frame["closed_code"] = last["closed_code"]
    frame["resolution_hours"] = (frame["resolved_at"] - frame["opened_at"]).dt.total_seconds() / 3600

    frame = frame.dropna(subset=["opened_at", "resolved_at"]).sort_values("opened_at")
    frame["hour"] = frame["opened_at"].dt.hour
    frame["day_of_week"] = frame["opened_at"].dt.day_of_week
    frame["is_weekend"] = (frame["day_of_week"] >= 5).astype(int)
    frame["is_after_hours"] = ((frame["is_weekend"] == 1) | ~frame["hour"].between(8, 17)).astype(int)
    frame[OPENING_CATEGORICAL + LEAKY_CATEGORICAL] = (
        frame[OPENING_CATEGORICAL + LEAKY_CATEGORICAL].astype("object").fillna("missing").astype(str)
    )
    return frame


def splits(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Chronological, with one embargo before the test period.

    The usable data spans about eleven weeks and resolution can take weeks, so a second
    embargo would leave no validation rows. Every row before the test period has a known
    label, so splitting them for model selection cannot leak into the test score.
    """
    known, test = time_split(frame, 0.75)
    known = purge_before(known, test["opened_at"].min(), "opened_at")
    train, validation = time_split(known, 0.8)
    return train, validation, test


def _pipeline(categorical: list[str], numeric: list[str], classifier) -> Pipeline:
    features = ColumnTransformer(
        [
            ("categorical", OneHotEncoder(handle_unknown="ignore", min_frequency=20), categorical),
            ("numeric", StandardScaler(), numeric),
        ]
    )
    return Pipeline([("features", features), ("clf", classifier)])


def _lightgbm() -> LGBMClassifier:
    return LGBMClassifier(
        n_estimators=300,
        learning_rate=0.03,
        num_leaves=15,
        min_child_samples=30,
        subsample=0.8,
        subsample_freq=1,
        colsample_bytree=0.6,
        random_state=SEED,
        n_jobs=2,
        verbose=-1,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    frame = load_incidents(args.csv)
    train, validation, test = splits(frame)
    y_train, y_validation, y_test = train["sla_breached"], validation["sla_breached"], test["sla_breached"]

    candidates = {
        "baseline_prior": _pipeline(OPENING_CATEGORICAL, OPENING_NUMERIC, DummyClassifier(strategy="prior")),
        "logistic_regression": _pipeline(
            OPENING_CATEGORICAL, OPENING_NUMERIC, LogisticRegression(max_iter=3000, C=0.3)
        ),
        "lightgbm": _pipeline(OPENING_CATEGORICAL, OPENING_NUMERIC, _lightgbm()),
    }
    comparison = {}
    for name, model in candidates.items():
        model.fit(train, y_train)
        scores = evaluation.binary_risk_metrics(y_validation, model.predict_proba(validation)[:, 1])
        scores.pop("calibration_bins")
        comparison[name] = scores
        print(name, scores)

    best_name = max(comparison, key=lambda name: comparison[name]["pr_auc"])
    test_scores = evaluation.binary_risk_metrics(y_test, candidates[best_name].predict_proba(test)[:, 1])
    test_scores.pop("calibration_bins")

    monthly = frame.groupby(frame["opened_at"].dt.to_period("M"))["sla_breached"].agg(["mean", "count"])
    leaky = _pipeline(OPENING_CATEGORICAL + LEAKY_CATEGORICAL, OPENING_NUMERIC + LEAKY_NUMERIC, _lightgbm()).fit(
        train, y_train
    )
    leaky_scores = evaluation.binary_risk_metrics(y_test, leaky.predict_proba(test)[:, 1])
    leaky_scores.pop("calibration_bins")

    report = {
        "dataset": "UCI Incident management process enriched event log (public, anonymised)",
        "purpose": "Validates the leakage-safe method on real data. Not used by the served model.",
        "incidents": len(frame),
        "breach_rate": round(float(frame["sla_breached"].mean()), 4),
        "date_range": [str(frame["opened_at"].min()), str(frame["opened_at"].max())],
        "splits": {"train": len(train), "validation": len(validation), "test": len(test)},
        "breach_rate_by_split": {
            "train": round(float(y_train.mean()), 4),
            "validation": round(float(y_validation.mean()), 4),
            "test": round(float(y_test.mean()), 4),
        },
        "breach_rate_by_month": {
            str(month): {"rate": round(float(row["mean"]), 4), "incidents": int(row["count"])}
            for month, row in monthly.iterrows()
            if row["count"] >= 100
        },
        "selected_model": best_name,
        "validation_comparison": comparison,
        "test": test_scores,
        "test_breach_rate": round(float(y_test.mean()), 4),
        "test_with_deliberate_leakage": leaky_scores,
        "leaky_features": LEAKY_NUMERIC + LEAKY_CATEGORICAL,
    }
    print(json.dumps(report, indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
