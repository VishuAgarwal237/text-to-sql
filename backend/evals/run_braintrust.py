"""Braintrust eval runner for the text-to-SQL pipeline.

Run from `backend/`:

    BRAINTRUST_API_KEY=... OPENAI_API_KEY=... python -m evals.run_braintrust

Run against labeled data and/or multiple models:

    EVAL_DATA_PATH=evaluation_data.json \
    LLM_CHAT_MODELS=gpt-4o-mini,gpt-4.1-mini \
    python -m evals.run_braintrust

Prereqs:
  - `python -m app.metadata.generate` has created `data/schema_metadata.json`
  - `CHINOOK_DB_PATH` points at a readable Chinook SQLite DB, unless using the default path

Scoring intentionally avoids exact SQL string matching. Equivalent SQL can be valid, so the eval
scores behavior: executable SQL, result equivalence against trusted gold SQL, required semantic
fragments for metrics/joins/aggregations, expected filters, chart choice, and clarification/safety
behavior for non-answerable requests.

Top-level metrics:
  - `answer_accuracy`: full-case correctness across SQL and non-SQL cases.
  - `sql_precision`: when the system chooses to emit SQL, whether that SQL/result is correct.

Labeled data format:

    [
      {
        "input": "Top 5 genres by revenue",
        "expected": {
          "gold_sql": "SELECT ...",
          "expected_rows": [{"Name": "Rock", "Revenue": 826.65}]
        }
      }
    ]

If `expected_rows` is omitted but `gold_sql` is present, the scorer executes `gold_sql` and uses
that as the trusted result. If both are present, `expected_rows` wins.
"""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from typing import Any

import braintrust
from braintrust import Eval, current_span

from app import db
from app.observability import DEFAULT_PROJECT
from app import llm
from app.nodes import run_pipeline
from app.resources import build_resources

DEFAULT_CASES_PATH = Path(__file__).with_name("text_to_sql_cases.jsonl")
DEFAULT_EVALUATION_DATA_PATH = Path(__file__).with_name("evaluation_data.json")


def _default_cases_path() -> Path:
    explicit = os.environ.get("EVAL_DATA_PATH")
    if explicit:
        return Path(explicit)
    if DEFAULT_EVALUATION_DATA_PATH.exists():
        return DEFAULT_EVALUATION_DATA_PATH
    return DEFAULT_CASES_PATH


def _normalize_case(case: dict[str, Any]) -> dict[str, Any]:
    """Accept common labeled-data shapes and normalize to Braintrust EvalCase dicts."""
    if "input" not in case:
        for key in ("question", "prompt", "natural_language_query"):
            if key in case:
                case["input"] = case[key]
                break
    expected = case.get("expected", {})
    if not expected:
        expected = {}
        for src, dst in (
            ("gold_sql", "gold_sql"),
            ("sql", "gold_sql"),
            ("expected_sql", "gold_sql"),
            ("expected_rows", "expected_rows"),
            ("rows", "expected_rows"),
            ("must_use_tables", "must_use_tables"),
            ("chart_type", "chart_type"),
        ):
            if src in case:
                expected[dst] = case[src]
    case["expected"] = expected
    if "input" not in case:
        raise ValueError(f"Eval case is missing input/question: {case}")
    return {"input": case["input"], "expected": case["expected"]}


def load_cases(path: Path | None = None) -> list[dict[str, Any]]:
    """Load JSON array, `{cases: [...]}`, `{data: [...]}`, or JSONL eval cases."""
    path = path or _default_cases_path()
    text = path.read_text().strip()
    if not text:
        return []
    if text[0] in "[{":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            if isinstance(parsed, dict):
                parsed = parsed.get("cases") or parsed.get("data") or parsed.get("examples") or [parsed]
            return [_normalize_case(dict(case)) for case in parsed]
    return [_normalize_case(json.loads(line)) for line in text.splitlines() if line.strip()]


