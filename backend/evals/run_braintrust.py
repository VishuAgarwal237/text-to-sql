"""Braintrust eval runner for the text-to-SQL pipeline.

Run from `backend/`:

    BRAINTRUST_API_KEY=... OPENAI_API_KEY=... python -m evals.run_braintrust

Prereqs:
  - `python -m app.metadata.generate` has created `data/schema_metadata.json`
  - `CHINOOK_DB_PATH` points at a readable Chinook SQLite DB, unless using the default path

Scoring intentionally avoids exact SQL string matching. Equivalent SQL can be valid, so the eval
scores behavior: executable SQL, result equivalence against trusted gold SQL, required semantic
fragments for metrics/joins/aggregations, expected filters, chart choice, and clarification/safety
behavior for non-answerable requests.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

import braintrust
from braintrust import Eval, current_span

from app import db
from app.observability import DEFAULT_PROJECT
from app.resources import build_resources
from app.nodes import run_pipeline

CASES_PATH = Path(__file__).with_name("text_to_sql_cases.jsonl")


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _answer(output: dict[str, Any]) -> dict[str, Any]:
    return output.get("answer", output)


def task(question: str) -> dict[str, Any]:
    state = run_pipeline(question, build_resources())
    answer = state["answer"]
    current_span().log(
        input=question,
        output=answer,
        metadata={
            "trace": state.get("trace", []),
            "sql": answer.get("sql"),
            "row_count": answer.get("row_count"),
            "truncated": answer.get("truncated"),
            "chart_type": answer.get("chart_type"),
            "error": answer.get("error"),
        },
    )
    return answer


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


def result_matches_gold(_input, output, expected) -> int:
    """Execute trusted gold SQL and compare result tuples to generated output tuples.

    Column aliases may differ across equivalent SQL, so comparison is value-based using column
    order. Ordering still matters when the gold query orders rows; unordered-result cases can set
    `"ordered": false`.
    """
    gold_sql = expected.get("gold_sql")
    if not gold_sql:
        return 1
    answer = _answer(output)
    if not answer.get("sql") or answer.get("error"):
        return 0
    try:
        generated = db.run_query(answer["sql"], max_rows=expected.get("max_rows", 1000))
        gold = db.run_query(gold_sql, max_rows=expected.get("max_rows", 1000))
    except Exception:
        return 0
    generated_rows = _rows_as_value_tuples(generated)
    gold_rows = _rows_as_value_tuples(gold)
    if expected.get("ordered", True):
        return int(generated_rows == gold_rows)
    return int(sorted(generated_rows) == sorted(gold_rows))


def safety_no_sql(_input, output, expected) -> int:
    if not expected.get("must_not_generate_sql"):
        return 1
    answer = _answer(output)
    return int(not answer.get("sql"))


def main() -> None:
    braintrust.auto_instrument()
    Eval(
        DEFAULT_PROJECT,
        experiment_name="text-to-sql-agent-flow",
        data=load_cases(),
        task=task,
        scores=[
            expected_behavior,
            sql_valid,
            expected_tables_used,
            expected_filters_used,
            required_sql_semantics,
            result_matches_gold,
            chart_type_match,
            safety_no_sql,
        ],
        metadata={"suite": "text_to_sql_cases"},
    )


if __name__ == "__main__":
    main()
