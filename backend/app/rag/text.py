"""Cleaning, chunking and the safety filters applied to knowledge text."""

import re
import unicodedata

_INJECTION_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(instructions?|prompts?|rules?|guidelines|context)\b",
        r"\b(new|updated|revised|real)\s+(system\s+)?instructions?\b",
        r"\byou\s+are\s+(now|no\s+longer)\b",
        r"\b(act|behave|respond)\s+as\s+(if|an?|the)\b.{0,30}\b(admin|system|developer|unrestricted)\b",
        r"\b(reveal|print|show|repeat|leak)\b.{0,30}\b(system\s+prompt|instructions|secrets?|api\s+keys?)\b",
        r"\bsystem\s+prompt\b",
        r"</?\s*(system|assistant|evidence|instructions?)\b",
        r"\b(do\s+not|don'?t)\s+(cite|mention|tell|warn|reveal)\b.{0,30}\b(sources?|user|this|anyone)\b",
        r"\b(send|post|upload|forward|exfiltrate)\b.{0,50}\bhttps?://",
        r"\bassistant\s*:\s",
    )
]

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{8,}\d(?!\w)")
_CITATION_LIKE = re.compile(r"\[\s*S\s*\d+\s*\]", re.IGNORECASE)
_CONTROL = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f​-‏ - ⁠-⁯﻿]")


def clean_text(text: str) -> str:
    """Normalise, and strip the invisible characters used to hide injected instructions."""
    text = _CONTROL.sub("", unicodedata.normalize("NFKC", text)).replace("\r\n", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def looks_like_injection(text: str) -> bool:
    flattened = re.sub(r"\s+", " ", text)
    return any(pattern.search(flattened) for pattern in _INJECTION_PATTERNS)


def redact_pii(text: str) -> str:
    """Applied to resolved tickets before they become shared knowledge."""
    return _PHONE.sub("[phone removed]", _EMAIL.sub("[email removed]", text))


def neutralise_evidence(text: str) -> str:
    """Remove anything that could pose as prompt structure: a document must not be able to
    close its evidence block or forge a citation."""
    return _CITATION_LIKE.sub("(source)", text).replace("<", "(").replace(">", ")")


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """Split on paragraphs where possible, falling back to sentences for long ones. Each
    chunk repeats the end of the previous one so a step is not cut from its context."""
    units: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if len(paragraph) <= size:
            units.append(paragraph)
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", paragraph):
            units.extend(sentence[start : start + size] for start in range(0, len(sentence), size - overlap))

    chunks: list[str] = []
    current = ""
    for unit in units:
        if current and len(current) + len(unit) + 2 > size:
            chunks.append(current)
            current = current[-overlap:].lstrip() if overlap else ""
            boundary = current.find(" ")
            current = current[boundary + 1 :] if boundary > 0 else current
        current = f"{current}\n\n{unit}" if current else unit
    if current:
        chunks.append(current)
    return chunks


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [part.strip(" -*\t") for part in parts if len(part.strip(" -*\t")) > 15]
