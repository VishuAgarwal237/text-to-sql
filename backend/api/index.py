"""Vercel Python serverless entrypoint for the FastAPI backend (standalone `backend/` root).

Vercel's Python runtime serves the ASGI `app` exported here. This entrypoint lives inside the
`backend/` project root, so the `app` package and the bundled data files all sit one level up.
It forces the in-process (direct) execution backend — serverless functions can't spawn the MCP
subprocess — and points at the bundled read-only Chinook DB.

Env vars are configured in the Vercel project (Settings -> Environment Variables):
  OPENAI_API_KEY, LLM_BACKEND (litellm|stub), DEFAULT_MODEL (default openai/gpt-4o-mini).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # the backend/ project root
sys.path.insert(0, str(ROOT))

os.environ.setdefault("EXEC_BACKEND", "direct")
os.environ.setdefault("CHINOOK_DB_PATH", str(ROOT / "data" / "Chinook.db"))

from app.main import app  # noqa: E402  (ASGI app served by @vercel/python)
