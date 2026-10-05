import argparse
import json
from pathlib import Path

from .evaluate import run
from .report import write_reports
from .schema import Configuration


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate a document-answer API and enforce regression gates"
    )
    parser.add_argument("--suite", required=True, type=Path)
    parser.add_argument("--corpus", required=True, type=Path)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--endpoint", help="POST query endpoint, e.g. http://127.0.0.1:8000/query")
    source.add_argument("--predictions", type=Path, help="Recorded predictions keyed by case ID")
    parser.add_argument("--output", type=Path, default=Path("local-results/latest"))
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--mode", choices=["lexical", "hybrid"], default="lexical")
    parser.add_argument("--answerer", choices=["extractive", "ollama"], default="extractive")
    args = parser.parse_args()
    try:
        config = Configuration(top_k=args.top_k, mode=args.mode, answerer=args.answerer)
        report = run(
            args.suite, args.corpus, config, args.predictions, args.endpoint, args.baseline
        )
        write_reports(report, args.output)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f"Invalid evaluation input: {exc}\n")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "cases": report["case_count"],
                "metrics": report["metrics"],
                "failures": report["failures"],
            },
            indent=2,
        )
    )
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
