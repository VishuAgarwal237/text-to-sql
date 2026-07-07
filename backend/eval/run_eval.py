"""Run the text-to-SQL eval across one or more models.

For each model, runs the full LangGraph pipeline on every eval question, scores it with the
execution-accuracy + valid-SQL scorers, and records per-case results (score, category, cost,
latency, SQL). Results are written to eval/results/<model-key>.json for the report generator.

If BRAINTRUST_API_KEY is set, each model is ALSO run as a Braintrust experiment so the runs are
comparable side-by-side in the Braintrust UI. Without a key, the local JSON results still power
report.py — the eval works fully offline (use LLM_BACKEND=stub to run with no LLM key at all).

Usage:
    python eval/run_eval.py                       # models from $EVAL_MODELS or the default 3
    EVAL_MODELS=claude-sonnet-5 python eval/run_eval.py
    LLM_BACKEND=stub python eval/run_eval.py       # offline, deterministic
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.graph import answer_question  # noqa: E402
from app.llm import MODEL_REGISTRY  # noqa: E402
from eval import scorers  # noqa: E402

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"
DEFAULT_MODELS = ["fireworks-llama-70b", "claude-haiku-4-5", "claude-sonnet-5"]


def _models() -> list[str]:
    env = os.environ.get("EVAL_MODELS")
    return [m.strip() for m in env.split(",")] if env else DEFAULT_MODELS


def run_case(question: str, gold_sql: str, model_key: str) -> dict:
    """Run the pipeline for one question and score it."""
    out = answer_question(question, model=model_key)
    pred_sql = out.get("sql", "")
    exec_res = scorers.execution_match(pred_sql, gold_sql)
    return {
        "question": question,
        "pred_sql": pred_sql,
        "gold_sql": gold_sql,
        "execution_accuracy": exec_res["score"],
        "valid_sql": scorers.is_valid_sql(pred_sql),
        "exec_reason": exec_res["reason"],
        "status": out.get("status"),
        "retries": out.get("retries", 0),
        "cost_usd": out.get("cost_usd", 0.0),
        "wall_clock_s": out.get("wall_clock_s", 0.0),
        "llm_seconds": out.get("llm_seconds", 0.0),
    }


def run_model(model_key: str, cases: list[dict], categories: dict) -> dict:
    print(f"\n=== Model: {model_key} ===")
    results = []
    for c in cases:
        r = run_case(c["question"], c["sql"], model_key)
        r["category"] = categories.get(c["question"], "uncategorized")
        results.append(r)
        mark = "✓" if r["execution_accuracy"] == 1.0 else "✗"
        print(f"  {mark} [{r['category']}] {c['question'][:55]}")

    _maybe_braintrust(model_key, cases, categories)

    n = len(results)
    acc = sum(r["execution_accuracy"] for r in results) / n if n else 0.0
    valid = sum(r["valid_sql"] for r in results) / n if n else 0.0
    summary = {
        "model": model_key,
        "model_id": MODEL_REGISTRY.get(model_key, model_key),
        "n": n,
        "execution_accuracy": round(acc, 4),
        "valid_sql_rate": round(valid, 4),
        "avg_cost_usd": round(sum(r["cost_usd"] for r in results) / n, 6) if n else 0.0,
        "avg_latency_s": round(sum(r["wall_clock_s"] for r in results) / n, 3) if n else 0.0,
        "results": results,
    }
    print(f"  -> execution accuracy {acc:.0%} | valid SQL {valid:.0%}")
    return summary


def _maybe_braintrust(model_key: str, cases: list[dict], categories: dict) -> None:
    """Log this model's run as a Braintrust experiment (side-by-side comparison), if configured."""
    if not os.environ.get("BRAINTRUST_API_KEY"):
        return
    try:
        from braintrust import Eval
    except ImportError:
        return

    def task(question: str):
        return answer_question(question, model=model_key).get("sql", "")

    def exec_acc(input, output, expected):  # noqa: A002
        return scorers.execution_match(output, expected["sql"])["score"]

    def valid(output, **_):
        return scorers.is_valid_sql(output)

    Eval(
        "MelodyStream Text-to-SQL",
        data=[
            {"input": c["question"],
             "expected": {"sql": c["sql"]},
             "metadata": {"category": categories.get(c["question"], "uncategorized")}}
            for c in cases
        ],
        task=task,
        scores=[exec_acc, valid],
        experiment_name=f"{model_key}",
    )
    print(f"  (logged Braintrust experiment '{model_key}')")


def main() -> None:
    cases = json.loads((HERE / "evaluation_data.json").read_text())
    categories = json.loads((HERE / "categories.json").read_text())
    RESULTS_DIR.mkdir(exist_ok=True)

    for model_key in _models():
        summary = run_model(model_key, cases, categories)
        out_path = RESULTS_DIR / f"{model_key}.json"
        out_path.write_text(json.dumps(summary, indent=2, default=str))
        print(f"  wrote {out_path}")

    print("\nDone. Generate the report with: python eval/report.py")


if __name__ == "__main__":
    main()
