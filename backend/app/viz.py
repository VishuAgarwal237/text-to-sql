"""Deterministic chart-selection rules engine.

This is the rules-first half of the Visualizer agent. It infers column types from the result
set and picks a chart type by a fixed heuristic; the LLM only acts as a tie-breaker/override on
top of this. It also builds the concrete chart spec (x / y / series / title) the frontend renders,
so visualization never depends on the model returning well-formed spec fields.
"""

from __future__ import annotations

import re
from typing import Any

CHART_TYPES = {"bar", "line", "scatter", "kpi", "table"}

_DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?")


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def infer_types(columns: list[str], rows: list[dict[str, Any]]) -> dict[str, str]:
    """Classify each column as 'numeric', 'temporal', or 'categorical' from sampled values."""
    types: dict[str, str] = {}
    sample = rows[:50]
    for col in columns:
        vals = [r.get(col) for r in sample if r.get(col) is not None]
        if vals and all(_is_number(v) for v in vals):
            types[col] = "numeric"
        elif vals and all(isinstance(v, str) and _DATE_RE.match(v) for v in vals):
            types[col] = "temporal"
        else:
            types[col] = "categorical"
    return types


def rule_based_chart(columns: list[str], rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return {'chart_type', 'x', 'y', 'series', 'reason'} from the fixed heuristic.

    Heuristic:
      - single scalar (1 row, 1 numeric)          -> kpi
      - 1 temporal + >=1 numeric                  -> line (time series)
      - 1 categorical + 1 numeric                 -> bar (unless too many categories -> table)
      - exactly 2 numeric                         -> scatter
      - otherwise                                 -> table
    """
    types = infer_types(columns, rows)
    numeric = [c for c in columns if types.get(c) == "numeric"]
    temporal = [c for c in columns if types.get(c) == "temporal"]
    categorical = [c for c in columns if types.get(c) == "categorical"]
    n_rows = len(rows)

    if n_rows == 0 or not columns:
        return {"chart_type": "table", "x": None, "y": [], "series": None,
                "reason": "no rows / no columns"}

    if n_rows == 1 and len(numeric) == 1 and len(columns) == 1:
        return {"chart_type": "kpi", "x": None, "y": [numeric[0]], "series": None,
                "reason": "single scalar value"}

    if temporal and numeric:
        return {"chart_type": "line", "x": temporal[0], "y": numeric[: 3], "series": None,
                "reason": "temporal x-axis with numeric measure(s)"}

    if len(categorical) == 1 and len(numeric) == 1:
        distinct = len({r.get(categorical[0]) for r in rows})
        if distinct > 30:
            return {"chart_type": "table", "x": categorical[0], "y": [numeric[0]], "series": None,
                    "reason": f"too many categories ({distinct}) to chart as bars"}
        return {"chart_type": "bar", "x": categorical[0], "y": [numeric[0]], "series": None,
                "reason": "one categorical + one numeric"}

    if len(numeric) == 2 and not categorical:
        return {"chart_type": "scatter", "x": numeric[0], "y": [numeric[1]], "series": None,
                "reason": "two numeric columns"}

    return {"chart_type": "table", "x": None, "y": numeric, "series": None,
            "reason": "default: no clear single-chart shape"}


def build_spec(chart_type: str, columns: list[str], rows: list[dict[str, Any]],
               title: str = "Query Results") -> dict[str, Any]:
    """Build a render-ready chart spec for the given (possibly LLM-overridden) chart type."""
    if chart_type not in CHART_TYPES:
        chart_type = "table"
    rule = rule_based_chart(columns, rows)
    # Reuse the rule engine's x/y role assignment; only the type may have been overridden.
    return {
        "type": chart_type,
        "x": rule["x"] if chart_type in {"bar", "line", "scatter"} else None,
        "y": rule["y"] if chart_type in {"bar", "line", "scatter", "kpi"} else [],
        "series": rule.get("series"),
        "title": title,
    }
