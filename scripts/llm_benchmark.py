#!/usr/bin/env python3
"""
LLM benchmark: compare local Ollama models on identical RMP structured-edit updates.
Writes output/benchmark/results.csv and matplotlib figures for thesis/proposal use.

Usage (from project root, venv active, Ollama running):
  python scripts/llm_benchmark.py --setup
  python scripts/llm_benchmark.py --run
  python scripts/llm_benchmark.py --plot
  python scripts/llm_benchmark.py --setup --run --plot
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

BENCHMARK_DIR = PROJECT_ROOT / "output" / "benchmark"
RESULTS_CSV = BENCHMARK_DIR / "results.csv"
META_JSON = BENCHMARK_DIR / "run_meta.json"
MISSION_NAME = "LLM Benchmark"
DEFAULT_MODELS = ["phi3", "llama3.2:3b", "gemma2:2b"]
DEFAULT_REPORT_TYPES = ["rmp"]
DEFAULT_JOB_TIMEOUT_S = 2400  # llama3.2:3b can exceed 15 min on 16 GB RAM CPU
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_benchmark_dir() -> None:
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)


def ollama_list() -> list[str]:
    try:
        out = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        print(f"Warning: ollama list failed: {e}")
        return []
    names: list[str] = []
    for line in out.stdout.strip().splitlines()[1:]:
        parts = line.split()
        if parts:
            names.append(parts[0])
    return names


def _model_present(model: str, installed: list[str]) -> bool:
    for x in installed:
        if x == model or x.startswith(model + ":") or model.startswith(x.split(":")[0]):
            return True
    return False


def ollama_pull(model: str) -> None:
    print(f"Pulling Ollama model: {model} ...")
    subprocess.run(["ollama", "pull", model], check=True, timeout=3600)


def ensure_models(models: list[str]) -> None:
    installed = ollama_list()
    for m in models:
        if _model_present(m, installed):
            print(f"Model already present: {m}")
        else:
            ollama_pull(m)


def init_server_state() -> None:
    import asyncio
    import threading

    import server

    if not getattr(server.app.state, "loop", None):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        server.app.state.loop = loop
        server.app.state.stream_buffers = {}
        server.app.state.stream_queues = {}
        server.app.state.stream_lock = threading.Lock()
        server.app.state.running_mission_id = None
    from src.mission_service import ensure_db

    ensure_db()


def set_active_model(model: str) -> None:
    os.environ["OLLAMA_MODEL"] = model
    import config.settings as settings
    import server

    settings.OLLAMA_MODEL = model
    server.OLLAMA_MODEL = model


def setup_mission(mission_id: str | None = None) -> str:
    from config.settings import OUTPUT_DIR, PROJECT_ROOT
    from src.index.build import build_mission_index, mission_index_exists
    from src.mission_service import create_mission, get_mission, list_missions

    source = (PROJECT_ROOT / "data" / "missions" / "sample_mission").resolve()
    if not source.is_dir():
        raise SystemExit(f"Sample mission not found: {source}")

    mid = mission_id
    if mid:
        if not get_mission(mid):
            raise SystemExit(f"Mission not found: {mid}")
    else:
        mid = None
        for m in list_missions():
            if m.get("name") == MISSION_NAME:
                mid = m["id"]
                break
        if not mid:
            out = (OUTPUT_DIR / "llm_benchmark").resolve()
            out.mkdir(parents=True, exist_ok=True)
            mid = create_mission(MISSION_NAME, str(source), str(out))
            print(f"Created mission: {mid}")

    if not mission_index_exists(mid):
        print(f"Building index for {mid} ...")
        build_mission_index(mid, source)
        print("Index build complete.")
    else:
        print(f"Index already exists for {mid}; skipping rebuild.")

    (BENCHMARK_DIR / "mission_id.txt").write_text(mid, encoding="utf-8")
    return mid


def load_mission_id(explicit: str | None) -> str:
    if explicit:
        return explicit
    p = BENCHMARK_DIR / "mission_id.txt"
    if p.is_file():
        return p.read_text(encoding="utf-8").strip()
    raise SystemExit("No mission_id; run with --setup first or pass --mission-id")


def parse_job_metrics(job: dict[str, Any], report_type: str) -> dict[str, Any]:
    progress = job.get("progress") or []
    metrics: dict[str, Any] = {
        "retrieval_ms": None,
        "generation_ms": None,
        "parse_validate_ms": None,
        "accepted_edit_count": None,
        "parse_failed": False,
        "fallback_used": bool(job.get("fallback_used")),
    }
    for ev in progress:
        if not isinstance(ev, dict):
            continue
        step = ev.get("step")
        detail = ev.get("detail") or {}
        if detail.get("report_type") and detail.get("report_type") != report_type:
            continue
        if step == "retrieval_done":
            metrics["retrieval_ms"] = detail.get("ms")
        elif step == "generation_done" and detail.get("phase") == "structured_edits":
            metrics["generation_ms"] = detail.get("ms")
        elif step == "parse_validate_done":
            metrics["parse_validate_ms"] = detail.get("ms")
            metrics["accepted_edit_count"] = detail.get("accepted_edit_count")
            metrics["parse_failed"] = bool(detail.get("parse_failed"))
        elif step == "structured_edits_fallback":
            metrics["fallback_used"] = True
    acc = metrics.get("accepted_edit_count") or 0
    metrics["structured_success"] = (
        acc > 0 and not metrics["parse_failed"] and not metrics["fallback_used"]
    )
    return metrics


def wait_for_job(mission_id: str, job_id: str, timeout_s: float = DEFAULT_JOB_TIMEOUT_S) -> dict[str, Any]:
    from src.pipeline_job_service import get_pipeline_job

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        job = get_pipeline_job(mission_id, job_id)
        if job and job.get("status") in ("completed", "failed"):
            return job
        time.sleep(2)
    raise TimeoutError(f"Job {job_id} did not finish within {timeout_s}s")


def prepare_trial(mission_id: str, report_type: str) -> None:
    """Clear pending edits and wait for any in-flight pipeline before starting a trial."""
    import server
    from src.report_service import reject_all_edits

    try:
        reject_all_edits(mission_id, report_type)
    except Exception as ex:
        print(f"    warning: pre-trial reject_all_edits: {ex}")

    for _ in range(120):
        if getattr(server.app.state, "running_mission_id", None) is None:
            break
        time.sleep(1)


def _row_from_job(
    mission_id: str,
    model: str,
    report_type: str,
    trial: int,
    job_id: str,
    wall: float,
    job: dict[str, Any] | None,
    *,
    job_status: str | None = None,
    error_message: str = "",
) -> dict[str, Any]:
    if not job:
        return {
            "model": model,
            "trial": trial,
            "report_type": report_type,
            "job_id": job_id,
            "wall_clock_s": round(wall, 2),
            "job_status": job_status or "unknown",
            "error_message": error_message,
            "structured_success": False,
            "parse_failed": True,
            "fallback_used": False,
            "accepted_edit_count": 0,
            "retrieval_ms": None,
            "generation_ms": None,
            "parse_validate_ms": None,
        }
    m = parse_job_metrics(job, report_type)
    return {
        "model": model,
        "trial": trial,
        "report_type": report_type,
        "job_id": job_id,
        "wall_clock_s": round(wall, 2),
        "retrieval_ms": m["retrieval_ms"],
        "generation_ms": m["generation_ms"],
        "parse_validate_ms": m["parse_validate_ms"],
        "accepted_edit_count": m["accepted_edit_count"],
        "parse_failed": m["parse_failed"],
        "fallback_used": m["fallback_used"],
        "structured_success": m["structured_success"],
        "job_status": job.get("status") or job_status or "unknown",
        "error_message": job.get("error_message") or error_message,
    }


def run_trial(
    mission_id: str,
    model: str,
    report_type: str,
    trial: int,
    *,
    timeout_s: float = DEFAULT_JOB_TIMEOUT_S,
) -> dict[str, Any]:
    import server
    from src.pipeline_job_service import get_pipeline_job
    from src.report_service import reject_all_edits

    prepare_trial(mission_id, report_type)
    set_active_model(model)
    print(f"  Trial {trial}: model={model} report={report_type} ...")

    t0 = time.monotonic()
    ok, err, job_id = server.request_mission_update(
        mission_id,
        report_types=[report_type],
        update_intent="full_refresh",
    )
    if not ok or not job_id:
        return {
            "model": model,
            "trial": trial,
            "report_type": report_type,
            "job_id": "",
            "wall_clock_s": round(time.monotonic() - t0, 2),
            "job_status": "request_failed",
            "error_message": err or "unknown",
            "structured_success": False,
            "parse_failed": True,
            "fallback_used": False,
            "accepted_edit_count": 0,
            "retrieval_ms": None,
            "generation_ms": None,
            "parse_validate_ms": None,
        }

    job: dict[str, Any] | None
    timeout_err = ""
    try:
        job = wait_for_job(mission_id, job_id, timeout_s=timeout_s)
    except TimeoutError as e:
        timeout_err = str(e)
        job = get_pipeline_job(mission_id, job_id)

    wall = time.monotonic() - t0
    row = _row_from_job(
        mission_id,
        model,
        report_type,
        trial,
        job_id,
        wall,
        job,
        job_status="timeout" if timeout_err and (not job or job.get("status") == "running") else None,
        error_message=timeout_err,
    )
    print(
        f"    done status={row['job_status']} gen_ms={row['generation_ms']} "
        f"edits={row['accepted_edit_count']} success={row['structured_success']}"
    )

    try:
        reject_all_edits(mission_id, report_type)
    except Exception as ex:
        print(f"    warning: reject_all_edits: {ex}")

    for _ in range(120):
        if getattr(server.app.state, "running_mission_id", None) is None:
            break
        time.sleep(1)

    return row


def append_results(rows: list[dict[str, Any]]) -> None:
    ensure_benchmark_dir()
    write_header = not RESULTS_CSV.is_file()
    with RESULTS_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def write_run_meta(models: list[str], mission_id: str) -> None:
    ensure_benchmark_dir()
    meta = {
        "created_at": _utc_now(),
        "mission_id": mission_id,
        "models": models,
        "report_types": DEFAULT_REPORT_TYPES,
        "ollama_list": ollama_list(),
        "note": "16GB RAM thesis benchmark; structured_success = edits>0, no parse fail, no fallback",
    }
    META_JSON.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def run_benchmark(
    mission_id: str,
    models: list[str],
    report_types: list[str],
    trials: int,
    fresh_results: bool = True,
    timeout_s: float = DEFAULT_JOB_TIMEOUT_S,
) -> None:
    init_server_state()
    if fresh_results and RESULTS_CSV.is_file():
        RESULTS_CSV.unlink()
    all_rows: list[dict[str, Any]] = []
    for model in models:
        print(f"\n=== Model batch: {model} ===")
        for trial in range(1, trials + 1):
            for rt in report_types:
                row = run_trial(mission_id, model, rt, trial, timeout_s=timeout_s)
                all_rows.append(row)
                append_results([row])
        time.sleep(3)
    write_run_meta(models, mission_id)
    print(f"\nWrote {len(all_rows)} rows to {RESULTS_CSV}")


def plot_results() -> None:
    try:
        import matplotlib.pyplot as plt
        import pandas as pd
    except ImportError as e:
        raise SystemExit("Install plotting deps: pip install matplotlib pandas") from e

    if not RESULTS_CSV.is_file():
        raise SystemExit(f"No results at {RESULTS_CSV}; run --run first")

    df = pd.read_csv(RESULTS_CSV)
    if df.empty:
        raise SystemExit("results.csv is empty")

    ensure_benchmark_dir()
    models = list(df["model"].unique())
    colors = ["#4C72B0", "#55A868", "#C44E52", "#8172B2", "#CCB974"]

    fig1, ax1 = plt.subplots(figsize=(8, 5))
    gen = df.groupby("model")["generation_ms"].agg(["mean", "std"]).reindex(models)
    x = range(len(models))
    means_s = gen["mean"].fillna(0) / 1000.0
    stds_s = gen["std"].fillna(0) / 1000.0
    ax1.bar(x, means_s, yerr=stds_s, capsize=5, color=colors[: len(models)])
    ax1.axhline(120, color="gray", linestyle="--", linewidth=1, label="120s reference")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(models, rotation=15, ha="right")
    ax1.set_ylabel("LLM generation time (seconds)")
    ax1.set_title("Structured-edit generation latency by model")
    ax1.legend()
    fig1.tight_layout()
    fig1.savefig(BENCHMARK_DIR / "fig1_generation_latency.png", dpi=150)
    plt.close(fig1)

    fig2, ax2 = plt.subplots(figsize=(8, 5))
    success_rate = df.groupby("model")["structured_success"].mean().reindex(models) * 100
    ax2.bar(range(len(models)), success_rate.fillna(0), color=colors[: len(models)])
    ax2.set_ylim(0, 100)
    ax2.set_xticks(range(len(models)))
    ax2.set_xticklabels(models, rotation=15, ha="right")
    ax2.set_ylabel("Structured success rate (%)")
    ax2.set_title("Valid structured edits without fallback")
    fig2.tight_layout()
    fig2.savefig(BENCHMARK_DIR / "fig2_structured_success_rate.png", dpi=150)
    plt.close(fig2)

    fig3, ax3 = plt.subplots(figsize=(8, 5))
    r_mean = df.groupby("model")["retrieval_ms"].mean().reindex(models).fillna(0) / 1000.0
    g_mean = df.groupby("model")["generation_ms"].mean().reindex(models).fillna(0) / 1000.0
    p_mean = df.groupby("model")["parse_validate_ms"].mean().reindex(models).fillna(0) / 1000.0
    ax3.bar(models, r_mean, label="Retrieval", color="#8DA0CB")
    ax3.bar(models, g_mean, bottom=r_mean, label="Generation", color="#FC8D62")
    ax3.bar(models, p_mean, bottom=r_mean + g_mean, label="Parse/validate", color="#66C2A5")
    ax3.set_ylabel("Mean time (seconds)")
    ax3.set_title("Pipeline phase breakdown by model")
    ax3.legend()
    plt.setp(ax3.get_xticklabels(), rotation=15, ha="right")
    fig3.tight_layout()
    fig3.savefig(BENCHMARK_DIR / "fig3_phase_breakdown.png", dpi=150)
    plt.close(fig3)

    summary = df.groupby("model").agg(
        trials=("trial", "count"),
        mean_generation_s=("generation_ms", lambda s: round(s.mean() / 1000, 2) if s.notna().any() else None),
        mean_wall_clock_s=("wall_clock_s", "mean"),
        mean_accepted_edits=("accepted_edit_count", "mean"),
        structured_success_rate=("structured_success", "mean"),
        fallback_rate=("fallback_used", "mean"),
        parse_failure_rate=("parse_failed", "mean"),
    )
    summary.to_csv(BENCHMARK_DIR / "summary_table.csv")
    print(f"Charts saved under {BENCHMARK_DIR}")


def main() -> None:
    p = argparse.ArgumentParser(description="LLM benchmark for mission RAG platform")
    p.add_argument("--setup", action="store_true", help="Pull models and create/index mission")
    p.add_argument("--run", action="store_true", help="Run benchmark trials")
    p.add_argument("--plot", action="store_true", help="Generate charts from results.csv")
    p.add_argument("--mission-id", default=None)
    p.add_argument("--models", default=",".join(DEFAULT_MODELS))
    p.add_argument("--report-types", default=",".join(DEFAULT_REPORT_TYPES))
    p.add_argument("--trials", type=int, default=2)
    p.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_JOB_TIMEOUT_S,
        help="Seconds to wait for each pipeline job (default: 2400)",
    )
    args = p.parse_args()

    if not (args.setup or args.run or args.plot):
        p.print_help()
        raise SystemExit(1)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    report_types = [r.strip() for r in args.report_types.split(",") if r.strip()]
    ensure_benchmark_dir()

    if args.setup:
        ensure_models(models)
        mid = setup_mission(args.mission_id)
        write_run_meta(models, mid)
        print(f"Setup complete. mission_id={mid}")

    if args.run:
        mid = load_mission_id(args.mission_id)
        run_benchmark(mid, models, report_types, args.trials, timeout_s=float(args.timeout))

    if args.plot:
        plot_results()


if __name__ == "__main__":
    main()
