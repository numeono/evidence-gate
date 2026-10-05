# Validation

Run on October 5, 2026, on an Apple M1 Mac mini using Python 3.13.15.

- `ruff check src tests scripts`: passed.
- `pytest -q`: 21 passed.
- Captured actual HTTP responses from local Margin Notes instances in lexical and hybrid modes.
- Both modes passed all gates on the 15-case synthetic smoke suite. All eight quality
  aggregates were 1.0 on that small fixture.
- Deliberately replacing one cited quote with invented text lowered quote integrity to
  0.9167 and caused the CLI to exit with status 1, as intended.
- Baseline regression detection, request errors, duplicate retrievals, invalid citations,
  HTML escaping, missing predictions, and invalid metric configuration have dedicated tests.

## Recorded reports

| Run | Gates | Recall@3 | Answer coverage | Abstention accuracy | p95 client latency |
| --- | --- | ---: | ---: | ---: | ---: |
| [Lexical smoke](results/lexical/report.json) | Pass | 1.000 | 1.000 | 1.000 | 13.906 ms |
| [Hybrid smoke](results/hybrid/report.json) | Pass | 1.000 | 1.000 | 1.000 | 25.422 ms |
| [Corrupted quote](results/corrupted/report.json) | Fail, expected | 1.000 | 1.000 | 1.000 | replay |
| [Lexical challenge](results/challenge-lexical/report.json) | Fail | 0.667 | 0.500 | 0.571 | 4.262 ms |
| [Hybrid challenge](results/challenge-hybrid/report.json) | Fail | 0.667 | 0.667 | 0.714 | 10.818 ms |

Each folder also has self-contained HTML and JUnit reports. The latency figures are one local
run on tiny fixtures, without a load generator; they are not service-level objectives. The
hybrid measurement uses a warmed model, while startup/model download are excluded.

The challenge cases were written separately before their first run. They demonstrate that
the gate catches weaknesses hidden by the easy smoke suite. Neither retrieval mode passes
the challenge gates, and no quality thresholds were relaxed to make it pass. These fixtures
are authored development examples, not an independently held-out benchmark.

## Reproduce

```sh
# Expected success
evidence-gate --suite examples/suite.json --corpus examples/documents.jsonl \
  --predictions examples/predictions.json --output local-results/replay

# Expected failure on harder language (exit 1)
evidence-gate --suite examples/challenge-suite.json --corpus examples/documents.jsonl \
  --predictions examples/challenge-hybrid.json --mode hybrid --output local-results/challenge

# Expected failure for a fabricated quote (exit 1)
python scripts/corrupt_predictions.py
evidence-gate --suite examples/suite.json --corpus examples/documents.jsonl \
  --predictions local-results/corrupted.json --output local-results/corrupted
```

For fresh measurements, run Margin Notes and use `--endpoint`, or record with
`python scripts/record_predictions.py --endpoint http://127.0.0.1:8000/query --output local-results/fresh.json`.
Pass `--suite examples/challenge-suite.json` and/or `--mode hybrid` as appropriate.

`environment-py313.txt` records the exact local packages; it is not a portable lockfile.
GitHub Actions reruns the evaluator's tests, the saved passing fixture, and the intentional
corruption check. It does not download models or run live inference.

