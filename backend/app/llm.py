"""Provider-agnostic LLM gateway.

One interface for every agent, so the same LangGraph runs unchanged under any benchmarked
model (a Fireworks OSS model, Claude Haiku 4.5, Claude Sonnet 5, ...). Responsibilities:
  - route to the configured model via LiteLLM (Anthropic / Fireworks / OpenAI / ...),
  - request/parse strict JSON,
  - capture per-call latency, token usage, and USD cost (for the eval's model comparison),
  - offer an offline `stub` backend so the pipeline + eval run deterministically without keys.

Config via env:
  LLM_BACKEND   = "litellm" (default) | "stub"
  DEFAULT_MODEL = e.g. "anthropic/claude-sonnet-5", "fireworks_ai/accounts/fireworks/models/llama-v3p1-70b-instruct"
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "openai/gpt-4o-mini")

# The models the eval benchmarks. `key` is a short label used in reports/UI; `model` is the
# LiteLLM model id. Provider-agnostic — mix providers freely by editing this map + your keys.
MODEL_REGISTRY: dict[str, str] = {
    "gpt-4o-mini": "openai/gpt-4o-mini",   # cheap / fast tier
    "gpt-4o": "openai/gpt-4o",             # higher-accuracy tier
    # Add other providers here if you have keys, e.g.:
    #   "claude-sonnet-5": "anthropic/claude-sonnet-5",
    #   "llama-70b": "fireworks_ai/accounts/fireworks/models/llama-v3p1-70b-instruct",
}


@dataclass
class LLMResult:
    """Parsed JSON payload plus call metadata for cost/latency accounting."""

    data: dict[str, Any]
    raw: str
    model: str
    latency_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def _backend() -> str:
    return os.environ.get("LLM_BACKEND", "litellm").lower()


def _extract_json(text: str) -> dict[str, Any]:
    """Best-effort parse of a JSON object from a model response (tolerates code fences/prose)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\n?|\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fall back to the first {...} span.
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def complete_json(
    system: str,
    user: str,
    model: str | None = None,
    max_tokens: int = 2000,
) -> LLMResult:
    """Run one system+user turn and return parsed JSON with cost/latency metadata.

    Never raises on model/parse failure — returns an LLMResult with `error` set and an empty
    `data` dict so the calling node can decide how to recover (repair, clarify, etc.).
    """
    model = model or DEFAULT_MODEL

    if _backend() == "stub":
        from app import stub_llm

        return stub_llm.complete_json(system, user, model=model)

    import litellm

    t0 = time.perf_counter()
    try:
        print(system)
        resp = litellm.completion(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0,
            max_tokens=max_tokens,
        )
        latency = time.perf_counter() - t0
        raw = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        in_tok = getattr(usage, "prompt_tokens", 0) or 0
        out_tok = getattr(usage, "completion_tokens", 0) or 0
        try:
            cost = litellm.completion_cost(completion_response=resp) or 0.0
        except Exception:
            cost = 0.0
        try:
            data = _extract_json(raw)
            err = None
        except Exception as e:
            data, err = {}, f"json_parse_error: {e}"
        return LLMResult(
            data=data, raw=raw, model=model, latency_s=latency,
            input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost, error=err,
        )
    except Exception as e:
        return LLMResult(
            data={}, raw="", model=model, latency_s=time.perf_counter() - t0,
            error=f"llm_error: {e}",
        )
