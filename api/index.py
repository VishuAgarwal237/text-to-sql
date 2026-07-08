"""Vercel Python serverless entrypoint for the FastAPI backend.

Vercel's Python runtime serves the ASGI `app` exported here. We add the sibling `backend/`
directory to the import path, force the in-process (direct) execution backend — serverless
functions can't spawn the MCP subprocess — and point at the bundled read-only Chinook DB.

Configure env vars in the Vercel project (Settings -> Environment Variables):
  OPENAI_API_KEY, LLM_BACKEND (litellm|stub), DEFAULT_MODEL (default openai/gpt-4o-mini).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

os.environ.setdefault("EXEC_BACKEND", "direct")
os.environ.setdefault("CHINOOK_DB_PATH", str(ROOT / "data" / "Chinook.db"))

from app.main import app  # noqa: E402  (ASGI app served by @vercel/python)
