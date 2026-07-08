"""Braintrust eval runner for the text-to-SQL pipeline.

Run from `backend/`:

    BRAINTRUST_API_KEY=... OPENAI_API_KEY=... python -m evals.run_braintrust

Prereqs:
  - `python -m app.metadata.generate` has created `data/schema_metadata.json`
  - `CHINOOK_DB_PATH` points at a readable Chinook SQLite DB, unless using the default path

Scoring intentionally avoids exact SQL string matching. Equivalent SQL can be valid, so the eval
scores behavior: validation, expected table usage, expected filters, and chart choice.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import braintrust
from braintrust import Eval, current_span

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


def sql_valid(_input, output, _expected) -> int:
    answer = _answer(output)
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


def main() -> None:
    braintrust.auto_instrument()
    Eval(
        DEFAULT_PROJECT,
        experiment_name="text-to-sql-agent-flow",
        data=load_cases(),
        task=task,
        scores=[sql_valid, expected_tables_used, expected_filters_used, chart_type_match],
        metadata={"suite": "text_to_sql_cases"},
    )


if __name__ == "__main__":
    main()
