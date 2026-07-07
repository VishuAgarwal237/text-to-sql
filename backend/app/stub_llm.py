"""Deterministic offline LLM backend (a TEST HARNESS, not a model).

Purpose: let the full LangGraph pipeline and the eval harness run end-to-end with NO API key,
so the wiring can be developed, tested, and demonstrated deterministically. It is NOT an
intelligence — it dispatches on which agent is calling (detected from the system prompt) and
returns role-appropriate JSON. For SQL generation it looks up the question in the eval set and
returns the ground-truth SQL; for unseen questions it returns a safe error so the graph exercises
its clarification/error paths honestly rather than hallucinating.

Enable with:  LLM_BACKEND=stub
Never use in production — swap to the real gateway by unsetting LLM_BACKEND / setting a key.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.llm import LLMResult

_EVAL = Path(__file__).resolve().parents[1] / "eval" / "evaluation_data.json"


def _load_eval_map() -> dict[str, str]:
    if not _EVAL.exists():
        return {}
    data = json.loads(_EVAL.read_text())
    return {c["question"].strip().lower(): c["sql"] for c in data}


_EVAL_MAP = _load_eval_map()


def _find_question(user: str) -> str | None:
    """Return the eval question whose text appears in the user prompt, if any."""
    low = user.lower()
    for q in _EVAL_MAP:
        if q in low:
            return q
    return None


def _result(data: dict, model: str) -> LLMResult:
    raw = json.dumps(data)
    # Rough token estimate so stub runs still populate the eval's latency/token columns.
    return LLMResult(
        data=data, raw=raw, model=f"stub::{model}", latency_s=0.001,
        input_tokens=len(raw) // 4, output_tokens=len(raw) // 4, cost_usd=0.0,
    )


def _agent_of(system: str) -> str:
    """Identify the calling agent from the prompt's H1 title (unique per agent)."""
    first = system.strip().splitlines()[0].lower() if system.strip() else ""
    for key in ("router", "schema hydration", "sql generation", "repair",
                "summarizer", "visualizer"):
        if key in first:
            return key
    return "unknown"


def complete_json(system: str, user: str, model: str = "stub") -> LLMResult:
    agent = _agent_of(system)

    # --- Router / Intent -------------------------------------------------------------------
    if agent == "router":
        q = _find_question(user)
        if q or "?" in user:
            return _result({
                "status": "success", "thought_process": "stub: treated as an analytical question",
                "intent": "analytical_sql",
                "entities": {"metrics": [], "dimensions": [], "filters": [], "sort": None,
                             "limit": None, "table_hints": []},
                "clarification": None, "assumptions": [],
                "result": "analytical question", "suggested_next_steps": ["generate SQL"],
            }, model)
        return _result({
            "status": "success", "thought_process": "stub: greeting/meta",
            "intent": "meta", "entities": {}, "clarification": None, "assumptions": [],
            "result": "Hello — ask me a question about the music store data.",
            "suggested_next_steps": ["ask a data question"],
        }, model)

    # --- Schema Hydration ------------------------------------------------------------------
    if agent == "schema hydration":
        return _result({
            "status": "success", "thought_process": "stub: pass metadata catalog through",
            "selected_tables": [], "selected_columns": {}, "join_paths": [],
            "resolved_concepts": [], "dialect_notes": [],
            "result": "Use the full Chinook metadata catalog provided.",
            "suggested_next_steps": ["generate SQL"],
        }, model)

    # --- SQL Generation --------------------------------------------------------------------
    if agent == "sql generation":
        q = _find_question(user)
        if q:
            return _result({
                "status": "success", "thought_process": "stub: ground-truth SQL for known question",
                "sql": _EVAL_MAP[q], "assumptions": [],
                "result": "known query", "suggested_next_steps": ["validate and execute"],
            }, model)
        return _result({
            "status": "error", "thought_process": "stub cannot author SQL for unseen questions",
            "sql": "", "assumptions": [],
            "result": "no canned SQL for this question (stub backend)",
            "suggested_next_steps": ["use a real model to answer novel questions"],
        }, model)

    # --- Repair ----------------------------------------------------------------------------
    if agent == "repair":
        m = re.search(r'"?previous_sql"?\s*[:=]\s*"([^"]+)"', user)
        return _result({
            "status": "error" if not m else "success",
            "thought_process": "stub: no automated repair available offline",
            "sql": m.group(1) if m else "", "fix_explanation": "stub passthrough",
            "result": "stub repair", "suggested_next_steps": ["use a real model"],
        }, model)

    # --- Summarizer ------------------------------------------------------------------------
    if agent == "summarizer":
        return _result({
            "status": "success", "thought_process": "stub summary",
            "summary": "Here are the results for your question (stub summary).",
            "result": "Here are the results for your question (stub summary).",
            "suggested_next_steps": ["break down further"],
        }, model)

    # --- Visualizer (LLM tie-breaker; rules engine already ran in code) ---------------------
    if agent == "visualizer":
        m = re.search(r'rule[_-]?based[^:]*[:=]\s*"?(\w+)"?', user, re.IGNORECASE)
        pick = m.group(1) if m else "table"
        return _result({
            "status": "success", "thought_process": "stub: follow the rule-based pick",
            "chart_type": pick,
            "chart_spec": {"type": pick, "x": None, "y": [], "series": None, "title": "Query Results"},
            "rationale": f"stub: followed rule-based pick ({pick})",
            "result": "stub chart", "suggested_next_steps": ["view as table"],
        }, model)

    # --- Fallback --------------------------------------------------------------------------
    return _result({"status": "error", "thought_process": "stub: unknown agent",
                    "result": "unknown", "suggested_next_steps": []}, model)