def _answer(output: dict[str, Any]) -> dict[str, Any]:
    return output.get("answer", output)


def make_task(model: str | None):
    """Build a model-specific task so one eval run can compare multiple LLMs."""

    def complete(system: str, user: str) -> str:
        return llm.complete(system, user, model=model)

    res = build_resources(complete_fn=complete)

    def task(question: str) -> dict[str, Any]:
        state = run_pipeline(question, res)
        answer = state["answer"]
        current_span().log(
            input=question,
            output=answer,
            metadata={
                "model": model or llm.CHAT_MODEL,
                "trace": state.get("trace", []),
                "sql": answer.get("sql"),
                "row_count": answer.get("row_count"),
                "truncated": answer.get("truncated"),
                "chart_type": answer.get("chart_type"),
                "error": answer.get("error"),
            },
        )
        return answer

    return task


def sql_valid(_input, output, expected) -> int:
    answer = _answer(output)
    if expected.get("must_not_generate_sql"):
        return int(not answer.get("sql"))
    return int(bool(answer.get("sql")) and not answer.get("error"))


def expected_tables_used(_input, output, expected) -> float:
    expected_tables = set(expected.get("must_use_tables", []))
    if not expected_tables:
        return 1.0
    sql = (_answer(output).get("sql") or "").lower()
    hits = sum(1 for table in expected_tables if table.lower() in sql)
    return hits / len(expected_tables)


def expected_filters_used(_input, output, expected) -> float:
    filters = expected.get("filters", {})
    if not filters:
        return 1.0
    sql = (_answer(output).get("sql") or "").lower()
    hits = 0
    for column, value in filters.items():
        if column.lower() in sql and str(value).lower() in sql:
            hits += 1
    return hits / len(filters)


def chart_type_match(_input, output, expected) -> int:
    expected_chart = expected.get("chart_type")
    if not expected_chart:
        return 1
    return int(_answer(output).get("chart_type") == expected_chart)


def expected_behavior(_input, output, expected) -> int:
    """Score router-level behavior for clarification/unsupported/safety cases."""
    behavior = expected.get("behavior")
    if not behavior:
        return 1
    answer = _answer(output)
    if behavior == "analytical_sql":
        return int(answer.get("kind") == "analytical_sql" and bool(answer.get("sql")))
    if behavior == "no_sql":
        return int(not answer.get("sql") and answer.get("kind") != "analytical_sql")
    return int(answer.get("kind") == behavior)


def _norm_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", (sql or "").lower()).strip()


def required_sql_semantics(_input, output, expected) -> float:
    """Check required SQL fragments for metrics, joins, aggregation, ordering, and limits.

    This is deliberately not an exact SQL match. Cases can specify only the semantic fragments
    that matter, e.g. `sum(`, `unitprice * quantity`, `group by`, or a required join predicate.
    """
    required = expected.get("required_sql_contains", [])
    if not required:
        return 1.0
    sql = _norm_sql(_answer(output).get("sql") or "")
    hits = 0
    for fragment in required:
        if _norm_sql(fragment) in sql:
            hits += 1
    return hits / len(required)


def _round_float(value: float) -> float:
    return round(value, 6)


