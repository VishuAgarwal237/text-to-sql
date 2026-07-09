"""Validate ⇄ Repair loop (verification layer 3).

The deterministic control structure that turns one-shot validation into a self-correcting
loop. It owns the retry budget and the validate→repair→re-validate cycle; the *repair* step
itself is an LLM call, injected as a callback so this loop stays pure and testable.

    repair_fn(sql, error, stage, attempt) -> corrected_sql

In the real graph, `repair_fn` wraps the Repair agent (prompts/repair.md) behind the LiteLLM
gateway. In tests it's a plain function. Either way the loop guarantees: the returned SQL has
passed `validate()`, or every attempt was exhausted and the last failure is reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.agents.validator import ValidationResult, validate

# (failing_sql, error, stage, attempt_number) -> corrected_sql
RepairFn = Callable[[str, str, str, int], str]


@dataclass
class RepairOutcome:
    ok: bool
    sql: str                                  # final SQL (valid if ok)
    attempts: int                             # how many repair attempts were made
    result: ValidationResult                  # final validation verdict
    history: list[str] = field(default_factory=list)  # per-attempt error trace


def validate_and_repair(
    sql: str, repair_fn: RepairFn, max_retries: int = 3
) -> RepairOutcome:
    """Validate `sql`; on failure call `repair_fn` and re-validate, up to `max_retries`."""
    history: list[str] = []
    current = sql

    result = validate(current)
    attempt = 0
    while not result.ok and attempt < max_retries:
        history.append(f"attempt {attempt}: [{result.stage}] {result.error}")
        attempt += 1
        current = repair_fn(result.sql, result.error or "", result.stage, attempt)
        result = validate(current)

    if not result.ok:
        history.append(f"attempt {attempt}: [{result.stage}] {result.error}")

    return RepairOutcome(
        ok=result.ok,
        sql=result.sql,
        attempts=attempt,
        result=result,
        history=history,
    )
