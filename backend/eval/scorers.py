"""Scorers for the text-to-SQL eval.

Primary metric is EXECUTION ACCURACY: run the predicted SQL and the ground-truth SQL against the
read-only database and compare their result sets order-insensitively (handling the documented
duplicate-row cases and float rounding). This is the fair metric — many correct queries differ
textually. Secondary: valid-SQL rate. An autoevals `Sql` similarity scorer is used when available.
"""

from __future__ import annotations

from typing import Any

from app import db


def _canonical(rows: list[dict[str, Any]]) -> list[tuple]:
    """Order-insensitive canonical form: sorted multiset of value-tuples, floats rounded."""
    def norm(v: Any) -> Any:
        if isinstance(v, float):
            return round(v, 2)
        if isinstance(v, int) and not isinstance(v, bool):
            return v
        return str(v)
    canon = [tuple(norm(v) for v in row.values()) for row in rows]
    return sorted(canon, key=lambda t: tuple(str(x) for x in t))


def execution_match(pred_sql: str, gold_sql: str) -> dict[str, Any]:
    """Execute both queries and compare result sets. Returns {'score': 1.0|0.0, 'reason', ...}."""
    if not pred_sql or not pred_sql.strip():
        return {"score": 0.0, "reason": "empty predicted SQL", "pred_error": "empty"}
    try:
        pred = db.run_query(pred_sql, max_rows=100000)
    except Exception as e:
        return {"score": 0.0, "reason": "predicted SQL failed to execute", "pred_error": str(e)}
    try:
        gold = db.run_query(gold_sql, max_rows=100000)
    except Exception as e:
        return {"score": 0.0, "reason": "gold SQL failed (eval data issue)", "gold_error": str(e)}

    match = _canonical(pred["rows"]) == _canonical(gold["rows"])
    return {
        "score": 1.0 if match else 0.0,
        "reason": "result sets match" if match else "result sets differ",
        "pred_rows": pred["row_count"],
        "gold_rows": gold["row_count"],
    }


def is_valid_sql(pred_sql: str) -> float:
    """1.0 if the predicted SQL is a valid, read-only query that EXPLAINs cleanly, else 0.0."""
    if not pred_sql or not pred_sql.strip():
        return 0.0
    try:
        db.explain(pred_sql)  # includes the read-only guard
        return 1.0
    except Exception:
        return 0.0


def sql_similarity(pred_sql: str, gold_sql: str) -> float | None:
    """Optional textual/AST similarity via autoevals' Sql scorer (best-effort)."""
    try:
        from autoevals import Sql

        res = Sql().eval(output=pred_sql, expected=gold_sql)
        return float(res.score) if res.score is not None else None
    except Exception:
        return None
