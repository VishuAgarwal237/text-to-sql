"""Token-budget / context manager.

The retrieval stage is recall-oriented and may hand back more candidate tables than fit in the
finalize prompt. This module renders each candidate's metadata compactly and packs as many as fit
under a token budget, highest-ranked first, so the LLM always sees the most promising tables in
full rather than a truncated blob. It is the single owner of "what actually goes into the prompt,"
which nothing else in the pipeline had before.

Token counting uses tiktoken when available and a ~4-chars/token heuristic otherwise — the exact
count doesn't matter, only that we stop before overflowing the window.
"""

from __future__ import annotations

from typing import Any


def estimate_tokens(text: str) -> int:
    try:
        import tiktoken

        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        return max(1, len(text) // 4)


def render_table(table: str, entry: dict[str, Any], max_cols: int | None = None) -> str:
    """Compact, LLM-readable rendering of one table's metadata."""
    lines = [f"TABLE {table} — {entry.get('description', '').strip()}"]
    if entry.get("synonyms"):
        lines.append(f"  aka: {', '.join(entry['synonyms'])}")
    cols = list(entry.get("columns", {}).items())
    if max_cols:
        cols = cols[:max_cols]
    for col, c in cols:
        fk = f" -> {c['references']}" if c.get("is_foreign_key") and c.get("references") else ""
        syn = f" (aka {', '.join(c['synonyms'])})" if c.get("synonyms") else ""
        lines.append(f"  - {col} [{c.get('type', '')}]{fk}: {c.get('description', '').strip()}{syn}")
    return "\n".join(lines)


def pack(
    ranked_tables: list[str],
    catalog: dict[str, Any],
    budget_tokens: int = 6000,
    always_include: set[str] | None = None,
) -> dict[str, Any]:
    """Pack candidate tables into the budget, in rank order. `always_include` tables (e.g. value-
    index matches) are placed first so a strong literal signal is never budgeted out. Returns the
    rendered bundle plus which tables made it in vs were dropped (dropped is a useful trace)."""
    always_include = always_include or set()
    tables = catalog.get("tables", {})

    # Order: forced tables first (keeping their relative rank), then the rest by rank.
    ordered = [t for t in ranked_tables if t in always_include]
    ordered += [t for t in ranked_tables if t not in always_include]
    # Include any forced table that wasn't ranked at all.
    ordered += [t for t in always_include if t not in ranked_tables]

    included, blocks, used = [], [], 0
    for t in ordered:
        if t not in tables or t in included:
            continue
        block = render_table(t, tables[t])
        cost = estimate_tokens(block)
        if used + cost > budget_tokens and t not in always_include and included:
            continue  # skip tables that don't fit, but never blow past budget
        blocks.append(block)
        included.append(t)
        used += cost

    return {
        "bundle": "\n\n".join(blocks),
        "included_tables": included,
        "dropped_tables": [t for t in ordered if t in tables and t not in included],
        "tokens_used": used,
        "budget_tokens": budget_tokens,
    }
