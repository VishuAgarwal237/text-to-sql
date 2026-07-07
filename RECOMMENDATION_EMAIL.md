**To:** Andrea Chen <andrea.chen@melodystream.com>
**From:** Solutions Team <solutions@fireworks.ai>
**Subject:** Re: Help Needed: Text-to-SQL for Internal BI Tool

Hi Andrea,

Thanks for the detailed context. We built a working prototype against your Chinook database and,
more importantly, an **evaluation framework** so decisions here are driven by numbers rather than
spot-checks. Below are direct answers to your three questions, plus how to run everything.

---

### 1. How do we measure if the model is working — and what's a good target?

The right metric is **execution accuracy**: run the model's SQL and the ground-truth SQL, then
compare the *result sets* (order-insensitive, with rounding and the duplicate-row cases your data
legitimately has). This is fairer than string-matching SQL, because many different queries are
correct. We complement it with a **valid-SQL rate** (does it parse and run at all) and a
**per-category** breakdown (simple filters vs. joins vs. date filters vs. aggregations), so you can
see *where* it fails, not just how often.

We wired this into **Braintrust**, so every model run is an experiment you can compare side-by-side,
drill into per question, and track over time as you iterate. A local report
(`EVAL_REPORT.md`) also produces a leaderboard and a per-category confusion matrix.

**Target:** for an internal BI assistant, we'd aim for **≥ 90% execution accuracy** on a
representative eval set before rollout, with a human-in-the-loop "here's the SQL I ran" step (which
the UI shows) so analysts can verify the ~10% edge cases. Start at your current 10 cases and grow
the eval set to 50–100 real questions from your teams — that's the single highest-leverage thing you
can do.

### 2. How do we improve on the naive prompt?

Your PoC prompt (`Convert this question to SQL: {question}`) fails because the model has **no schema
and no business context** — hence the hallucinated table names. We replaced it with a small
**multi-agent pipeline**, and each stage is a measurable accuracy lever:

- **Schema hydration + a metadata catalog** — the biggest win. We generate a rich catalog of your
  tables/columns (descriptions, synonyms, join paths, and business metrics like
  *revenue = SUM(InvoiceLine.UnitPrice × Quantity)*) and feed only the relevant slice to the model.
  This kills the hallucinations and resolves ambiguous phrasing.
- **Grounded generation + few-shot** — SQLite-dialect rules (dates via `strftime`, `||` concat) and
  curated examples.
- **A self-correcting validation loop** — every query is parsed, `EXPLAIN`-checked, and guarded to
  be read-only; on failure the exact error is fed back for one or more repair attempts. This alone
  removes most "invalid SQL" failures.
- **A router** that keeps non-questions out of the SQL path, and **summary + auto-visualization** on
  the way out.

Each layer is independently measurable in the eval harness, so you can quantify what each buys you.

### 3. Which model should we use?

Because you'll run this **all day**, cost and latency matter as much as accuracy — so we made the
system **model-agnostic** and benchmark three tiers on the same eval:

- a **Fireworks-hosted open model** (cheapest/fastest),
- **Claude Haiku 4.5** ($1 / $5 per 1M tokens — cheap, fast),
- **Claude Sonnet 5** ($3 / $15 — higher accuracy).

A text-to-SQL request is small (a few thousand tokens), so **per-query cost is a fraction of a cent
even on the priciest option** — accuracy and latency should drive the choice, not raw token price.
Our recommendation pattern: **default to the cheapest model that clears your accuracy bar** (often an
open model or Haiku for this workload), and reserve the stronger model for queries flagged as
hard. The eval report picks this automatically from your numbers; see `EVAL_REPORT.md`.

> Note: the accuracy numbers in the committed `EVAL_REPORT.md` were produced with an offline
> deterministic stub so the harness runs without keys. Drop in a provider key and re-run
> `python eval/run_eval.py` to get real per-model numbers on your data.

---

### What we're handing over

- A running **web app** (ask a question → summary + the SQL + results table + auto-chart), matching
  the mockup.
- The **evaluation framework** (Braintrust + local report) and the multi-model benchmark.
- The full **agent pipeline**, the **metadata-generation prompt** (saved for your review), and
  **Docker** deployment (`docker compose up`).
- Read-only safety throughout (no query can modify your database).

**Run it:** `./setup.sh && cp .env.example .env` (add a key) `&& docker compose up --build` → UI at
`http://localhost:3000`. Full instructions in `README.md`.

### Recommended next steps

1. **Grow the eval set** to 50–100 real analyst questions (biggest accuracy lever).
2. Run the benchmark on your key to lock the **model choice** on real numbers.
3. Add a **few-shot example store** seeded from questions your teams actually ask.
4. Layer in **caching** for repeated questions and a lightweight **feedback thumbs-up/down** to grow
   the eval set continuously.
5. Optional: role-based row/column scoping if different teams should see different data.

We used Claude (via Claude Code) to help build this prototype. Happy to walk through the eval
results live and tailor the model choice to your latency/cost budget.

Best,
Solutions Team, Fireworks.ai
