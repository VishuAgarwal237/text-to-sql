# Deploying to Vercel

This repo is set up to run **entirely on Vercel** as **two projects from the same GitHub repo**:

| Vercel project | Root Directory | What it serves |
|---|---|---|
| **backend** | repo root (`.`) | FastAPI + LangGraph as a Python serverless function (`api/index.py`, config in `vercel.json`) |
| **frontend** | `frontend` | Next.js UI |

They must be **two separate Vercel projects** because they use different Root Directories. Deploy
the backend first (you need its URL for the frontend).

---

## 1. Backend project (Python API)

1. In Vercel → **Add New → Project** → import `VishuAgarwal237/text-to-sql`.
2. **Root Directory:** leave as the repo root (`.`).
3. Vercel auto-detects `api/index.py` (Python) and reads `vercel.json`. The rewrite
   `"/(.*)" → "/api/index"` sends all paths to the FastAPI app; `includeFiles` bundles
   `data/Chinook.db`; deps come from `api/requirements.txt` (slim — no matplotlib/pandas/mcp).
4. **Environment Variables** (Settings → Environment Variables):
   - `OPENAI_API_KEY` = your key
   - `LLM_BACKEND` = `litellm`  (or `stub` for a keyless demo)
   - `DEFAULT_MODEL` = `openai/gpt-4o-mini`
   - `EXEC_BACKEND` = `direct`  (serverless can't spawn the MCP subprocess)
5. **Deploy.** Verify: `https://<backend>.vercel.app/health` → `{"status":"ok",...}`.

> Notes: cold starts take a few seconds (langgraph + litellm import). The `/query` endpoint is
> the main path; `/stream` (SSE) works but is subject to Vercel's function duration limit
> (`maxDuration` is set to 60s in `vercel.json`).

## 2. Frontend project (Next.js)

1. Vercel → **Add New → Project** → import the **same repo** again.
2. **Root Directory:** set to `frontend`.
3. **Environment Variable:**
   - `NEXT_PUBLIC_API_URL` = `https://<backend>.vercel.app`  (the backend URL from step 1)
4. **Deploy.** Open `https://<frontend>.vercel.app` and ask a question.

The backend allows all origins by default (CORS `*`), so the two Vercel domains talk to each
other out of the box. To lock it down, set `CORS_ORIGINS=https://<frontend>.vercel.app` on the
backend project.

---

## CLI alternative

```bash
npm i -g vercel && vercel login
# Backend (from repo root):
vercel --prod
# Frontend:
cd frontend && vercel --prod
# Set env vars with:  vercel env add OPENAI_API_KEY
```

---

## Robust alternative for the backend (Render / Railway / Fly)

If you prefer a long-running container over serverless (keeps the MCP execution path, no cold
starts, easier for heavy eval deps), deploy the backend with the existing `Dockerfile.backend`:

- **Render/Railway:** new **Web Service from Dockerfile** → `Dockerfile.backend`. Ensure the
  Chinook DB is available in the container — either bake it in (add `COPY data/ /data/` and keep
  `CHINOOK_DB_PATH=/data/Chinook.db`) or download it in a build step (`setup.sh`).
- Set the same env vars (`OPENAI_API_KEY`, `LLM_BACKEND`, `DEFAULT_MODEL`).
- Point the Vercel **frontend**'s `NEXT_PUBLIC_API_URL` at the container URL.

This keeps the frontend on Vercel (its best home) while the backend runs where a Python service
with a bundled database is happiest.
