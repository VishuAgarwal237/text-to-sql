"""Generate the schema metadata catalog (schema_metadata.json) with an LLM.

Pipeline (RTF step 2 / 2.2):
  1. Introspect the live Chinook schema (tables, columns, types, FKs) via app.db.
  2. Sample a few real distinct values per column so the model's descriptions/synonyms are
     grounded in reality, not hallucinated.
  3. Load the engineered prompt from metadata_prompt.md, inject the schema + samples.
  4. Call the LLM (provider-agnostic via LiteLLM), parse the JSON it returns.
  5. Validate every table/column in the catalog exists in the real schema, then save.

Run:
    python metadata/generate_metadata.py                # uses $METADATA_MODEL or default
    METADATA_MODEL=anthropic/claude-sonnet-5 python metadata/generate_metadata.py

Requires an API key for the chosen provider (e.g. ANTHROPIC_API_KEY / FIREWORKS_API_KEY).
A curated schema_metadata.json is committed alongside this script so the system runs even
without a key; running this script regenerates it.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

# Make the sibling app package importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import db  # noqa: E402

HERE = Path(__file__).resolve().parent
PROMPT_FILE = HERE / "metadata_prompt.md"
OUTPUT_FILE = HERE / "schema_metadata.json"
DEFAULT_MODEL = os.environ.get("METADATA_MODEL", "openai/gpt-4o")
SAMPLES_PER_COLUMN = 5


def _extract_prompts(md_text: str) -> tuple[str, str]:
    """Pull the SYSTEM and USER prompt fenced code blocks out of metadata_prompt.md."""
    blocks = re.findall(r"```(?:\w+)?\n(.*?)```", md_text, flags=re.DOTALL)
    if len(blocks) < 2:
        raise ValueError("Expected at least two ``` code blocks (SYSTEM, USER) in prompt file.")
    return blocks[0].strip(), blocks[1].strip()


def _sample_values(schema: dict) -> dict[str, dict[str, list]]:
    """Sample up to N distinct non-null values per column (best-effort, read-only)."""
    conn = sqlite3.connect(f"file:{db.DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    samples: dict[str, dict[str, list]] = {}
    try:
        for table, info in schema.items():
            samples[table] = {}
            for col in info["columns"]:
                name = col["name"]
                try:
                    rows = conn.execute(
                        f'SELECT DISTINCT "{name}" AS v FROM "{table}" '
                        f'WHERE "{name}" IS NOT NULL LIMIT {SAMPLES_PER_COLUMN}'
                    ).fetchall()
                    samples[table][name] = [r["v"] for r in rows]
                except sqlite3.Error:
                    samples[table][name] = []
    finally:
        conn.close()
    return samples


def _validate_catalog(catalog: dict, schema: dict) -> list[str]:
    """Return a list of problems: catalog tables/columns that don't exist in the real schema."""
    problems: list[str] = []
    cat_tables = catalog.get("tables", {})
    for table in schema:
        if table not in cat_tables:
            problems.append(f"missing table in catalog: {table}")
            continue
        real_cols = {c["name"] for c in schema[table]["columns"]}
        cat_cols = set(cat_tables[table].get("columns", {}))
        for missing in real_cols - cat_cols:
            problems.append(f"{table}: column not documented: {missing}")
        for extra in cat_cols - real_cols:
            problems.append(f"{table}: catalog invents column: {extra}")
    return problems


def build_prompt() -> tuple[str, str]:
    schema = db.get_schema()
    samples = _sample_values(schema)
    system, user = _extract_prompts(PROMPT_FILE.read_text())
    user = user.replace("{SCHEMA_INTROSPECTION}", json.dumps(schema, indent=2))
    user = user.replace("{SAMPLE_VALUES}", json.dumps(samples, indent=2, default=str))
    return system, user


def main() -> None:
    system, user = build_prompt()

    try:
        import litellm
    except ImportError:
        sys.exit("litellm is required: pip install -e . (in backend/)")

    print(f"Generating metadata with model: {DEFAULT_MODEL}")
    resp = litellm.completion(
        model=DEFAULT_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0,
        max_tokens=8000,
    )
    content = resp.choices[0].message.content.strip()
    # Be tolerant of accidental code fences.
    content = re.sub(r"^```(?:json)?\n?|\n?```$", "", content).strip()

    try:
        catalog = json.loads(content)
    except json.JSONDecodeError as e:
        sys.exit(f"Model did not return valid JSON: {e}\n--- got ---\n{content[:500]}")

    problems = _validate_catalog(catalog, db.get_schema())
    if problems:
        print("WARNING — catalog does not match live schema:")
        for p in problems:
            print("  -", p)
        print("Saving anyway for inspection; fix the prompt and re-run if this is unexpected.")

    OUTPUT_FILE.write_text(json.dumps(catalog, indent=2))
    print(f"Wrote {OUTPUT_FILE} ({len(catalog.get('tables', {}))} tables).")


if __name__ == "__main__":
    main()
