"""Shared helpers for agent nodes: run an LLM step and produce trace/accounting updates."""

from __future__ import annotations

from typing import Any

from app import llm


def run_llm_step(step: str, system: str, user: str, model: str, max_tokens: int = 2000):
    """Run one LLM agent step. Returns (LLMResult, accounting_update).

    `accounting_update` is a partial AgentState with the additive fields (trace/cost/seconds)
    the node should merge into its return value.
    """
    res = llm.complete_json(system, user, model=model, max_tokens=max_tokens)
    entry: dict[str, Any] = {
        "step": step,
        "model": res.model,
        "latency_s": round(res.latency_s, 4),
        "input_tokens": res.input_tokens,
        "output_tokens": res.output_tokens,
        "cost_usd": round(res.cost_usd, 6),
        "error": res.error,
        "output": res.data,
    }
    accounting = {
        "trace": [entry],
        "cost_usd": res.cost_usd,
        "llm_seconds": res.latency_s,
    }
    return res, accounting
