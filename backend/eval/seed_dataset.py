"""Upload evaluation_data.json to a Braintrust dataset.

Each record: input = question; expected = {sql, expected_result}; metadata = {category}.
Requires BRAINTRUST_API_KEY. No-op with a clear message if the key/SDK is absent.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATASET_NAME = os.environ.get("BRAINTRUST_DATASET", "chinook-text-to-sql")


def main() -> None:
    if not os.environ.get("BRAINTRUST_API_KEY"):
        print("BRAINTRUST_API_KEY not set — skipping dataset upload. "
              "Set it to push the eval set to Braintrust.")
        return
    try:
        import braintrust
    except ImportError:
        print("braintrust not installed: pip install -e .")
        return

    cases = json.loads((HERE / "evaluation_data.json").read_text())
    categories = json.loads((HERE / "categories.json").read_text())

    dataset = braintrust.init_dataset(project="MelodyStream Text-to-SQL", name=DATASET_NAME)
    for c in cases:
        dataset.insert(
            input=c["question"],
            expected={"sql": c["sql"], "expected_result": c.get("expected_result")},
            metadata={"category": categories.get(c["question"], "uncategorized")},
        )
    print(f"Uploaded {len(cases)} cases to Braintrust dataset '{DATASET_NAME}'.")
    print(dataset.summarize())


if __name__ == "__main__":
    main()
