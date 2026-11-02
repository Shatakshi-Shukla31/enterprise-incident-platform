"""Embedding backends. `fastembed` runs all-MiniLM-L6-v2 on ONNX Runtime, which needs far
less disk and memory than PyTorch on a CPU-only machine and gives the same 384-dimensional
vectors. `sentence_transformers` is the optional PyTorch route to the same model."""

import hashlib
import re
import threading
from functools import lru_cache
from typing import Protocol

import numpy as np

from app.core.config import get_settings


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def _normalise(vectors: np.ndarray) -> list[list[float]]:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return (vectors / np.clip(norms, 1e-12, None)).tolist()


class FastEmbedEmbedder:
    def __init__(self, model: str, cache_dir: str | None) -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model, cache_dir=cache_dir, threads=4)
        self._lock = threading.Lock()

    def embed(self, texts: list[str]) -> list[list[float]]:
        with self._lock:
            return _normalise(np.array(list(self._model.embed(texts, batch_size=32))))


class SentenceTransformerEmbedder:
    def __init__(self, model: str, cache_dir: str | None) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model, cache_folder=cache_dir, device="cpu")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return _normalise(self._model.encode(texts, batch_size=32, show_progress_bar=False))


class HashEmbedder:
    """Deterministic token hashing, for tests that must not download a model. It rewards
    shared words only, so it says nothing about real retrieval quality."""

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def embed(self, texts: list[str]) -> list[list[float]]:
        output = np.zeros((len(texts), self.dimension))
        for row, text in enumerate(texts):
            for token in re.findall(r"[a-z0-9]+", text.lower()):
                digest = hashlib.sha256(token.encode()).digest()
                output[row, int.from_bytes(digest[:4]) % self.dimension] += 1.0
        return _normalise(output)


@lru_cache
def get_embedder() -> Embedder:
    settings = get_settings()
    cache_dir = str(settings.embedding_cache_dir) if settings.embedding_cache_dir else None
    match settings.embedding_provider:
        case "fastembed":
            return FastEmbedEmbedder(settings.embedding_model, cache_dir)
        case "sentence_transformers":
            return SentenceTransformerEmbedder(settings.embedding_model, cache_dir)
        case _:
            return HashEmbedder(settings.embedding_dim)
