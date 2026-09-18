"""Regenerate the system architecture diagram for the HPEC talk.

Replaces the flat left-to-right chain with three lanes inside a mission boundary:
ingest (populates the index), generate (reads it), review (the human loop).
"""
from __future__ import annotations

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
os.makedirs(OUT, exist_ok=True)

plt.rcParams["font.family"] = ["Arial", "DejaVu Sans"]

NAVY = "#0C182B"
TEAL_EDGE = "#12726A"
TEAL_FILL = "#E2F1EF"
PURPLE_EDGE = "#6B4E9B"
PURPLE_FILL = "#EFE9F7"
GRAY_EDGE = "#5B6675"
GRAY_FILL = "#EEF0F3"

FS_MAIN = 22
FS_SUB = 16
FS_ARROW = 16
FS_LANE = 19

fig, ax = plt.subplots(figsize=(16, 8))
ax.set_xlim(0, 100)
ax.set_ylim(0, 100)
ax.axis("off")


def box(x0, x1, y0, y1, title, sub=None, kind="teal"):
    fill, edge = {
        "teal": (TEAL_FILL, TEAL_EDGE),
        "purple": (PURPLE_FILL, PURPLE_EDGE),
        "gray": (GRAY_FILL, GRAY_EDGE),
    }[kind]
    ax.add_patch(
        FancyBboxPatch(
            (x0, y0), x1 - x0, y1 - y0,
            boxstyle="round,pad=0,rounding_size=1.6",
            facecolor=fill, edgecolor=edge, linewidth=2.4, zorder=3,
        )
    )
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if sub:
        ax.text(cx, cy + 2.1, title, ha="center", va="center", fontsize=FS_MAIN,
                color=NAVY, fontweight="bold", zorder=4)
        ax.text(cx, cy - 2.8, sub, ha="center", va="center", fontsize=FS_SUB,
                color=GRAY_EDGE, zorder=4)
    else:
        ax.text(cx, cy, title, ha="center", va="center", fontsize=FS_MAIN,
                color=NAVY, fontweight="bold", zorder=4)


def arrow(p0, p1, color=NAVY, lw=2.6, style="-", zorder=2):
    ax.add_patch(
        FancyArrowPatch(
            p0, p1, arrowstyle="-|>", mutation_scale=26, linewidth=lw,
            color=color, linestyle=style, shrinkA=0, shrinkB=0, zorder=zorder,
            joinstyle="miter",
        )
    )


def elbow(pts, color=NAVY, lw=2.6, style="-"):
    """Polyline with an arrowhead on the final segment."""
    for a, b in zip(pts[:-2], pts[1:-1]):
        ax.plot([a[0], b[0]], [a[1], b[1]], color=color, linewidth=lw,
                linestyle=style, solid_capstyle="round", zorder=2)
    arrow(pts[-2], pts[-1], color=color, lw=lw, style=style)


# --- mission boundary -------------------------------------------------------
ax.add_patch(
    Rectangle((2.5, 4.0), 95.0, 88.0, fill=False, edgecolor=NAVY,
              linewidth=2.8, linestyle=(0, (7, 5)), zorder=1)
)
ax.text(5.0, 88.2, "Mission workspace  —  locally hosted, isolated per mission",
        ha="left", va="center", fontsize=FS_LANE, color=NAVY, fontweight="bold")

# --- lane labels ------------------------------------------------------------
for y, label, color in [
    (76, "INGEST", TEAL_EDGE),
    (50, "GENERATE", TEAL_EDGE),
    (22, "REVIEW", PURPLE_EDGE),
]:
    ax.text(4.6, y, label, ha="center", va="center", fontsize=FS_LANE,
            color=color, fontweight="bold", rotation=90)

# --- lane 1: ingest ---------------------------------------------------------
box(9, 31, 70, 82, "Mission artifacts", ".txt  ·  .pdf  ·  .docx", "gray")
box(39, 61, 70, 82, "Normalize + embed", "chunk  ·  tag  ·  encode", "teal")
box(69, 91, 70, 82, "Mission index", "FAISS vector store", "teal")
arrow((31, 76), (39, 76))
arrow((61, 76), (69, 76))

# --- lane 2: generate -------------------------------------------------------
box(9, 31, 44, 56, "Report template", "RMP · Timeline · AAR · SITREP", "gray")
box(39, 61, 44, 56, "gemma2:2b", "local, via Ollama", "teal")
box(69, 91, 44, 56, "Proposed edit", "block-level change", "teal")
arrow((31, 50), (39, 50))
arrow((61, 50), (69, 50))

# index feeds the model
elbow([(80, 70), (80, 63), (50, 63), (50, 56)], color=TEAL_EDGE)
ax.text(64.5, 65.0, "retrieved evidence", ha="center", va="bottom",
        fontsize=FS_ARROW, color=TEAL_EDGE, style="italic")

# --- lane 3: review ---------------------------------------------------------
box(39, 61, 16, 28, "Operator review", "accept  ·  reject", "purple")
box(69, 91, 16, 28, "Approved report", ".docx to mission output", "gray")

# proposed edit drops into review
elbow([(80, 44), (80, 36), (50, 36), (50, 28)], color=PURPLE_EDGE)
arrow((61, 22), (69, 22), color=PURPLE_EDGE)
ax.text(65.0, 23.4, "accept", ha="center", va="bottom", fontsize=FS_ARROW,
        color=PURPLE_EDGE, style="italic")

# the review loop back into the draft
elbow([(39, 22), (20, 22), (20, 44)], color=PURPLE_EDGE, lw=3.4,
      style=(0, (6, 4)))
ax.text(21.5, 33.5, "accepted edits\nupdate the draft", ha="left", va="center",
        fontsize=FS_ARROW, color=PURPLE_EDGE, style="italic")

fig.tight_layout(pad=0.3)
for ext in ("png", "pdf"):
    path = os.path.join(OUT, f"fig_architecture.{ext}")
    fig.savefig(path, dpi=200, facecolor="white", bbox_inches="tight")
    print("wrote", path)
