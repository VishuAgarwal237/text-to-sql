"""Generate EVAL_REPORT.md + a per-category confusion-matrix heatmap from eval results.

Reads eval/results/<model>.json (written by run_eval.py) and produces:
  - a model leaderboard (execution accuracy, valid-SQL rate, avg cost, avg latency),
  - a per-category accuracy breakdown across models,
  - a correct/incorrect confusion matrix (category x outcome) heatmap PNG for the best model,
  - a model recommendation on the accuracy/cost/latency trade-off.

Usage: python eval/report.py
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"
REPORT = HERE.parent.parent / "EVAL_REPORT.md"


def _load() -> list[dict]:
    if not RESULTS_DIR.exists():
        raise SystemExit("No results found. Run: python eval/run_eval.py")
    summaries = [json.loads(p.read_text()) for p in sorted(RESULTS_DIR.glob("*.json"))]
    if not summaries:
        raise SystemExit("No results found. Run: python eval/run_eval.py")
    return summaries


def _confusion_png(summary: dict) -> Path:
    """Category x {correct, incorrect} counts for one model, as a heatmap PNG."""
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])  # [correct, incorrect]
    for r in summary["results"]:
        counts[r["category"]][0 if r["execution_accuracy"] == 1.0 else 1] += 1
    cats = sorted(counts)
    matrix = [counts[c] for c in cats]

    fig, ax = plt.subplots(figsize=(6, 0.6 * len(cats) + 1.5))
    im = ax.imshow(matrix, cmap="Greens", aspect="auto")
    ax.set_xticks([0, 1], ["correct", "incorrect"])
    ax.set_yticks(range(len(cats)), cats)
    ax.set_title(f"Confusion matrix — {summary['model']}\n(execution accuracy per category)")
    for i in range(len(cats)):
        for j in range(2):
            ax.text(j, i, matrix[i][j], ha="center", va="center",
                    color="black", fontsize=11)
    fig.colorbar(im, ax=ax, label="cases")
    fig.tight_layout()
    out = RESULTS_DIR / f"confusion_matrix_{summary['model']}.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    return out


def main() -> None:
    summaries = _load()
    summaries.sort(key=lambda s: (-s["execution_accuracy"], s["avg_cost_usd"]))
    best = summaries[0]
    png = _confusion_png(best)

    all_cats = sorted({r["category"] for s in summaries for r in s["results"]})

    lines: list[str] = []
    lines.append("# Text-to-SQL Evaluation Report\n")
    lines.append("**Database:** Chinook (SQLite) · **Eval set:** 10 ground-truth cases · "
                 "**Primary metric:** execution accuracy (order-insensitive result-set match).\n")

    # Leaderboard
    lines.append("## Model leaderboard\n")
    lines.append("| Rank | Model | Exec. accuracy | Valid SQL | Avg cost/query | Avg latency |")
    lines.append("|---|---|---|---|---|---|")
    for i, s in enumerate(summaries, 1):
        lines.append(
            f"| {i} | `{s['model']}` | **{s['execution_accuracy']:.0%}** | "
            f"{s['valid_sql_rate']:.0%} | ${s['avg_cost_usd']:.4f} | {s['avg_latency_s']:.2f}s |"
        )
    lines.append("")

    # Per-category accuracy
    lines.append("## Accuracy by question category\n")
    header = "| Category | " + " | ".join(f"`{s['model']}`" for s in summaries) + " |"
    lines.append(header)
    lines.append("|" + "---|" * (len(summaries) + 1))
    for cat in all_cats:
        row = [cat]
        for s in summaries:
            cases = [r for r in s["results"] if r["category"] == cat]
            acc = sum(r["execution_accuracy"] for r in cases) / len(cases) if cases else 0
            row.append(f"{acc:.0%} ({len(cases)})")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    # Confusion matrix
    lines.append("## Confusion matrix (best model)\n")
    lines.append(f"Per-category correct/incorrect for the top model `{best['model']}`:\n")
    lines.append(f"![confusion matrix](backend/eval/results/{png.name})\n")

    # Recommendation
    lines.append("## Recommendation\n")
    cheapest_good = min(
        (s for s in summaries if s["execution_accuracy"] >= best["execution_accuracy"] - 0.1),
        key=lambda s: s["avg_cost_usd"],
    )
    lines.append(
        f"- **Highest accuracy:** `{best['model']}` at {best['execution_accuracy']:.0%} "
        f"execution accuracy.\n"
        f"- **Best value:** `{cheapest_good['model']}` — within 10 points of the top accuracy "
        f"({cheapest_good['execution_accuracy']:.0%}) at ${cheapest_good['avg_cost_usd']:.4f}/query "
        f"and {cheapest_good['avg_latency_s']:.2f}s latency.\n"
        f"- For a BI tool used heavily throughout the day, recommend **`{cheapest_good['model']}`** "
        f"as the default (cost/latency), reserving `{best['model']}` for hard queries if accuracy "
        f"headroom is needed.\n"
    )

    # Failure inspection
    lines.append("## Failed cases (top model)\n")
    fails = [r for r in best["results"] if r["execution_accuracy"] != 1.0]
    if not fails:
        lines.append("_None — the top model answered all cases correctly._\n")
    else:
        for r in fails:
            lines.append(f"- **{r['question']}** — {r['exec_reason']}")
            lines.append(f"  - predicted: `{r['pred_sql'][:160]}`")
    lines.append("")

    REPORT.write_text("\n".join(lines))
    print(f"Wrote {REPORT}")
    print(f"Confusion matrix: {png}")


if __name__ == "__main__":
    main()