def _norm_value(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return str(value)
        return _round_float(value)
    if isinstance(value, int):
        return value
    if value is None:
        return None
    text = str(value)
    try:
        return _round_float(float(text))
    except ValueError:
        return text


def _rows_as_value_tuples(result: dict[str, Any]) -> list[tuple[Any, ...]]:
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    return [tuple(_norm_value(row.get(col)) for col in columns) for row in rows]


def _expected_rows_as_value_tuples(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    if not rows:
        return []
    columns = list(rows[0])
    return [tuple(_norm_value(row.get(col)) for col in columns) for row in rows]


def result_matches_gold(_input, output, expected) -> int:
    """Compare generated results to labeled expected rows or trusted gold SQL results.

    Column aliases may differ across equivalent SQL, so comparison is value-based using column
    order. Ordering still matters when the gold query orders rows; unordered-result cases can set
    `"ordered": false`.
    """
    gold_sql = expected.get("gold_sql")
    expected_rows = expected.get("expected_rows")
    if expected_rows is None and not gold_sql:
        return 1
    answer = _answer(output)
    if not answer.get("sql") or answer.get("error"):
        return 0
    try:
        generated = db.run_query(answer["sql"], max_rows=expected.get("max_rows", 1000))
        if expected_rows is not None:
            gold_rows = _expected_rows_as_value_tuples(expected_rows)
        else:
            gold = db.run_query(gold_sql, max_rows=expected.get("max_rows", 1000))
            gold_rows = _rows_as_value_tuples(gold)
    except Exception:
        return 0
    generated_rows = _rows_as_value_tuples(generated)
    if expected.get("ordered", True):
        return int(generated_rows == gold_rows)
    return int(sorted(generated_rows) == sorted(gold_rows))


def safety_no_sql(_input, output, expected) -> int:
    if not expected.get("must_not_generate_sql"):
        return 1
    answer = _answer(output)
    return int(not answer.get("sql"))


def answer_accuracy(input_, output, expected) -> int:
    """Overall case accuracy.

    For analytical cases, the generated SQL must be valid and match expected rows/gold SQL when
    labels exist. For no-SQL cases, the system must avoid generating SQL and route correctly.
    This is the metric to quote as "accuracy" in interviews and reports.
    """
    if expected.get("must_not_generate_sql"):
        return int(
            expected_behavior(input_, output, expected)
            and safety_no_sql(input_, output, expected)
        )

    checks = [
        sql_valid(input_, output, expected),
        expected_tables_used(input_, output, expected),
        expected_filters_used(input_, output, expected),
        required_sql_semantics(input_, output, expected),
        result_matches_gold(input_, output, expected),
    ]
    return int(all(score == 1 for score in checks))


def sql_precision(input_, output, expected) -> float | None:
    """Precision over SQL attempts.

    Precision answers: "When the agent emits SQL, how often is that SQL correct?" Non-SQL cases
    where the system correctly emits no SQL are excluded from the denominator by returning None.
    If it emits SQL for a no-SQL/safety case, that is a false positive and scores 0.
    """
    answer = _answer(output)
    emitted_sql = bool(answer.get("sql"))
    if not emitted_sql and expected.get("must_not_generate_sql"):
        return None
    if emitted_sql and expected.get("must_not_generate_sql"):
        return 0.0
    if not emitted_sql:
        return None
    return float(
        sql_valid(input_, output, expected)
        and expected_tables_used(input_, output, expected) == 1
        and expected_filters_used(input_, output, expected) == 1
        and required_sql_semantics(input_, output, expected) == 1
        and result_matches_gold(input_, output, expected) == 1
    )


def main() -> None:
    braintrust.auto_instrument()
    path = _default_cases_path()
    cases = load_cases(path)
    models = [
        m.strip()
        for m in os.environ.get("LLM_CHAT_MODELS", os.environ.get("LLM_CHAT_MODEL", llm.CHAT_MODEL)).split(",")
        if m.strip()
    ]
    scorers = [
        answer_accuracy,
        sql_precision,
        expected_behavior,
        sql_valid,
        expected_tables_used,
        expected_filters_used,
        required_sql_semantics,
        result_matches_gold,
        chart_type_match,
        safety_no_sql,
    ]
    for model in models:
        safe_model = re.sub(r"[^A-Za-z0-9_.-]+", "-", model)
        Eval(
            DEFAULT_PROJECT,
            experiment_name=f"text-to-sql-agent-flow-{safe_model}",
            data=cases,
            task=make_task(model),
            scores=scorers,
            metadata={"suite": path.name, "model": model, "case_count": len(cases)},
        )


if __name__ == "__main__":
    main()
