"""Provider-agnostic LLM + embedding gateway.

Thin wrappers over LiteLLM so every module (metadata generation, embedding index,
hydration finalize) talks to the same place and the eval harness can swap models by
changing one env var. All calls are injectable — every consumer accepts a callable so
tests run offline without hitting a provider.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Callable, Sequence

# Defaults chosen for the eval harness; override per-call or via env.
CHAT_MODEL = os.environ.get("LLM_CHAT_MODEL", "claude-haiku-4-5")
EMBED_MODEL = os.environ.get("LLM_EMBED_MODEL", "text-embedding-3-small")

# A function that turns a system+user prompt into raw model text.
CompleteFn = Callable[[str, str], str]
# A function that turns a batch of strings into embedding vectors.
EmbedFn = Callable[[Sequence[str]], list[list[float]]]


def complete(system: str, user: str, model: str | None = None, temperature: float = 0.0) -> str:
    """Single chat completion. Deterministic by default (temperature 0)."""
    import litellm  # imported lazily so the package loads without the dep for tests

    resp = litellm.completion(
        model=model or CHAT_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
    )
    return resp["choices"][0]["message"]["content"]


def embed(texts: Sequence[str], model: str | None = None) -> list[list[float]]:
    """Embed a batch of texts. Batches are the caller's responsibility to size."""
    import litellm

    resp = litellm.embedding(model=model or EMBED_MODEL, input=list(texts))
    # LiteLLM normalises to {"data": [{"embedding": [...]}, ...]}.
    return [row["embedding"] for row in resp["data"]]


_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", re.DOTALL)


def parse_json(text: str) -> Any:
    """Extract the first JSON object/array from a model reply, tolerating code fences and
    surrounding prose. Raises ValueError if nothing parseable is found — callers route that
    to their repair/retry path rather than passing bad state downstream."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _JSON_FENCE.search(text)
    if m:
        return json.loads(m.group(1))
    # Last resort: first balanced object.
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            depth += (text[i] == "{") - (text[i] == "}")
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError("No JSON object found in model output.")
