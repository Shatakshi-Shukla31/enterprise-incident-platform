"""RAG evaluation: python -m app.rag.evaluate [--report PATH]

Retrieval runs against the real pipeline as an admin, so access filters do not distort the
result. A TF-IDF keyword search over the same chunks gives the baseline. The evidence
threshold is chosen on `dev` queries, and only `test` queries are reported as results.
"""

import argparse
import json
import re
import statistics
import time
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sqlalchemy import select

from app.core.config import BACKEND_DIR, get_settings
from app.core.enums import DocumentSource, Role
from app.db.session import new_session
from app.models import KnowledgeChunk, KnowledgeDocument, User
from app.rag.generator import generate_answer
from app.rag.retriever import retrieve

GOLDEN_PATH = BACKEND_DIR / "data" / "eval" / "rag_golden.json"
_STOP = frozenset("the a an and or to of in on for is are be it this that with from as at by your you".split())


def ranked_refs(hits) -> list[str]:
    return list(dict.fromkeys(hit.source_ref for hit in hits))


def recall_at_k(ranked: list[str], relevant: set[str], k: int) -> float:
    return len(set(ranked[:k]) & relevant) / len(relevant)


def reciprocal_rank(ranked: list[str], relevant: set[str]) -> float:
    for rank, ref in enumerate(ranked, start=1):
        if ref in relevant:
            return 1 / rank
    return 0.0


def _retrieval_scores(results: list[tuple[list[str], set[str]]]) -> dict:
    return {
        "queries": len(results),
        "recall_at_1": round(np.mean([recall_at_k(r, g, 1) for r, g in results]), 4),
        "recall_at_3": round(np.mean([recall_at_k(r, g, 3) for r, g in results]), 4),
        "recall_at_5": round(np.mean([recall_at_k(r, g, 5) for r, g in results]), 4),
        "mrr": round(np.mean([reciprocal_rank(r, g) for r, g in results]), 4),
    }


def _content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in _STOP}


def grounding_score(answer: str, cited_texts: dict[str, str]) -> float:
    """Share of answer sentences mostly made of words from the source they cite."""
    sentences = [s for s in re.split(r"\n+", answer) if "[S" in s]
    if not sentences:
        return 0.0
    supported = 0
    for sentence in sentences:
        cited = re.findall(r"\[(S\d+)\]", sentence)
        evidence = _content_words(" ".join(cited_texts.get(c, "") for c in cited))
        words = _content_words(re.sub(r"\[S\d+\]", "", sentence))
        supported += bool(words) and len(words & evidence) / len(words) >= 0.7
    return supported / len(sentences)


def _keyword_baseline(db, queries: list[str]) -> list[list[str]]:
    rows = db.execute(
        select(KnowledgeChunk.content, KnowledgeDocument.source_ref)
        .join(KnowledgeDocument)
        .where(KnowledgeDocument.source_type == DocumentSource.KB_ARTICLE)
    ).all()
    vectoriser = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
    matrix = vectoriser.fit_transform([content for content, _ in rows])
    scores = (vectoriser.transform(queries) @ matrix.T).toarray()
    return [list(dict.fromkeys(rows[index][1] for index in np.argsort(-row)[:20])) for row in scores]


def tune_threshold(positive: list[float], negative: list[float]) -> tuple[float, float]:
    """Threshold maximising balanced accuracy of answer vs refuse on dev queries. Takes the
    middle of the best range, leaving margin on both sides rather than sitting on its edge."""
    grid = np.arange(0.2, 0.8, 0.01)
    scores = np.array([(np.mean(np.array(positive) >= t) + np.mean(np.array(negative) < t)) / 2 for t in grid])
    best = grid[scores == scores.max()]
    return round(float((best[0] + best[-1]) / 2), 2), round(float(scores.max()), 4)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    settings = get_settings()
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))

    with new_session() as db:
        admin = db.scalar(select(User).where(User.role == Role.ADMIN))
        if admin is None:
            raise SystemExit("No admin user found. Run scripts/seed_demo.py first.")

        def search(query: str, top_k: int = 5):
            hits = retrieve(db, admin, query, top_k=top_k, source_type=DocumentSource.KB_ARTICLE)
            db.rollback()  # ends the transaction that holds SET LOCAL
            return hits

        all_answerable = golden["answerable"]
        retrieved = {item["query"]: search(item["query"]) for item in all_answerable}
        latencies = []
        for item in all_answerable:
            started = time.perf_counter()
            search(item["query"])
            latencies.append((time.perf_counter() - started) * 1000)

        def top_similarity(query: str) -> float:
            hits = search(query, 1)
            return hits[0].similarity if hits else 0.0

        dev_positive = [retrieved[i["query"]][0].similarity for i in all_answerable if i["split"] == "dev"]
        dev_negative = [top_similarity(i["query"]) for i in golden["unanswerable"] if i["split"] == "dev"]
        threshold, dev_balanced = tune_threshold(dev_positive, dev_negative)

        test_items = [i for i in all_answerable if i["split"] == "test"]
        vector_results = [(ranked_refs(retrieved[i["query"]]), set(i["relevant"])) for i in test_items]
        keyword_rankings = _keyword_baseline(db, [i["query"] for i in test_items])
        keyword_results = [
            (ranking, set(i["relevant"])) for ranking, i in zip(keyword_rankings, test_items, strict=True)
        ]

        settings.rag_min_similarity = threshold
        answered = citation_correct = 0
        grounding, generation_ms = [], []
        for item in test_items:
            hits = retrieved[item["query"]]
            started = time.perf_counter()
            result = generate_answer(item["query"], hits)
            generation_ms.append((time.perf_counter() - started) * 1000)
            if result.insufficient_evidence:
                continue
            answered += 1
            citation_correct += any(c["source_ref"] in item["relevant"] for c in result.citations)
            cited = {c["id"]: chunk.content for c, chunk in zip(result.citations, result.used_chunks, strict=True)}
            grounding.append(grounding_score(result.answer, cited))

        refused = 0
        negative_test = [i for i in golden["unanswerable"] if i["split"] == "test"]
        for item in negative_test:
            result = generate_answer(item["query"], search(item["query"]))
            refused += result.insufficient_evidence

    report = {
        "embedding_model": settings.embedding_model,
        "embedding_provider": settings.embedding_provider,
        "llm_provider": settings.llm_provider,
        "corpus": "synthetic knowledge articles",
        "threshold": {"selected": threshold, "dev_balanced_accuracy": dev_balanced},
        "retrieval_test": {
            "vector": _retrieval_scores(vector_results),
            "tfidf_keyword_baseline": _retrieval_scores(keyword_results),
        },
        "generation_test": {
            "answerable_queries": len(test_items),
            "answered": answered,
            "citation_correct_rate": round(citation_correct / answered, 4) if answered else None,
            "mean_grounding_score": round(statistics.mean(grounding), 4) if grounding else None,
            "unanswerable_queries": len(negative_test),
            "correctly_refused": refused,
            "refusal_rate": round(refused / len(negative_test), 4),
        },
        "latency_ms": {
            "retrieval_p50": round(float(np.percentile(latencies, 50)), 1),
            "retrieval_p95": round(float(np.percentile(latencies, 95)), 1),
            "generation_p50": round(float(np.percentile(generation_ms, 50)), 1),
            "generation_p95": round(float(np.percentile(generation_ms, 95)), 1),
        },
    }
    print(json.dumps(report, indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
