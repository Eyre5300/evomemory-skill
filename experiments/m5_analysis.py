"""M5: analysis & publication-style figures from the experiment result JSONs.

Loads the latest results (no re-running, no API) and produces:
  fig1  cost vs success  — baseline vs +experience (the token/success Pareto direction)
  fig2  experience quality — final P per candidate experience (M3 quality filtering)
  fig3  per-task flip — baseline vs retry pass across the multi-task SWE suite
plus a summary CSV.

Run from repo root:
    python -m experiments.m5_analysis
"""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .config import RESULTS_DIR  # noqa: E402

FIGDIR = RESULTS_DIR / "figures"


def _latest(prefix: str) -> dict | None:
    files = sorted(RESULTS_DIR.glob(f"{prefix}*.json"), key=lambda p: p.stat().st_mtime)
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


def fig_cost_success(swe, out):
    """Baseline vs +experience as (avg_steps, success%) points — the Pareto direction."""
    recs = [r for r in swe["records"] if r.get("needs_experience")]
    if not recs:
        return None
    n = len(swe["seeds"])
    base_steps = statistics.mean(s for r in recs for s in r["baseline_steps"])
    retry_steps = statistics.mean(s for r in recs for s in r["retry_steps"])
    base_succ = 0.0
    retry_succ = 100.0 * sum(r["retry_pass"] for r in recs) / (len(recs) * n)

    plt.figure(figsize=(6, 4.2))
    plt.scatter([base_steps], [base_succ], s=140, c="#C0392B", label="baseline (no experience)", zorder=3)
    plt.scatter([retry_steps], [retry_succ], s=140, c="#1F4E79", label="+ shared experience", zorder=3)
    plt.annotate("", xy=(retry_steps, retry_succ), xytext=(base_steps, base_succ),
                 arrowprops=dict(arrowstyle="->", color="#888", lw=1.5))
    plt.text(base_steps, base_succ + 4, f"{base_steps:.1f} steps\n{base_succ:.0f}%", ha="center", fontsize=9)
    plt.text(retry_steps, retry_succ - 9, f"{retry_steps:.1f} steps\n{retry_succ:.0f}%", ha="center", fontsize=9)
    plt.xlabel("cost  (agent tool steps)")
    plt.ylabel("success rate  (%)")
    plt.title("Experience sharing: higher success at lower cost (real SWE-bench)")
    plt.ylim(-8, 112)
    plt.legend(loc="center right", fontsize=9)
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close()
    return {"baseline_steps": base_steps, "baseline_success": base_succ,
            "retry_steps": retry_steps, "retry_success": retry_succ}


def fig_quality(m3, out):
    """Final P per candidate experience (structural ties broken by verification)."""
    ranking = m3["ranking"]
    eids = [r["eid"] for r in ranking]
    ps = [r["P"] for r in ranking]
    colors = ["#1F4E79" if p >= 0.5 else "#C0392B" for p in ps]
    plt.figure(figsize=(6, 4))
    plt.bar(eids, ps, color=colors)
    plt.axhline(0.5, ls="--", c="#888", lw=1, label="selection threshold (min_P=0.5)")
    for i, p in enumerate(ps):
        plt.text(i, p + 0.02, f"{p:.2f}", ha="center", fontsize=9)
    plt.ylabel("Precision  P(e)")
    plt.title("Quality scoring separates the useful experience (M3)")
    plt.ylim(0, max(ps) + 0.15)
    plt.xticks(rotation=15, fontsize=8)
    plt.legend(fontsize=8)
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close()
    return dict(zip(eids, ps))


def fig_flips(swe, out):
    """Per-task baseline vs retry pass rate across the multi-task SWE suite."""
    n = len(swe["seeds"])
    recs = swe["records"]
    names = [r["task"].replace("flask_", "") for r in recs]
    base = [100.0 * r.get("baseline_pass", 0) / n for r in recs]
    retry = [100.0 * r.get("retry_pass", r.get("baseline_pass", 0)) / n for r in recs]
    x = range(len(names))
    plt.figure(figsize=(6.5, 4))
    plt.bar([i - 0.2 for i in x], base, width=0.4, label="baseline (qwen alone)", color="#C0392B")
    plt.bar([i + 0.2 for i in x], retry, width=0.4, label="+ shared experience", color="#1F4E79")
    plt.ylabel("pass rate  (%)")
    plt.title(f"Per-task flip on real Flask repo  (seeds={n})")
    plt.xticks(list(x), names, rotation=12, fontsize=8)
    plt.ylim(0, 112)
    plt.legend(fontsize=9)
    plt.tight_layout()
    plt.savefig(out, dpi=150)
    plt.close()


def main():
    FIGDIR.mkdir(parents=True, exist_ok=True)
    swe = _latest("swe_multi")
    m3 = _latest("m3_quality")
    summary = {}

    if swe:
        cs = fig_cost_success(swe, FIGDIR / "fig1_cost_success.png")
        fig_flips(swe, FIGDIR / "fig3_per_task_flip.png")
        summary["cost_success"] = cs
        summary["needs_experience"] = f"{swe['needs']}/{len(swe['records'])}"
        summary["flips"] = f"{swe['flips']}/{swe['needs']}"
        print(f"swe_multi: needs {swe['needs']}/{len(swe['records'])}, flips {swe['flips']}/{swe['needs']}, seeds={swe['seeds']}")
    else:
        print("(no swe_multi result yet)")

    if m3:
        q = fig_quality(m3, FIGDIR / "fig2_experience_quality.png")
        summary["m3_P"] = q
        print("m3 quality P:", {k: round(v, 2) for k, v in q.items()})

    # summary CSV
    with open(RESULTS_DIR / "m5_summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["metric", "value"])
        for k, v in summary.items():
            w.writerow([k, json.dumps(v, ensure_ascii=False)])

    print(f"figures -> {FIGDIR}")
    print(f"summary -> {RESULTS_DIR / 'm5_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
