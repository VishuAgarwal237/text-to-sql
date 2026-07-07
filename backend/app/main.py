"""FastAPI service for the MelodyStream text-to-SQL BI tool.

Endpoints:
  GET  /health        - liveness + backend/model config.
  GET  /schema        - live database schema (for the UI's schema explorer).
  POST /query         - run the full pipeline for one question; returns the final payload.
  GET  /stream        - Server-Sent Events: stream the agent trace as the graph runs, then
                        emit the final payload (drives the UI's live "agent thinking" view).
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app import db
from app.graph import answer_question, get_app
from app.llm import DEFAULT_MODEL, MODEL_REGISTRY

app = FastAPI(title="MelodyStream Text-to-SQL", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: str
    model: str | None = None
    max_retries: int = 2


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "llm_backend": os.environ.get("LLM_BACKEND", "litellm"),
        "exec_backend": os.environ.get("EXEC_BACKEND", "direct"),
        "default_model": DEFAULT_MODEL,
        "models": list(MODEL_REGISTRY.keys()),
    }


@app.get("/schema")
def schema() -> dict[str, Any]:
    return db.get_schema()


@app.post("/query")
def query(req: QueryRequest) -> dict[str, Any]:
    """Run the pipeline synchronously and return {summary, sql, rows, chart_spec, ...}."""
    return answer_question(req.question, model=req.model, max_retries=req.max_retries)


@app.get("/stream")
async def stream(question: str, model: str | None = None, max_retries: int = 2):
    """Stream the agent trace via SSE, then the final payload.

    Emits one `event: step` per graph node as it completes (so the UI shows the pipeline
    working), then a single `event: final` with the assembled result.
    """
    resolved = MODEL_REGISTRY.get(model, model) or DEFAULT_MODEL
    graph = get_app()

    async def gen():
        loop = asyncio.get_event_loop()
        seen = 0
        final_state: dict[str, Any] = {}
        # Run the graph in a thread; stream node outputs as they arrive.
        queue: asyncio.Queue = asyncio.Queue()

        def run():
            for chunk in graph.stream(
                {"question": question, "model": resolved,
                 "max_retries": max_retries, "retry_count": 0},
                stream_mode="values",
            ):
                loop.call_soon_threadsafe(queue.put_nowait, chunk)
            loop.call_soon_threadsafe(queue.put_nowait, None)

        loop.run_in_executor(None, run)

        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            final_state = chunk
            trace = chunk.get("trace", [])
            # Emit any newly-completed trace steps.
            while seen < len(trace):
                step = trace[seen]
                seen += 1
                yield {"event": "step", "data": json.dumps(step, default=str)}

        final = final_state.get("final") or {}
        yield {"event": "final", "data": json.dumps(final, default=str)}

    return EventSourceResponse(gen())
