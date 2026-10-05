# Evidence Gate

[![checks](https://github.com/numeono/evidence-gate/actions/workflows/ci.yml/badge.svg)](https://github.com/numeono/evidence-gate/actions/workflows/ci.yml)

Turn a small, labeled question set into a repeatable quality gate for document-answer
systems. Replay saved predictions or query an HTTP API; get a JSON result, a readable HTML
report, and JUnit output. Failed cases count against the result, and a regression can fail CI.

**Status:** personal engineering prototype, created October 2026. Includes 15 synthetic
workplace-document cases and a companion API integration with
[Margin Notes](https://github.com/numeono/margin-notes). No paid services required.

## Quick start: replay a recorded run

```sh
git clone https://github.com/numeono/evidence-gate.git
cd evidence-gate
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
evidence-gate --suite examples/suite.json --corpus examples/documents.jsonl \
  --predictions examples/predictions.json --output local-results/replay
```

Open `local-results/replay/report.html`. The checked-in predictions are an actual local
Margin Notes run, not hardcoded scores. Replay verifies the evaluator and saved evidence;
it does not exercise a live model or endpoint.

## Evaluate a live system

Start Margin Notes using its README, then:

```sh
evidence-gate --suite examples/suite.json --corpus examples/documents.jsonl \
  --endpoint http://127.0.0.1:8000/query --output local-results/live
evidence-gate --suite examples/suite.json --corpus examples/documents.jsonl \
  --endpoint http://127.0.0.1:8000/query --baseline local-results/live/report.json \
  --output local-results/candidate
```

To evaluate semantic retrieval, start a semantic-enabled Margin Notes instance and pass
`--mode hybrid`. `--answerer ollama` exercises its local model evidence selector. Baselines
must use the same configuration and the exact same suite/corpus fingerprint; compare different
retrieval modes side by side, not through a same-configuration regression gate.

## Metrics and their limits

| Metric | Definition |
| --- | --- |
| Recall@k | Fraction of expected document IDs retrieved in the first k chunks; duplicate chunks do not inflate recall |
| MRR | Reciprocal rank of the first relevant chunk |
| Citation precision | Fraction of cited document IDs labeled relevant |
| Quote integrity | Fraction of citations matching an exact source span, source URI, and retrieved chunk |
| Answer coverage | Fraction of expected phrases present after case/punctuation normalization |
| Abstention accuracy | Agreement with the expected answer/refusal decision |
| Collection integrity | All retrieved evidence matches the source text in the requested collection |
| Success rate | Fraction of cases returning a valid response |
| p95 latency | Nearest-rank 95th percentile; client wall time for HTTP, recorded time for replay |

Retrieval, citation, and coverage metrics are macro-averaged over answerable cases. Explicit
abstention cases have no relevance labels; empty citations are not given free quality points.
Request and schema failures count as zero and always fail the run. A configured gate without
applicable cases fails instead of silently passing.

These are transparent diagnostics, not an LLM judge. A verbatim quote can be irrelevant;
phrase coverage does not prove correctness; document labels do not capture all valid answers.
Collection integrity validates returned data against this corpus, not the server's access-control
implementation. Use human review and independently labeled held-out data before production.

## Gates and reports

Configure `minimums`, `max_regression` (absolute metric decrease), and optional `max_p95_ms`
in the suite JSON. Default gates require exact quote/collection integrity and successful
responses, plus minimum retrieval, answer coverage, and citation relevance.

- Exit `0`: all configured gates pass.
- Exit `1`: quality gate or request failure; reports still written.
- Exit `2`: invalid input or incompatible baseline.

Reports include configuration, UTC timestamp, SHA-256 fixture fingerprint, per-case predictions,
errors, metric deltas, and failure reasons. HTML escapes all source text and contains no external
scripts. JUnit represents the suite-level gates; individual case diagnostics are in JSON/HTML.
Reports may contain your source excerpts, so review them before publishing.

The HTTP request contract is `{question, collection, top_k, mode, answerer}`. Responses need
`answer`, `abstained`, `citations`, `retrieved`, and `latency_ms`; see `schema.py` and the example
predictions for exact fields. Unknown response fields are ignored for adapter compatibility.
An adapter for another application can translate its response into this contract.

## Development

```sh
ruff check src tests
pytest -q
```

Tests cover known-rank metric calculations, duplicate retrievals, fabricated quotes, collection
leaks, failed requests, invalid inputs, HTML escaping, and baseline regressions. CI repeats
the saved evaluation and checks that deliberately corrupted evidence fails the gate.

See [validation notes](docs/VALIDATION.md) for actual test and evaluation results. Synthetic
fixture scores are development checks, not generalization measurements.

MIT license. Built with AI coding assistance; fixtures, scoring rules, and limitations are
included so every reported result can be inspected.

