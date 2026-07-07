"""Schema Hydration node: select relevant tables/columns and resolve business concepts.

Always composes a reliable schema context = the compact catalog rendering (ground truth) plus
the hydration agent's question-specific selection/resolution. Even if the LLM output is thin,
the compact catalog guarantees the SQL agent has what it needs.
"""

from __future__ import annotations

import json
from typing import Any

from app.agents._common import run_llm_step
from app.prompts import load_catalog, load_prompt, render_catalog_compact
from app.state import AgentState


def schema_node(state: AgentState) -> dict[str, Any]:
    system = load_prompt("schema_hydration")
    catalog = load_catalog()
    user = (
        f"QUESTION: {state['question']}\n\n"
        f"ROUTER ENTITIES: {json.dumps(state.get('router', {}).get('entities', {}))}\n\n"
        f"METADATA CATALOG (authoritative):\n{json.dumps(catalog)}"
    )
    res, acct = run_llm_step("schema_hydration", system, user, state["model"], max_tokens=1500)
    hydration = res.data or {}

    compact = render_catalog_compact()
    focus = hydration.get("result", "")
    resolved = hydration.get("resolved_concepts", [])
    context_parts = [compact]
    if focus:
        context_parts.append("\nFOCUS FOR THIS QUESTION:\n" + str(focus))
    if resolved:
        context_parts.append("\nRESOLVED CONCEPTS:\n" + json.dumps(resolved))
    schema_context = "\n".join(context_parts)

    return {"hydration": hydration, "schema_context": schema_context, **acct}
