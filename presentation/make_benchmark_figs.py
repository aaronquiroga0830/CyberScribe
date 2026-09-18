"""Presentation figures from the n=100 benchmark (300 trials).

Reads output/benchmark/experiment3/results.csv and produces:
  fig_tradeoff_labeled  - structured success rate vs success-only latency
  fig_failure_modes     - how each model's 100 trials actually ended
"""
from __future__ import annotations

import csv
import os
import statistics as st
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "assets")
CSV = os.path.join(ROOT, "output", "benchmark", "experiment3", "results.csv")
os.makedirs(OUT, exist_ok=True)

plt.rcParams["font.family"] = ["Arial", "DejaVu Sans"]

NAVY = "#0C182B"
GRAY = "#5B6675"
GREEN = "#2E8B6B"
AMBER = "#D99A2B"
RED = "#C0504D"
GRID = "#D5D9DF"

ORDER = ["gemma2:2b", "phi3", "llama3.2:3b"]
INVOKE_CAP_S = 210.0


def truthy(v: str) -> bool:
    return str(v).strip().lower() in ("true", "1", "yes")


def load():
    rows = list(csv.DictReader(open(CSV, newline="", encoding="utf-8-sig")))
    by = defaultdict(list)
    for r in rows:
        by[r["model"]].append(r)
    stats = {}
    for m, rs in by.items():
        succ = [r for r in rs if truthy(r["structured_success"])]
        fail = [r for r in rs if not truthy(r["structured_success"])]
        parse = [r for r in fail if truthy(r["parse_failed"])]
        timeout = [r for r in fail
                   if not truthy(r["parse_failed"])
                   and float(r["generation_ms"]) / 1000.0 >= INVOKE_CAP_S - 5]
        other = [r for r in fail if r not in parse and r not in timeout]
        gs = [float(r["generation_ms"]) / 1000.0 for r in succ]
        stats[m] = {
            "n": len(rs),
            "success": len(succ),
            "parse": len(parse),
            "timeout": len(timeout),
            "other": len(other),
            "succ_mean": st.mean(gs) if gs else 0.0,
            "all_mean": st.mean([float(r["generation_ms"]) / 1000.0 for r in rs]),
            "fail_mean": (st.mean([float(r["generation_ms"]) / 1000.0 for r in fail])
                          if fail else 0.0),
        }
    return stats


S = load()
for m in ORDER:
    d = S[m]
    print(f"{m:14s} success={d['success']:3d} parse_fail={d['parse']:3d} "
          f"timeout={d['timeout']:3d} other={d['other']:3d} "
          f"succ_mean={d['succ_mean']:6.1f}s fail_mean={d['fail_mean']:6.1f}s")

# --------------------------------------------------------------------------
# Figure 1: reliability vs latency
# --------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(11, 8.4))
COLORS = {"gemma2:2b": GREEN, "phi3": "#4F81BD", "llama3.2:3b": RED}
LABEL_OFF = {
    "gemma2:2b": (0.0, 16.0, "center"),
    "phi3": (7.0, 0.0, "left"),
    "llama3.2:3b": (7.0, 0.0, "left"),
}

for m in ORDER:
    d = S[m]
    x = 100.0 * d["success"] / d["n"]
    y = d["succ_mean"]
    ax.scatter([x], [y], s=1100, c=COLORS[m], edgecolors=NAVY,
               linewidths=2.2, zorder=5)
    dx, dy, ha = LABEL_OFF[m]
    ax.annotate(
        f"{m}\n{x:.0f}% success  ·  {y:.1f} s",
        xy=(x, y), xytext=(x + dx, y + dy), ha=ha, va="center",
        fontsize=19, color=NAVY, fontweight="bold", zorder=6,
        linespacing=1.45,
    )

ax.set_xlabel("Structured success rate  (% of 100 trials)", fontsize=21,
              color=NAVY, labelpad=12)
ax.set_ylabel("Generation time on successful trials  (s)", fontsize=21,
              color=NAVY, labelpad=12)
ax.set_xlim(-6, 128)
ax.set_ylim(-6, 112)
ax.tick_params(labelsize=18, colors=NAVY)
ax.grid(True, linestyle="--", linewidth=1.1, color=GRID, zorder=0)
ax.set_axisbelow(True)
for sp in ("top", "right"):
    ax.spines[sp].set_visible(False)
for sp in ("left", "bottom"):
    ax.spines[sp].set_color(GRAY)
    ax.spines[sp].set_linewidth(1.6)

ax.text(4, 6, "lower and further right is better",
        fontsize=18, color=GRAY, style="italic", ha="left", va="center")

fig.tight_layout(pad=0.6)
for ext in ("png", "pdf"):
    p = os.path.join(OUT, f"fig_tradeoff_labeled.{ext}")
    fig.savefig(p, dpi=200, facecolor="white", bbox_inches="tight")
    print("wrote", p)
plt.close(fig)

# --------------------------------------------------------------------------
# Figure 2: failure modes
# --------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(14, 6.6))
ys = list(range(len(ORDER)))[::-1]
H = 0.52

for y, m in zip(ys, ORDER):
    d = S[m]
    left = 0
    segs = [
        (d["success"], GREEN, "success"),
        (d["parse"], AMBER, "parse"),
        (d["timeout"], RED, "timeout"),
        (d["other"], GRAY, "other"),
    ]
    for val, color, _kind in segs:
        if val <= 0:
            continue
        ax.barh(y, val, left=left, height=H, color=color,
                edgecolor="white", linewidth=2.0, zorder=3)
        if val >= 6:
            ax.text(left + val / 2.0, y, f"{val}", ha="center", va="center",
                    fontsize=21, color="white", fontweight="bold", zorder=4)
        else:
            ax.text(left + val / 2.0, y - 0.47, f"{val}", ha="center", va="top",
                    fontsize=17, color=color, fontweight="bold", zorder=4)
        left += val

ax.set_yticks(ys)
ax.set_yticklabels(ORDER, fontsize=23, color=NAVY, fontweight="bold")
ax.set_xlim(0, 100)
ax.set_xlabel("Trials out of 100", fontsize=20, color=NAVY, labelpad=10)
ax.tick_params(axis="x", labelsize=17, colors=NAVY)
ax.tick_params(axis="y", length=0)
ax.grid(axis="x", linestyle="--", linewidth=1.1, color=GRID, zorder=0)
ax.set_axisbelow(True)
for sp in ("top", "right", "left"):
    ax.spines[sp].set_visible(False)
ax.spines["bottom"].set_color(GRAY)

handles = [
    plt.Rectangle((0, 0), 1, 1, color=GREEN),
    plt.Rectangle((0, 0), 1, 1, color=AMBER),
    plt.Rectangle((0, 0), 1, 1, color=RED),
]
labels = [
    "Valid structured edit",
    "Malformed JSON  (mean 17.5 s)",
    "Timed out at 210 s cap",
]
ax.legend(handles, labels, fontsize=19, loc="upper center",
          bbox_to_anchor=(0.5, -0.17), ncol=3, frameon=False,
          handlelength=1.5, columnspacing=2.2)

fig.tight_layout(pad=0.6)
for ext in ("png", "pdf"):
    p = os.path.join(OUT, f"fig_failure_modes.{ext}")
    fig.savefig(p, dpi=200, facecolor="white", bbox_inches="tight")
    print("wrote", p)
plt.close(fig)
