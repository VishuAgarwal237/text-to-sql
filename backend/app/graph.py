"""LangGraph adapter.

This is intentionally thin: all the logic lives in `app/nodes.py` as framework-agnostic
functions, and this module just registers them as a `StateGraph` and declares the edges. The
graph and the plain-Python `run_pipeline` therefore share exactly the same nodes and routing —
the graph adds streaming, checkpointing, and visualization; it does not add behaviour.

Pipeline:

    router ─(analytical_sql)─▶ hydrate ▶ generate_sql ▶ validate ─(ok)─▶ execute ─(ok)─▶ present ▶ aggregate ▶ END
       └─(meta/unsupported)──────────────────────────────────────────────────────────────▶ aggregate
    validate/execute ─(error, retries left)─▶ repair ▶ validate   (self-correcting loop)
"""

from __future__ import annotations

from functools import partial
from typing import Any

from langgraph.graph import END, StateGraph

from app import nodes
from app.state import AgentState, Resources


def build_graph(res: Resources):
    """Compile the pipeline into a runnable LangGraph. Nodes close over `res` via partial."""
    g = StateGraph(AgentState)

    g.add_node("router", partial(nodes.router_node, res=res))
    g.add_node("hydrate", partial(nodes.hydrate_node, res=res))
    g.add_node("generate_sql", partial(nodes.generate_sql_node, res=res))
    g.add_node("validate", partial(nodes.validate_node, res=res))
    g.add_node("repair", partial(nodes.repair_node, res=res))
    g.add_node("execute", partial(nodes.execute_node, res=res))
    g.add_node("present", partial(nodes.present_node, res=res))
    g.add_node("aggregate", partial(nodes.aggregate_node, res=res))

    g.set_entry_point("router")
    g.add_conditional_edges(
        "router", nodes.route_after_router,
        {"hydrate": "hydrate", "aggregate": "aggregate"},
    )
    g.add_edge("hydrate", "generate_sql")
    g.add_edge("generate_sql", "validate")
    g.add_conditional_edges(
        "validate", partial(nodes.route_after_validate, res=res),
        {"execute": "execute", "repair": "repair", "fail": "aggregate"},
    )
    g.add_edge("repair", "validate")
    g.add_conditional_edges(
        "execute", partial(nodes.route_after_execute, res=res),
        {"present": "present", "repair": "repair", "fail": "aggregate"},
    )
    g.add_edge("present", "aggregate")
    g.add_edge("aggregate", END)

    return g.compile()


def run(question: str, res: Resources) -> dict[str, Any]:
    """Convenience: invoke the compiled graph for one question and return the final answer."""
    final = build_graph(res).invoke({"question": question, "retries": 0, "trace": []})
    return final.get("answer", {})
