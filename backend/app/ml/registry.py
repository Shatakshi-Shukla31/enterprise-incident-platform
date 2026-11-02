"""File-based model registry: versioned artifacts with metadata and integrity checks."""

import hashlib
import json
import platform
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import joblib
import sklearn


class ModelIntegrityError(RuntimeError):
    pass


@dataclass(frozen=True)
class LoadedModel:
    kind: str
    version: str
    model: object
    metadata: dict


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_model(root: Path, kind: str, model: object, metadata: dict) -> str:
    version = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    directory = root / kind / version
    directory.mkdir(parents=True, exist_ok=True)
    model_path = directory / "model.joblib"
    joblib.dump(model, model_path, compress=3)
    full_metadata = {
        **metadata,
        "kind": kind,
        "version": version,
        "created_at": datetime.now(UTC).isoformat(),
        "model_sha256": _sha256(model_path),
        "sklearn_version": sklearn.__version__,
        "python_version": platform.python_version(),
    }
    (directory / "metadata.json").write_text(json.dumps(full_metadata, indent=2), encoding="utf-8")
    (root / kind / "LATEST").write_text(version, encoding="utf-8")
    return version


def load_metadata(root: Path, kind: str) -> dict | None:
    latest = root / kind / "LATEST"
    if not latest.exists():
        return None
    version = latest.read_text(encoding="utf-8").strip()
    return json.loads((root / kind / version / "metadata.json").read_text(encoding="utf-8"))


def load_model(root: Path, kind: str) -> LoadedModel | None:
    metadata = load_metadata(root, kind)
    if metadata is None:
        return None
    path = root / kind / metadata["version"] / "model.joblib"
    # joblib deserialisation executes code, so only load the exact file training produced.
    if _sha256(path) != metadata["model_sha256"]:
        raise ModelIntegrityError(f"Checksum mismatch for {path}")
    return LoadedModel(kind, metadata["version"], joblib.load(path), metadata)
