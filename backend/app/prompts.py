"""Load agent system prompts and render the metadata catalog into compact context.

The prompt `.md` files under app/agents/prompts/ ARE the system prompts (written in the
6-section format). We pass each file's full text as the system message.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path
from typing import Any

_PROMPT_DIR = Path(__file__).resolve().parent / "agents" / "prompts"
_CATALOG_FILE = Path(__file__).resolve().parent.parent / "metadata" / "schema_metadata.json"


@functools.lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Return the full system-prompt text for an agent (e.g. load_prompt('router'))."""
    path = _PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return path.read_text()


@functools.lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    """Return the parsed schema metadata catalog."""
    return json.loads(_CATALOG_FILE.read_text())


@functools.lru_cache(maxsize=1)
def render_catalog_compact() -> str:
    """Render the catalog as a compact, token-efficient text block for the SQL agent.

    Always available (independent of the hydration agent) so SQL generation has ground truth
    even when hydration output is thin — a reliability backstop.
    """
    cat = load_catalog()
    lines: list[str] = [f"DATABASE ({cat['database']['dialect']}): {cat['database']['description']}", ""]

    lines.append("TABLES (columns):")
    for t, info in cat["tables"].items():
        cols = ", ".join(info["columns"].keys())
        pk = ",".join(info.get("primary_key", []))
        lines.append(f"  {t} [PK {pk}]: {cols}")
    lines.append("")

    lines.append("RELATIONSHIPS (join on):")
    for r in cat["relationships"]:
        lines.append(f"  {r['join']}")
    lines.append("")

    lines.append("COMMON METRICS:")
    for m in cat["common_metrics"]:
        lines.append(f"  {m['name']}: {m['sql_expression']}  ({m.get('notes', '')})")
    lines.append("")

    lines.append("JOIN PATHS:")
    for j in cat["join_paths"]:
        lines.append(f"  {j['goal']}: {j['path']}")
    lines.append("")

    lines.append("DIALECT NOTES:")
    for d in cat["dialect_notes"]:
        lines.append(f"  - {d}")

    return "\n".join(lines)
