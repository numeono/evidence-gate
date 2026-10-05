import json
from pathlib import Path
from xml.etree import ElementTree

import httpx
import pytest
from pydantic import ValidationError

from evidence_gate.evaluate import run, score
from evidence_gate.report import write_reports
from evidence_gate.schema import Case, Configuration, Prediction, Suite


@pytest.fixture
def inputs(tmp_path):
    text = "Access expires after 90 days."
    doc = {"id": "access", "collection": "demo", "source": "synthetic://access", "text": text}
    case = {
        "id": "access",
        "question": "When does access expire?",
        "relevant_documents": ["access"],
        "expected_phrases": ["90 days"],
    }
    prediction = {
        "answer": text,
        "abstained": False,
        "latency_ms": 12.5,
        "retrieved": [
            {"document_id": "access", "chunk_id": "c1", "text": text, "start": 0, "end": len(text)}
        ],
        "citations": [
            {
                "document_id": "access",
                "chunk_id": "c1",
                "source": "synthetic://access",
                "quote": text,
                "start": 0,
                "end": len(text),
            }
        ],
    }
    corpus_path, suite_path, predictions_path = [
        tmp_path / f for f in ["corpus.jsonl", "suite.json", "predictions.json"]
    ]
    corpus_path.write_text(json.dumps(doc) + "\n")
    suite_path.write_text(json.dumps({"name": "unit fixture", "cases": [case]}))
    predictions_path.write_text(json.dumps({"access": prediction}))
    return {
        "corpus": {("demo", "access"): doc},
        "case": case,
        "prediction": prediction,
        "corpus_path": corpus_path,
        "suite_path": suite_path,
        "predictions_path": predictions_path,
    }


def evaluate(inputs, **kwargs):
    return run(
        inputs["suite_path"],
        inputs["corpus_path"],
        Configuration(),
        predictions_path=inputs["predictions_path"],
        **kwargs,
    )


def test_perfect_prediction(inputs):
    report = evaluate(inputs)
    assert report["passed"]
    assert report["metrics"]["recall_at_k"] == 1
    assert report["metrics"]["quote_integrity"] == 1
    assert report["metrics"]["p95_latency_ms"] == 12.5


def test_known_rank_and_duplicate_chunks(inputs):
    case = Case(**{**inputs["case"], "relevant_documents": ["access", "second"]})
    pred = inputs["prediction"]
    pred["retrieved"] = [
        {**pred["retrieved"][0], "document_id": "wrong", "chunk_id": "wrong"},
        pred["retrieved"][0],
        {**pred["retrieved"][0], "chunk_id": "c2"},
    ]
    metrics = score(case, Prediction(**pred), inputs["corpus"], 3)
    assert metrics["recall_at_k"] == 0.5
    assert metrics["mrr"] == 0.5
    assert metrics["collection_integrity"] == 0


@pytest.mark.parametrize(
    "field,value",
    [("quote", "Invented answer."), ("start", 1), ("chunk_id", "missing"), ("source", "wrong")],
)
def test_invalid_evidence_is_detected(inputs, field, value):
    pred = inputs["prediction"]
    pred["citations"][0][field] = value
    metrics = score(Case(**inputs["case"]), Prediction(**pred), inputs["corpus"], 3)
    assert metrics["quote_integrity"] == 0


def test_collection_text_mismatch_is_detected(inputs):
    inputs["prediction"]["retrieved"][0]["text"] = "A private version of this document."
    metrics = score(Case(**inputs["case"]), Prediction(**inputs["prediction"]), inputs["corpus"], 3)
    assert metrics["collection_integrity"] == 0


def test_refusal_is_not_free_relevance_credit(inputs):
    case = Case(id="missing", question="Unknown", should_abstain=True)
    prediction = Prediction(answer="", abstained=True, citations=[], retrieved=[], latency_ms=1)
    metrics = score(case, prediction, inputs["corpus"], 3)
    assert metrics["recall_at_k"] is None
    assert metrics["quote_integrity"] is None
    assert metrics["abstention_accuracy"] == 1


def test_missing_predictions_fail_instead_of_changing_denominator(inputs):
    inputs["predictions_path"].write_text("{}")
    with pytest.raises(ValueError, match="exactly"):
        evaluate(inputs)


def test_malformed_prediction_fails_case(inputs):
    inputs["predictions_path"].write_text(json.dumps({"access": {"answer": "missing fields"}}))
    report = evaluate(inputs)
    assert not report["passed"]
    assert report["case_count"] == 1
    assert report["metrics"]["success_rate"] == 0


def test_http_failure_remains_in_report(inputs, monkeypatch):
    def fail(*args, **kwargs):
        raise httpx.ConnectError("unreachable")

    monkeypatch.setattr(httpx.Client, "post", fail)
    report = run(
        inputs["suite_path"], inputs["corpus_path"], Configuration(), endpoint="http://test/query"
    )
    assert not report["passed"] and report["cases"][0]["error"] == "ConnectError"


def test_baseline_regression_with_absolute_gates_disabled(inputs, tmp_path):
    # This test isolates the relative gate: absolute minimums are explicitly empty.
    suite = json.loads(inputs["suite_path"].read_text())
    suite["minimums"] = {}
    inputs["suite_path"].write_text(json.dumps(suite))
    baseline = evaluate(inputs)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline))
    inputs["prediction"]["answer"] = "Different wording without the expected number."
    inputs["predictions_path"].write_text(json.dumps({"access": inputs["prediction"]}))
    candidate = evaluate(inputs, baseline=baseline_path)
    assert not candidate["passed"]
    assert candidate["deltas"]["answer_coverage"] == -1
    assert any("regression" in reason for reason in candidate["failures"])


def test_incompatible_baseline_rejected(inputs, tmp_path):
    baseline = evaluate(inputs)
    baseline["configuration"]["mode"] = "hybrid"
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(baseline))
    with pytest.raises(ValueError, match="different"):
        evaluate(inputs, baseline=path)


def test_report_escapes_untrusted_text_and_valid_junit(inputs, tmp_path):
    report = evaluate(inputs)
    report["cases"][0]["question"] = '<script>alert("x")</script>'
    report["passed"] = False
    report["failures"] = ["quote integrity failed"]
    write_reports(report, tmp_path / "out")
    page = (tmp_path / "out/report.html").read_text()
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    root = ElementTree.parse(tmp_path / "out/junit.xml").getroot()
    assert root.attrib["failures"] == "1"


@pytest.mark.parametrize(
    "change",
    [{"minimums": {"made_up": 0.9}}, {"minimums": {"recall_at_k": float("nan")}}, {"cases": []}],
)
def test_bad_suite_configuration_rejected(inputs, change):
    with pytest.raises(ValidationError):
        Suite(**{**json.loads(inputs["suite_path"].read_text()), **change})


def test_duplicate_cases_rejected(inputs):
    with pytest.raises(ValidationError, match="Duplicate"):
        Suite(name="duplicate", cases=[inputs["case"], inputs["case"]])


def test_unknown_or_empty_expected_phrases_rejected():
    with pytest.raises(ValidationError):
        Case(id="x", question="x", relevant_documents=["x"], expected_phrases=[""])


def test_invalid_latency_rejected(inputs):
    with pytest.raises(ValidationError):
        Prediction(**{**inputs["prediction"], "latency_ms": float("nan")})


def test_checked_in_demo_has_15_cases_and_passes():
    root = Path(__file__).parents[1] / "examples"
    result = run(
        root / "suite.json", root / "documents.jsonl", Configuration(), root / "predictions.json"
    )
    assert result["case_count"] == 15
    assert result["passed"], result["failures"]
