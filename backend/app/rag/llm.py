"""LLM providers behind one interface. The RAG pipeline depends only on `LLMProvider`, so
adding a backend means adding a class here and a line in `get_llm`."""

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import httpx
import numpy as np

from app.core.config import get_settings
from app.rag.embeddings import get_embedder
from app.rag.text import split_sentences

_FIELD_LABEL = re.compile(r"^Resolution:\s*", re.IGNORECASE)


class LLMError(RuntimeError):
    pass


@dataclass(frozen=True)
class Source:
    id: str
    title: str
    text: str


@dataclass(frozen=True)
class LLMRequest:
    system: str
    prompt: str
    question: str
    sources: list[Source]


class LLMProvider(Protocol):
    name: str

    def generate(self, request: LLMRequest) -> str: ...


class ExtractiveProvider:
    """No model required: selects the evidence sentences closest to the question and cites
    them. It cannot state anything outside the sources, which also makes it the fallback
    when a configured LLM is unreachable.

    The tuned retrieval threshold decides whether to answer. By the time evidence reaches
    this class it has been accepted, so `min_sentence_similarity` only trims a long answer
    and never empties one: a step can be the right advice without echoing the question."""

    name = "extractive"
    max_sentences = 4
    min_sentences = 2
    min_sentence_similarity = 0.3

    def generate(self, request: LLMRequest) -> str:
        candidates = [
            (source.id, sentence)
            for source in request.sources
            for sentence in split_sentences(source.text)
            if not sentence.lower().startswith(("problem reported:", "symptoms"))
        ]
        candidates = [(source_id, _FIELD_LABEL.sub("", sentence)) for source_id, sentence in candidates]
        if not candidates:
            return "INSUFFICIENT_EVIDENCE"
        embedder = get_embedder()
        vectors = np.array(embedder.embed([request.question] + [sentence for _, sentence in candidates]))
        scores = vectors[1:] @ vectors[0]

        chosen: list[str] = []
        seen: set[str] = set()
        for index in np.argsort(-scores):
            enough = len(chosen) >= self.min_sentences and scores[index] < self.min_sentence_similarity
            if enough or len(chosen) == self.max_sentences:
                break
            source_id, sentence = candidates[index]
            key = re.sub(r"\W+", "", sentence.lower())
            if key in seen:
                continue
            seen.add(key)
            ending = "" if sentence.endswith((".", "!", "?")) else "."
            chosen.append(f"- {sentence}{ending} [{source_id}]")
        return "Based on the retrieved sources:\n" + "\n".join(chosen)


class OllamaProvider:
    def __init__(self, base_url: str, model: str, timeout: float, temperature: float, max_tokens: int):
        self.name = f"ollama:{model}"
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)
        self._model = model
        self._options = {"temperature": temperature, "num_predict": max_tokens}

    def generate(self, request: LLMRequest) -> str:
        try:
            response = self._client.post(
                "/api/chat",
                json={
                    "model": self._model,
                    "stream": False,
                    "options": self._options,
                    "messages": [
                        {"role": "system", "content": request.system},
                        {"role": "user", "content": request.prompt},
                    ],
                },
            )
            response.raise_for_status()
            return response.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc


class OpenAICompatibleProvider:
    """Any hosted or local service exposing POST {base_url}/chat/completions."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None,
        timeout: float,
        temperature: float,
        max_tokens: int,
    ):
        self.name = f"openai_compatible:{model}"
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, headers=headers)
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    def generate(self, request: LLMRequest) -> str:
        try:
            response = self._client.post(
                "/chat/completions",
                json={
                    "model": self._model,
                    "temperature": self._temperature,
                    "max_tokens": self._max_tokens,
                    "messages": [
                        {"role": "system", "content": request.system},
                        {"role": "user", "content": request.prompt},
                    ],
                },
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc


@lru_cache
def get_llm() -> LLMProvider:
    settings = get_settings()
    match settings.llm_provider:
        case "ollama":
            return OllamaProvider(
                settings.llm_base_url,
                settings.llm_model,
                settings.llm_timeout_seconds,
                settings.llm_temperature,
                settings.llm_max_tokens,
            )
        case "openai_compatible":
            return OpenAICompatibleProvider(
                settings.llm_base_url,
                settings.llm_model,
                settings.llm_api_key,
                settings.llm_timeout_seconds,
                settings.llm_temperature,
                settings.llm_max_tokens,
            )
        case _:
            return ExtractiveProvider()
