"""Text-to-SQL evaluation harness.

Loads the ground-truth dataset (`evaluation_data.json`: question / gold SQL / expected
rows), produces a candidate result for each question, and scores it against the expected
rows using the order-insensitive, float-tolerant, unicode-normalized multiset comparison in
`compare.py`.

Two modes, selected automatically:

  - **pipeline** — if the LangGraph pipeline is importable (`app.graph.run_pipeline`), each
    question is answered end-to-end (NL -> SQL -> execute) and the produced rows are scored.
    This is the real accuracy number.
  - **self-check** (fallback, used today) — the pipeline doesn't exist yet, so we execute the
    *gold* SQL through the read-only core (`app.db.run_query`) and score its rows against the
    expected rows. This validates the dataset, the DB, and the scorer itself: every case
    should pass, and any failure points at a dataset/DB drift rather than a model error.

Usage:
    python -m eval.run_eval            # auto-detect mode, run all cases
    python eval/run_eval.py --json     # machine-readable summary on stdout

Exit code is non-zero if any case fails, so this doubles as a CI check.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

# Make `app` importable whether run as `python -m eval.run_eval` (from backend/) or as a
# script (python eval/run_eval.py): backend/ is this file's parent's parent.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app import db  # noqa: E402  (path set up above)
from eval.compare import compare_results  # noqa: E402

DATASET_PATH = Path(__file__).resolve().parent / "evaluation_data.json"

# A predictor maps (question, gold_sql) -> (rows, executed_sql). Gold SQL is passed so the
# self-check predictor can run it; the real pipeline predictor ignores it.
Predictor = Callable[[str, str], tuple[list[dict[str, Any]], str]]


def _self_check_predictor(question: str, gold_sql: str) -> tuple[list[dict[str, Any]], str]:
    """Fallback: run the gold SQL itself. Proves dataset+DB+scorer are consistent."""
    result = db.run_query(gold_sql)
    return result["rows"], gold_sql


def _get_predictor() -> tuple[Predictor, str]:
    """Return (predictor, mode). Prefer the real pipeline; fall back to self-check."""
    try:
        from app.graph import run_pipeline  # type: ignore
    except Exception:
        return _self_check_predictor, "self-check"

    def _pipeline_predictor(question: str, gold_sql: str) -> tuple[list[dict[str, Any]], str]:
        out = run_pipeline(question)  # expected to return {"sql": ..., "rows": [...]}
        return out.get("rows", []), out.get("sql", "")

    return _pipeline_predictor, "pipeline"


def load_dataset(path: Path = DATASET_PATH) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def run(dataset: list[dict[str, Any]], predictor: Predictor) -> list[dict[str, Any]]:
    """Score every case. Returns one record per case with the comparison verdict."""
    records = []
    for i, case in enumerate(dataset, 1):
        question = case["question"]
        gold_sql = case["sql"]
        expected = case["expected_result"]
        rec: dict[str, Any] = {"index": i, "question": question}
        try:
            rows, executed_sql = predictor(question, gold_sql)
            cmp = compare_results(expected, rows)
            rec.update(
                passed=cmp.passed,
                detail=cmp.summary(),
                executed_sql=executed_sql,
                error=None,
            )
        except Exception as exc:  # a crash (bad SQL, exec error) is a failed case, not a stop
            rec.update(passed=False, detail=f"ERROR: {exc}", executed_sql=None, error=str(exc))
        records.append(rec)
    return records


def print_report(records: list[dict[str, Any]], mode: str) -> float:
    total = len(records)
    passed = sum(1 for r in records if r["passed"])
    accuracy = passed / total if total else 0.0

    print(f"\nText-to-SQL eval — mode: {mode}\n" + "=" * 60)
    for r in records:
        mark = "PASS" if r["passed"] else "FAIL"
        q = r["question"] if len(r["question"]) <= 62 else r["question"][:59] + "..."
        print(f"[{mark}] {r['index']:>2}. {q}")
        if not r["passed"]:
            print(f"        -> {r['detail']}")
    print("=" * 60)
    print(f"Accuracy: {passed}/{total} = {accuracy:.1%}")
    if mode == "self-check" and passed < total:
        print(
            "NOTE: self-check failures mean the gold SQL and the loaded DB disagree "
            "(dataset/DB drift), not a model error."
        )
    return accuracy


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the text-to-SQL evaluation.")
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    dataset = load_dataset(args.dataset)
    predictor, mode = _get_predictor()
    records = run(dataset, predictor)

    if args.json:
        passed = sum(1 for r in records if r["passed"])
        print(json.dumps(
            {"mode": mode, "total": len(records), "passed": passed,
             "accuracy": passed / len(records) if records else 0.0, "cases": records},
            ensure_ascii=False, indent=2,
        ))
    else:
        print_report(records, mode)

    all_passed = all(r["passed"] for r in records)
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
