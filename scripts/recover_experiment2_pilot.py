#!/usr/bin/env python3
"""Rebuild Experiment 2 pilot (n=2) CSVs from SQLite pipeline_jobs into experiment2_pilot/."""
from __future__ import annotations

import csv
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

OUT = PROJECT_ROOT / "output" / "benchmark" / "experiment2_pilot"
DB = PROJECT_ROOT / "data" / "agentic_rag.db"

# Pilot completed before the n=10 anchor job f90ff186 (2026-06-01T23:00:18Z).
PILOT_JOBS: list[tuple[str, str, int]] = [
    ("030266c9-963d-4c5a-babf-2f6f0e478ca3", "phi3", 1),
    ("20af1b68-b390-4891-9568-0f9f41f92a18", "phi3", 2),
    ("4fdf3f04-00fa-4e91-99dc-9f0d794a55a4", "llama3.2:3b", 1),
    ("802f69af-17bc-477b-ac01-9e899bb9b45c", "llama3.2:3b", 2),
    ("ee02910e-02d8-42e7-bf88-83b183aa3887", "gemma2:2b", 1),
]

CSV_FIELDS = [
    "model",
    "trial",
    "report_type",
    "job_id",
    "wall_clock_s",
    "retrieval_ms",
    "generation_ms",
    "parse_validate_ms",
    "accepted_edit_count",
    "parse_failed",
    "fallback_used",
    "structured_success",
    "job_status",
    "error_message",
]


def _parse_job(jid: str) -> dict:
    with sqlite3.connect(DB) as conn:
        row = conn.execute(
            "SELECT status, created_at, finished_at, progress_json FROM pipeline_jobs WHERE id=?",
            (jid,),
        ).fetchone()
    if not row:
        raise SystemExit(f"Job not found: {jid}")
    status, created_at, finished_at, progress_json = row
    prog = json.loads(progress_json or "[]")
    metrics = {
        "retrieval_ms": None,
        "generation_ms": None,
        "parse_validate_ms": None,
        "accepted_edit_count": 0,
        "parse_failed": False,
        "fallback_used": False,
    }
    for ev in prog:
        step = ev.get("step")
        detail = ev.get("detail") or {}
        if step == "retrieval_done":
            metrics["retrieval_ms"] = detail.get("ms")
        elif step == "generation_done" and detail.get("phase") == "structured_edits":
            metrics["generation_ms"] = detail.get("ms")
        elif step == "parse_validate_done":
            metrics["parse_validate_ms"] = detail.get("ms")
            metrics["accepted_edit_count"] = detail.get("accepted_edit_count") or 0
            metrics["parse_failed"] = bool(detail.get("parse_failed"))
        elif step == "structured_edits_fallback":
            metrics["fallback_used"] = True
    wall = 0.0
    if created_at and finished_at:
        t0 = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        t1 = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
        wall = round((t1 - t0).total_seconds(), 2)
    metrics["structured_success"] = (
        metrics["accepted_edit_count"] > 0
        and not metrics["parse_failed"]
        and not metrics["fallback_used"]
    )
    return {
        "job_id": jid,
        "wall_clock_s": wall,
        "job_status": status or "unknown",
        "error_message": "",
        **metrics,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for jid, model, trial in PILOT_JOBS:
        parsed = _parse_job(jid)
        rows.append(
            {
                "model": model,
                "trial": trial,
                "report_type": "rmp",
                **parsed,
            }
        )

    with (OUT / "results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    readme = """# Experiment 2 pilot (n=2 per model) — recovered

The original pilot CSV/figures in `output/benchmark/experiment2/` were **deleted**
when the canonical n=10 run started with `fresh_results=True` (2026-06-01 ~18:00 local).

This folder restores **best-effort** trial rows from SQLite `pipeline_jobs`.
Judge CSVs and pilot figures were **not** recoverable from disk.
**gemma trial 2** row was lost in the overwrite (only 5 of 6 pilot trials recovered here).

- **Canonical n=10 run:** `output/benchmark/experiment2/`
- **Experiment 1 (May 31, different protocol):** `output/benchmark/results.csv`
- **Pilot aggregates** cited in the paper/BENCHMARK_REPORT §14 may differ slightly
  from this reconstruction; treat `docs/paper/benchmark_results_section.txt`
  pilot table as the documented reference unless re-run.

Regenerate pilot figures (does not touch experiment2/):

  python scripts/llm_benchmark.py --plot --experiment-id experiment2_pilot
"""
    (OUT / "README.md").write_text(readme, encoding="utf-8")
    print(f"Wrote {len(rows)} rows to {OUT / 'results.csv'}")
    print("See", OUT / "README.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
