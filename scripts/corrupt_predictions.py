"""Create an intentionally invalid candidate to demonstrate a failing CI gate."""

import json
from pathlib import Path

root = Path(__file__).parents[1]
predictions = json.loads((root / "examples/predictions.json").read_text())
predictions["travel-deadline"]["citations"][0]["quote"] = (
    "Invented evidence that was never in the source."
)
output = root / "local-results/corrupted.json"
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(predictions, indent=2) + "\n")
