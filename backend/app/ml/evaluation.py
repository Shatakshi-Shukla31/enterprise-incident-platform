import numpy as np
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    brier_score_loss,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
    roc_auc_score,
)


def classification_metrics(y_true, y_pred, labels: list[str]) -> dict:
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, average="macro", zero_division=0
    )
    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "macro_precision": round(float(precision), 4),
        "macro_recall": round(float(recall), 4),
        "macro_f1": round(float(f1), 4),
        "weighted_f1": round(float(f1_score(y_true, y_pred, labels=labels, average="weighted", zero_division=0)), 4),
    }


def full_classification_report(y_true, y_pred, labels: list[str]) -> dict:
    report = classification_report(y_true, y_pred, labels=labels, output_dict=True, zero_division=0)
    return {
        "per_class": {label: {key: round(float(value), 4) for key, value in report[label].items()} for label in labels},
        "confusion_matrix": {
            "labels": labels,
            "matrix": confusion_matrix(y_true, y_pred, labels=labels).tolist(),
        },
    }


def top_k_accuracy(y_true, probabilities: np.ndarray, classes: np.ndarray, k: int) -> float:
    top = np.argsort(probabilities, axis=1)[:, -k:]
    hits = [label in classes[row] for label, row in zip(y_true, top, strict=True)]
    return round(float(np.mean(hits)), 4)


def expected_calibration_error(y_true, y_score, bins: int = 10) -> tuple[float, list[dict]]:
    """Mean gap between predicted and observed rate, over equal-width probability bins."""
    y_true, y_score = np.asarray(y_true), np.asarray(y_score)
    edges = np.linspace(0, 1, bins + 1)
    ece = 0.0
    table = []
    for low, high in zip(edges[:-1], edges[1:], strict=True):
        mask = (y_score >= low) & (y_score <= high if high == 1 else y_score < high)
        if not mask.any():
            continue
        predicted, observed = float(y_score[mask].mean()), float(y_true[mask].mean())
        ece += mask.mean() * abs(predicted - observed)
        table.append(
            {
                "bin": f"{low:.1f}-{high:.1f}",
                "count": int(mask.sum()),
                "predicted": round(predicted, 4),
                "observed": round(observed, 4),
            }
        )
    return round(float(ece), 4), table


def binary_risk_metrics(y_true, y_score) -> dict:
    ece, calibration = expected_calibration_error(y_true, y_score)
    return {
        "roc_auc": round(float(roc_auc_score(y_true, y_score)), 4),
        "pr_auc": round(float(average_precision_score(y_true, y_score)), 4),
        "brier": round(float(brier_score_loss(y_true, y_score)), 4),
        "ece": ece,
        "calibration_bins": calibration,
    }


def threshold_metrics(y_true, y_score, threshold: float) -> dict:
    y_true = np.asarray(y_true)
    flagged = np.asarray(y_score) >= threshold
    true_positives = int((flagged & (y_true == 1)).sum())
    precision = true_positives / flagged.sum() if flagged.any() else 0.0
    recall = true_positives / (y_true == 1).sum() if (y_true == 1).any() else 0.0
    return {
        "threshold": threshold,
        "flag_rate": round(float(flagged.mean()), 4),
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
    }
