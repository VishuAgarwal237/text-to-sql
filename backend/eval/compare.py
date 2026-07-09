"""Result-set comparison for the text-to-SQL eval.

The single tricky part of scoring text-to-SQL is deciding when a candidate result
"matches" the ground truth. Naive equality (row-by-row, key-by-key, string ==) produces
false negatives on perfectly correct queries, which is exactly what earlier eval runs hit.
This module compares *values* with:

  - **order-insensitive** rows: two result sets that differ only in row order match. Gold
    queries carry an ORDER BY, but a correct candidate may tie-break differently (several
    countries share the same average invoice total, several playlists share a name+count).
  - **order-insensitive columns / alias-insensitive**: cells are compared as a multiset per
    row, so `AS TotalSales` vs `AS revenue` (or a different column order) does not fail a
    numerically identical answer.
  - **multiset semantics**: duplicate rows are preserved and must match in multiplicity, so
    the two real `"Music" -> 3290` playlist rows are NOT collapsed away.
  - **float tolerance**: floats are rounded (default 6 dp) so `6.659999999999999` == `6.66`.
  - **unicode normalization** (NFC): `"Luís"` compares equal regardless of composed vs
    decomposed form.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any

Row = dict[str, Any]

# Decimal places floats are rounded to before comparison. 6 dp absorbs floating-point
# noise (AVG, division) while staying tight enough to catch a genuinely wrong number.
FLOAT_NDIGITS = 6


def _norm_cell(value: Any) -> tuple[str, Any]:
    """Normalize one cell into a hashable, type-tagged token.

    The tag keeps a number from accidentally matching its stringified form and makes mixed
    rows sortable (all tags are strings, so tuples order deterministically).
    """
    if value is None:
        return ("null", None)
    # bool is a subclass of int; SQLite has no bool, so fold it into the numeric domain.
    if isinstance(value, bool):
        return ("num", round(float(value), FLOAT_NDIGITS))
    if isinstance(value, (int, float)):
        return ("num", round(float(value), FLOAT_NDIGITS))
    if isinstance(value, str):
        return ("str", unicodedata.normalize("NFC", value))
    if isinstance(value, bytes):
        return ("bytes", value)
    return ("other", str(value))


def _norm_row(row: Row) -> tuple[tuple[str, Any], ...]:
    """Normalize a row to a sorted tuple of cell tokens (column order / names ignored)."""
    return tuple(sorted(_norm_cell(v) for v in row.values()))


def _counter(rows: list[Row]) -> Counter:
    return Counter(_norm_row(r) for r in rows)


@dataclass
class ComparisonResult:
    passed: bool
    n_expected: int
    n_candidate: int
    n_missing: int  # rows expected but not produced
    n_extra: int    # rows produced but not expected
    missing_sample: list[tuple]
    extra_sample: list[tuple]

    def summary(self) -> str:
        if self.passed:
            return f"match ({self.n_candidate} rows)"
        parts = [f"expected {self.n_expected}, got {self.n_candidate}"]
        if self.n_missing:
            parts.append(f"{self.n_missing} missing")
        if self.n_extra:
            parts.append(f"{self.n_extra} extra")
        return "MISMATCH — " + ", ".join(parts)


def compare_results(
    expected: list[Row], candidate: list[Row], sample: int = 3
) -> ComparisonResult:
    """Compare two result sets as value-multisets. Returns a structured verdict + diff."""
    exp = _counter(expected)
    cand = _counter(candidate)

    missing = exp - cand  # multiset difference: expected rows short-counted in candidate
    extra = cand - exp

    return ComparisonResult(
        passed=(not missing and not extra),
        n_expected=len(expected),
        n_candidate=len(candidate),
        n_missing=sum(missing.values()),
        n_extra=sum(extra.values()),
        missing_sample=list(missing.elements())[:sample],
        extra_sample=list(extra.elements())[:sample],
    )
