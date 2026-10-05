"""Record real HTTP responses for deterministic replay, including client latency."""

import argparse
import json
import time
from pathlib import Path

import httpx

parser = argparse.ArgumentParser()
parser.add_argument("--endpoint", default="http://127.0.0.1:8000/query")
parser.add_argument("--mode", choices=["lexical", "hybrid"], default="lexical")
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--suite", type=Path, default=Path(__file__).parents[1] / "examples/suite.json")
args = parser.parse_args()
suite = json.loads(args.suite.read_text())
predictions = {}
with httpx.Client(timeout=60) as client:
    for case in suite["cases"]:
        started = time.perf_counter()
        response = client.post(
            args.endpoint,
            json={
                "question": case["question"],
                "collection": case.get("collection", "demo"),
                "mode": args.mode,
            },
        )
        response.raise_for_status()
        prediction = response.json()
        prediction["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
        predictions[case["id"]] = prediction
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(predictions, indent=2) + "\n")
print(f"Recorded {len(predictions)} actual HTTP responses to {args.output}")
