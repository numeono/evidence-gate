import hashlib
import json
import math
import re
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .schema import QUALITY_METRICS, Case, Configuration, Prediction, Suite


def normalized(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def load_corpus(path: Path) -> dict[tuple[str, str], dict]:
    corpus = {}
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        doc = json.loads(line)
        if not all(
            isinstance(doc.get(k), str) and doc[k] for k in ["id", "collection", "text", "source"]
        ):
            raise ValueError("Corpus rows need nonempty string id, collection, text, and source")
        key = (doc["collection"], doc["id"])
        if key in corpus:
            raise ValueError(f"Duplicate corpus key: {key}")
        corpus[key] = doc
    return corpus


def score(case: Case, prediction: Prediction, corpus: dict, top_k: int) -> dict:
    relevant = set(case.relevant_documents)
    retrieved = prediction.retrieved[:top_k]
    found = {r.document_id for r in retrieved}
    answerable = not case.should_abstain
    recall = len(relevant & found) / len(relevant) if answerable else None
    mrr = (
        next((1 / i for i, r in enumerate(retrieved, 1) if r.document_id in relevant), 0.0)
        if answerable
        else None
    )
    cited = prediction.citations
    precision = (
        sum(c.document_id in relevant for c in cited) / len(cited)
        if cited
        else (0.0 if answerable else None)
    )
    valid_quotes = []
    by_chunk = {r.chunk_id: r for r in retrieved}
    for c in cited:
        doc = corpus.get((case.collection, c.document_id))
        hit = by_chunk.get(c.chunk_id)
        valid_quotes.append(
            bool(
                doc
                and hit
                and hit.document_id == c.document_id
                and c.source == doc["source"]
                and 0 <= c.start < c.end <= len(doc["text"])
                and doc["text"][c.start : c.end] == c.quote
                and hit.start <= c.start < c.end <= hit.end
                and c.quote in hit.text
            )
        )
    integrity = (
        sum(valid_quotes) / len(valid_quotes) if valid_quotes else (0.0 if answerable else None)
    )
    coverage = (
        sum(normalized(p) in normalized(prediction.answer) for p in case.expected_phrases)
        / len(case.expected_phrases)
        if answerable
        else None
    )
    safe = True
    for hit in prediction.retrieved:
        doc = corpus.get((case.collection, hit.document_id))
        if (
            not doc
            or not 0 <= hit.start < hit.end <= len(doc["text"])
            or doc["text"][hit.start : hit.end] != hit.text
        ):
            safe = False
    if any((case.collection, c.document_id) not in corpus for c in cited):
        safe = False
    return {
        "recall_at_k": recall,
        "mrr": mrr,
        "citation_precision": precision,
        "quote_integrity": integrity,
        "answer_coverage": coverage,
        "abstention_accuracy": float(prediction.abstained == case.should_abstain),
        "collection_integrity": float(safe),
        "success_rate": 1.0,
    }


def run(
    suite_path: Path,
    corpus_path: Path,
    config: Configuration,
    predictions_path: Path | None = None,
    endpoint: str | None = None,
    baseline: Path | None = None,
) -> dict:
    suite = Suite.model_validate_json(suite_path.read_text())
    corpus = load_corpus(corpus_path)
    for case in suite.cases:
        if any((case.collection, d) not in corpus for d in case.relevant_documents):
            raise ValueError(f"Case {case.id} references a document outside its collection")
    fingerprint = hashlib.sha256(
        suite_path.read_bytes() + b"\0" + corpus_path.read_bytes()
    ).hexdigest()
    if (predictions_path is None) == (endpoint is None):
        raise ValueError("Choose exactly one of predictions or endpoint")
    replay = None
    if predictions_path is not None:
        replay = json.loads(predictions_path.read_text())
        if not isinstance(replay, dict) or set(replay) != {c.id for c in suite.cases}:
            raise ValueError("Predictions must contain exactly the suite case IDs")
    previous = None
    if baseline is not None:
        previous = json.loads(baseline.read_text())
        if (
            previous.get("fingerprint") != fingerprint
            or previous.get("configuration") != config.model_dump()
        ):
            raise ValueError("Baseline uses a different suite, corpus, or configuration")
        if set(previous.get("metrics", {})) != QUALITY_METRICS | {"p95_latency_ms"}:
            raise ValueError("Baseline metric schema is incompatible")
        if any(
            v is not None and (not isinstance(v, (int, float)) or not math.isfinite(v))
            for v in previous["metrics"].values()
        ):
            raise ValueError("Baseline metrics must be finite numbers or null")
    rows = []
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        for case in suite.cases:
            started = time.perf_counter()
            try:
                if replay is not None:
                    payload = replay[case.id]
                else:
                    response = client.post(
                        endpoint,
                        json={
                            "question": case.question,
                            "collection": case.collection,
                            **config.model_dump(),
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                    payload["latency_ms"] = (time.perf_counter() - started) * 1000
                prediction = Prediction.model_validate(payload)
                metrics = score(case, prediction, corpus, config.top_k)
                rows.append(
                    {
                        "id": case.id,
                        "question": case.question,
                        "tags": case.tags,
                        "metrics": metrics,
                        "latency_ms": prediction.latency_ms,
                        "prediction": prediction.model_dump(),
                        "error": None,
                    }
                )
            except (ValueError, TypeError, httpx.HTTPError) as exc:
                # A failed request is a failed case, never dropped from the denominator.
                metrics = dict.fromkeys(QUALITY_METRICS, 0.0)
                rows.append(
                    {
                        "id": case.id,
                        "question": case.question,
                        "tags": case.tags,
                        "metrics": metrics,
                        "latency_ms": (time.perf_counter() - started) * 1000,
                        "prediction": None,
                        "error": type(exc).__name__,
                    }
                )
    metrics = {}
    for name in sorted(QUALITY_METRICS):
        values = [r["metrics"][name] for r in rows if r["metrics"][name] is not None]
        metrics[name] = statistics.mean(values) if values else None
    latencies = sorted(r["latency_ms"] for r in rows)
    metrics["p95_latency_ms"] = latencies[math.ceil(0.95 * len(latencies)) - 1]
    failures = []
    if any(r["error"] for r in rows):
        failures.append("One or more cases failed to return a valid prediction")
    for name, minimum in suite.minimums.items():
        if metrics[name] is None:
            failures.append(f"{name}: no applicable cases for configured gate")
        elif metrics[name] < minimum:
            failures.append(f"{name}: {metrics[name]:.4f} < {minimum:.4f}")
    if suite.max_p95_ms is not None and metrics["p95_latency_ms"] > suite.max_p95_ms:
        failures.append(f"p95 latency exceeds {suite.max_p95_ms} ms")
    deltas = {}
    if previous:
        for name in sorted(QUALITY_METRICS):
            old, new = previous["metrics"][name], metrics[name]
            if old is not None and new is not None:
                deltas[name] = new - old
                if deltas[name] < -suite.max_regression - 1e-12:
                    failures.append(
                        f"{name}: regression {deltas[name]:.4f} exceeds {suite.max_regression}"
                    )
    return {
        "schema_version": 1,
        "suite": suite.name,
        "fingerprint": fingerprint,
        "created_at": datetime.now(UTC).isoformat(),
        "configuration": config.model_dump(),
        "transport": "replay" if replay is not None else "http",
        "case_count": len(rows),
        "metrics": metrics,
        "deltas": deltas,
        "passed": not failures,
        "failures": failures,
        "cases": rows,
    }
