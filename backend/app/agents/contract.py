"""Agent JSON-contract verification (verification layer 4).

Every LLM node must return strict JSON matching its Output Contract. Models sometimes wrap
that JSON in ```json fences or add stray prose; this module extracts and validates it so a
malformed reply is caught at the boundary and routed to a retry/repair instead of corrupting
downstream state.

`parse_agent_json` returns the parsed dict on success and raises `ContractError` (with a
message a retry prompt can use) on failure. `REQUIRED_KEYS` pins the minimal keys each agent
must emit, per the prompts in prompts/*.md.
"""

from __future__ import annotations

import json
import re

# Minimal required keys per agent, from each prompt's Output Contract.
REQUIRED_KEYS: dict[str, set[str]] = {
    "router": {"status", "intent", "entities", "result"},
    "schema_hydration": {"status", "selected_tables", "selected_columns", "join_paths", "result"},
    "sql_generation": {"status", "sql", "result"},
    "repair": {"status", "sql", "fix_explanation"},
    "summarizer": {"status", "summary", "result"},
    "visualizer": {"status", "chart_type", "chart_spec"},
}

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class ContractError(ValueError):
    """Raised when an agent reply is not valid JSON or is missing required keys."""


def _extract_json_text(raw: str) -> str:
    """Pull the JSON object out of a raw model reply (strip fences / surrounding prose)."""
    if not raw or not raw.strip():
        raise ContractError("Empty agent reply.")

    fenced = _FENCE_RE.search(raw)
    if fenced:
        return fenced.group(1).strip()

    # No fence: take from the first { to the last } to tolerate leading/trailing prose.
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ContractError("No JSON object found in agent reply.")
    return raw[start : end + 1].strip()


def parse_agent_json(raw: str, agent: str) -> dict:
    """Parse and validate an agent's reply against its contract. Raises `ContractError`."""
    if agent not in REQUIRED_KEYS:
        raise ContractError(f"Unknown agent '{agent}'.")

    text = _extract_json_text(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ContractError(f"Invalid JSON from {agent}: {exc}") from exc

    if not isinstance(data, dict):
        raise ContractError(f"{agent} must return a JSON object, got {type(data).__name__}.")

    missing = REQUIRED_KEYS[agent] - data.keys()
    if missing:
        raise ContractError(f"{agent} reply missing required key(s): {', '.join(sorted(missing))}.")

    return data
