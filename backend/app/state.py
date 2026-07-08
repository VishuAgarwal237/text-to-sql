"""Shared pipeline state + injected resources.

`AgentState` is the single dict that flows through every node (router → hydration → SQL gen →
validate ⇄ repair → execute → presentation → aggregate). `Resources` bundles the things a node
needs but shouldn't construct itself — the catalog, the retrieval indexes, the FK graph, and the
LLM callables — so every node is a pure function of (state, resources) and is trivially testable
with fakes. Nothing here imports langgraph; the graph is just one adapter over these.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, TypedDict

from app import llm

PROMPTS_DIR = Path(__file__).parent / "agents" / "prompts"


class AgentState(TypedDict, total=False):
    question: str
    # router
    intent: str
    entities: dict[str, Any]
    router_message: str  # user-facing text for meta / unsupported / clarification
    # hydration
    hydration: dict[str, Any]
    # sql
    sql: str
    assumptions: list[str]
    # validate / repair loop
    validation_error: Optional[str]
    retries: int
    # execute
    result: dict[str, Any]
    # presentation
    presentation: dict[str, Any]
    # final
    answer: dict[str, Any]
    trace: list[str]
    error: Optional[str]


@dataclass
class Resources:
    """Everything the nodes depend on, injected once at graph-build time."""

    catalog: dict[str, Any]
    embed_index: Any  # TableEmbeddingIndex
    value_index: Any  # ValueIndex
    fk_graph: Any  # FKGraph
    complete_fn: Callable[[str, str], str] = llm.complete
    embed_fn: Callable[..., list[list[float]]] = llm.embed
    max_retries: int = 2
    max_rows: int = 1000
    timeout_ms: int = 5000
    candidate_k: int = 30
    budget_tokens: int = 6000
    _prompts: dict[str, str] = field(default_factory=dict)

    def prompt(self, name: str) -> str:
        """Load and cache a system prompt by stem (e.g. 'router')."""
        if name not in self._prompts:
            self._prompts[name] = (PROMPTS_DIR / f"{name}.md").read_text()
        return self._prompts[name]
