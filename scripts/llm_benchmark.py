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
import atexit
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_BENCHMARK_LOCK_PATH: Path | None = None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

BENCHMARK_DIR = PROJECT_ROOT / "output" / "benchmark"
RESULTS_CSV = BENCHMARK_DIR / "results.csv"
META_JSON = BENCHMARK_DIR / "run_meta.json"
ACCURACY_CSV = BENCHMARK_DIR / "accuracy.csv"
ACCURACY_SUMMARY_CSV = BENCHMARK_DIR / "accuracy_summary.csv"
MISSION_NAME = "LLM Benchmark"
INCREMENTAL_MISSION_ID = "llm_benchmark_inc"
INCREMENTAL_MISSION_NAME = "LLM Benchmark Incremental"
EVAL_GOLD_DIR = PROJECT_ROOT / "data" / "eval" / "rmp_gold"
SEED_RMP_PATH = EVAL_GOLD_DIR / "seed_rmp.html"
DEFAULT_DELTA_DIR = EVAL_GOLD_DIR / "deltas"
INCREMENTAL_SOURCE_DIR = EVAL_GOLD_DIR / "incremental_source"
DEFAULT_MODELS = ["phi3", "llama3.2:3b", "gemma2:2b"]
DEFAULT_REPORT_TYPES = ["rmp"]
DEFAULT_JOB_TIMEOUT_S = 300  # 5 min wall-clock per trial (prevents 20+ min outlier jobs)
BENCHMARK_LLM_INVOKE_TIMEOUT_S = 180  # overridden per run from --timeout via per_invoke_timeout_s()
BENCHMARK_JOB_OVERHEAD_S = 90.0  # retrieval, parse, harness poll, cleanup within one trial
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
    "incremental_only",
    "update_intent",
    "job_status",
    "error_message",
]
ACCURACY_FIELDS = [
    "model",
    "trial",
    "report_type",
    "job_id",
    "edit_id",
    "grounding_score",
    "hallucination",
    "checklist_items_addressed",
    "judge_model",
    "judge_error",
    "rationale",
]
ACCURACY_SUMMARY_FIELDS = [
    "model",
    "trial",
    "report_type",
    "job_id",
    "mean_grounding_score",
    "grounded_edit_rate",
    "checklist_recall",
    "hallucination_rate",
    "judge_model",
    "edit_count",
]


def per_invoke_timeout_s(job_timeout_s: float, *, allow_structured_retry: bool = False) -> float:
    """
    Max seconds for one Ollama generate so a trial can finish within --timeout.

    Benchmark mode disables structured retry in server.py, so one invoke gets the full budget.
    """
    budget = max(60.0, float(job_timeout_s) - BENCHMARK_JOB_OVERHEAD_S)
    if allow_structured_retry:
        budget = max(60.0, budget / 2.0)
    return budget


def ollama_unload_model(model: str) -> None:
    """Drop a loaded model from VRAM (keep_alive=0) to avoid queue saturation between trials."""
    import json
    import urllib.error
    import urllib.request

    base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    body = json.dumps({"model": model, "prompt": "", "keep_alive": 0}).encode("utf-8")
    req = urllib.request.Request(
        f"{base}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
        print(f"  ollama unload requested for {model}")
    except (urllib.error.URLError, TimeoutError, OSError) as ex:
        print(f"  warning: ollama unload {model}: {ex}")


def ollama_loaded_models() -> list[str]:
    try:
        out = subprocess.check_output(["ollama", "ps"], text=True, timeout=30)
    except (subprocess.SubprocessError, OSError, FileNotFoundError):
        return []
    names: list[str] = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if parts:
            names.append(parts[0])
    return names


def drain_ollama_between_trials(model: str, *, when: str) -> None:
    """
    Ensure no loaded model / queued work carries into the next benchmark trial.
    Critical for llama: timed-out invokes leave orphan Ollama work on the GPU.
    """
    ollama_unload_model(model)
    time.sleep(2)
    still = ollama_loaded_models()
    if still:
        print(f"  warning: after drain ({when}) ollama still has: {', '.join(still)}")
        ollama_unload_model(model)
        time.sleep(1)


def configure_benchmark_dir(experiment_id: str | None) -> None:
    global BENCHMARK_DIR, RESULTS_CSV, META_JSON, ACCURACY_CSV, ACCURACY_SUMMARY_CSV
    if experiment_id:
        BENCHMARK_DIR = PROJECT_ROOT / "output" / "benchmark" / experiment_id
    else:
        BENCHMARK_DIR = PROJECT_ROOT / "output" / "benchmark"
    RESULTS_CSV = BENCHMARK_DIR / "results.csv"
    META_JSON = BENCHMARK_DIR / "run_meta.json"
    ACCURACY_CSV = BENCHMARK_DIR / "accuracy.csv"
    ACCURACY_SUMMARY_CSV = BENCHMARK_DIR / "accuracy_summary.csv"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_benchmark_dir() -> None:
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            out = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"if (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{ 'yes' }}",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return (out.stdout or "").strip().lower() == "yes"
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _release_benchmark_lock() -> None:
    global _BENCHMARK_LOCK_PATH
    if not _BENCHMARK_LOCK_PATH or not _BENCHMARK_LOCK_PATH.is_file():
        return
    try:
        if int(_BENCHMARK_LOCK_PATH.read_text(encoding="utf-8").strip()) == os.getpid():
            _BENCHMARK_LOCK_PATH.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def acquire_benchmark_lock(lock_path: Path) -> None:
    """Ensure only one benchmark harness process runs per output directory."""
    global _BENCHMARK_LOCK_PATH
    _BENCHMARK_LOCK_PATH = lock_path
    atexit.register(_release_benchmark_lock)
    ensure_benchmark_dir()
    me = os.getpid()
    if lock_path.is_file():
        try:
            old_pid = int(lock_path.read_text(encoding="utf-8").strip())
        except ValueError:
            old_pid = -1
        if old_pid > 0 and old_pid != me and _process_alive(old_pid):
            raise SystemExit(
                f"Another benchmark is already running (PID {old_pid}). "
                f"Stop it or remove stale lock only if that process is gone: {lock_path}"
            )
        if old_pid > 0 and not _process_alive(old_pid):
            print(f"Removing stale benchmark.lock (dead PID {old_pid})")
    lock_path.write_text(str(me), encoding="utf-8")


def cleanup_benchmark_mission(mission_id: str) -> int:
    """Cancel queued/running pipeline jobs and clear in-process mission lock."""
    import server
    from src.pipeline_job_service import fail_stale_running_jobs

    n = fail_stale_running_jobs(mission_id, "benchmark cleanup: stale or superseded job")
    with server.app.state.stream_lock:
        if server.app.state.running_mission_id == mission_id:
            server.app.state.running_mission_id = None
    if n:
        print(f"  cleanup: cancelled {n} stale pipeline job(s) for {mission_id}")
    return n


def wait_for_pipeline_idle(mission_id: str, max_wait_s: float = 120.0) -> bool:
    """Wait until no in-flight pipeline holds running_mission_id for this mission."""
    import server

    deadline = time.monotonic() + max_wait_s
    while time.monotonic() < deadline:
        with server.app.state.stream_lock:
            mid = server.app.state.running_mission_id
        db_running = count_running_pipeline_jobs(mission_id)
        if (mid is None or mid != mission_id) and db_running == 0:
            return True
        time.sleep(1)
    cleanup_benchmark_mission(mission_id)
    with server.app.state.stream_lock:
        if server.app.state.running_mission_id == mission_id:
            server.app.state.running_mission_id = None
            print(f"  warning: cleared stuck running_mission_id after {max_wait_s:.0f}s")
    return count_running_pipeline_jobs(mission_id) == 0


def benchmark_abort_job(mission_id: str, job_id: str, reason: str) -> None:
    """On harness timeout: cancel DB job so pipeline threads stop doing fallback work."""
    import server
    from src.pipeline_job_service import cancel_pipeline_job

    cancel_pipeline_job(job_id, reason[:4000])
    with server.app.state.stream_lock:
        if server.app.state.running_mission_id == mission_id:
            server.app.state.running_mission_id = None
    wait_for_pipeline_idle(mission_id, max_wait_s=30.0)


def count_running_pipeline_jobs(mission_id: str) -> int:
    from src.db.models import get_connection

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) FROM pipeline_jobs
            WHERE mission_id = ? AND status IN ('queued', 'running')
            """,
            (mission_id,),
        ).fetchone()
    return int(row[0]) if row else 0


def preflight_benchmark_clean(mission_id: str, experiment_id: str | None) -> None:
    """Drain stale jobs before trials (single-runner enforced via benchmark.lock)."""
    cleanup_benchmark_mission(mission_id)
    wait_for_pipeline_idle(mission_id, max_wait_s=120.0)
    remaining = count_running_pipeline_jobs(mission_id)
    if remaining:
        cleanup_benchmark_mission(mission_id)
        wait_for_pipeline_idle(mission_id, max_wait_s=60.0)
        remaining = count_running_pipeline_jobs(mission_id)
    if remaining:
        raise SystemExit(
            f"Mission {mission_id} still has {remaining} queued/running pipeline job(s) after cleanup. "
            "Restart Ollama or run: python -c \"from src.pipeline_job_service import fail_stale_running_jobs; "
            f"fail_stale_running_jobs('{mission_id}', 'manual')\""
        )
    print(f"Preflight OK: no stale jobs for {mission_id} (benchmark_mode=on, fallback disabled in server)")


def cooldown_between_models(mission_id: str, model: str) -> None:
    print(f"\n--- Cooldown after {model} (cancel stale work, drain pipeline, unload VRAM) ---")
    cleanup_benchmark_mission(mission_id)
    wait_for_pipeline_idle(mission_id, max_wait_s=300.0)
    ollama_unload_model(model)
    time.sleep(3)


def archive_benchmark_results() -> Path | None:
    """Move existing benchmark artifacts to archived/<timestamp>/ before a fresh run."""
    markers = (
        RESULTS_CSV,
        ACCURACY_CSV,
        ACCURACY_SUMMARY_CSV,
        BENCHMARK_DIR / "summary_table.csv",
        BENCHMARK_DIR / "accuracy_summary_table.csv",
    )
    extras = list(BENCHMARK_DIR.glob("fig*.png")) + list(BENCHMARK_DIR.glob("fig*.pdf"))
    extras += list(BENCHMARK_DIR.glob("fig_paper_*"))
    if not any(p.is_file() for p in (*markers, *extras)):
        return None
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = BENCHMARK_DIR / "archived" / ts
    dest.mkdir(parents=True, exist_ok=True)
    for p in (*markers, *extras):
        if p.is_file():
            shutil.move(str(p), str(dest / p.name))
    print(f"Archived prior benchmark artifacts to {dest}")
    return dest


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


def init_server_state(*, invoke_timeout_s: float | None = None) -> None:
    import asyncio
    import threading

    import config.settings as settings
    import server

    cap = float(invoke_timeout_s if invoke_timeout_s is not None else BENCHMARK_LLM_INVOKE_TIMEOUT_S)
    os.environ["BENCHMARK_MODE"] = "1"
    os.environ["OLLAMA_GENERATE_TIMEOUT_S"] = str(cap)
    settings.OLLAMA_GENERATE_TIMEOUT_S = cap

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


def sync_incremental_source() -> Path:
    """Copy baseline sample_mission files into incremental_source (no delta files)."""
    sample = (PROJECT_ROOT / "data" / "missions" / "sample_mission").resolve()
    if not sample.is_dir():
        raise SystemExit(f"Sample mission not found: {sample}")
    INCREMENTAL_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    for p in sample.iterdir():
        if p.is_file():
            shutil.copy2(p, INCREMENTAL_SOURCE_DIR / p.name)
    for p in INCREMENTAL_SOURCE_DIR.glob("findings_delta_*.txt"):
        p.unlink()
    for p in INCREMENTAL_SOURCE_DIR.glob("trial_*.txt"):
        p.unlink()
    return INCREMENTAL_SOURCE_DIR


def _force_rebuild_index(mission_id: str, source: Path) -> None:
    from config.settings import INDEX_DIR
    from src.index.build import build_mission_index

    index_path = INDEX_DIR / mission_id
    if index_path.is_dir():
        shutil.rmtree(index_path, ignore_errors=True)
    print(f"Building index for {mission_id} from {source} ...")
    build_mission_index(mission_id, source)
    print("Index build complete.")


def _set_report_current_content(mission_id: str, report_type: str, html: str) -> None:
    from src.db.models import get_connection, init_db

    init_db()
    now = _utc_now()
    with get_connection() as conn:
        conn.execute(
            """UPDATE reports SET current_content = ?, current_updated_at = ?,
               pending_content = NULL, pending_at = NULL, pending_sources = NULL
               WHERE mission_id = ? AND report_type = ?""",
            (html, now, mission_id, report_type),
        )


def setup_incremental_mission(
    mission_id: str = INCREMENTAL_MISSION_ID,
    *,
    seed_path: Path | None = None,
) -> str:
    """Experiment 3: seeded partial RMP + manifest baseline for update_from_evidence."""
    from config.settings import OUTPUT_DIR
    from src.ingest.manifest import read_manifest
    from src.mission_service import create_mission, get_mission
    from src.report_service import clear_report_docs_used, reject_all_edits, set_report_docs_used

    seed_file = (seed_path or SEED_RMP_PATH).resolve()
    if not seed_file.is_file():
        raise SystemExit(f"Seed RMP not found: {seed_file}")

    source = sync_incremental_source()
    mid = mission_id
    if not get_mission(mid):
        out = (OUTPUT_DIR / mid).resolve()
        out.mkdir(parents=True, exist_ok=True)
        mid = create_mission(
            INCREMENTAL_MISSION_NAME,
            str(source),
            str(out),
            mission_id=mission_id,
        )
        print(f"Created mission: {mid}")
    else:
        print(f"Using existing mission: {mid}")

    _force_rebuild_index(mid, source)

    manifest_paths = [item["path"] for item in read_manifest(mid) if item.get("path")]
    if not manifest_paths:
        raise SystemExit(f"No manifest paths for mission {mid}")

    seed_html = seed_file.read_text(encoding="utf-8")
    for rt in DEFAULT_REPORT_TYPES:
        try:
            reject_all_edits(mid, rt)
        except Exception as ex:
            print(f"warning: reject_all_edits({rt}): {ex}")
        _set_report_current_content(mid, rt, seed_html if rt == "rmp" else "")
        set_report_docs_used(mid, rt, list(manifest_paths))
        print(f"Seeded {rt}: {len(seed_html)} chars, baseline docs={len(manifest_paths)}")

    (BENCHMARK_DIR / "mission_id.txt").write_text(mid, encoding="utf-8")
    return mid


def inject_trial_delta(source_dir: Path, delta_dir: Path, trial: int) -> Path | None:
    """Copy one trial delta into the mission source so manifest diff sees a new file."""
    for name in (f"trial_{trial:02d}.txt", f"findings_delta_{trial:02d}.txt"):
        src = delta_dir / name
        if src.is_file():
            dest = source_dir / f"findings_delta_{trial:02d}.txt"
            shutil.copy2(src, dest)
            return dest
    print(f"    warning: no delta file for trial {trial} in {delta_dir}")
    return None


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
        "fallback_used": False,
        "incremental_only": False,
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
            if detail.get("incremental_only") is not None:
                metrics["incremental_only"] = bool(detail.get("incremental_only"))
        elif step == "generation_done" and detail.get("phase") == "structured_edits":
            metrics["generation_ms"] = detail.get("ms")
        elif step == "parse_validate_done":
            metrics["parse_validate_ms"] = detail.get("ms")
            metrics["accepted_edit_count"] = detail.get("accepted_edit_count")
            metrics["parse_failed"] = bool(detail.get("parse_failed"))
        elif step == "structured_edits_fallback":
            rt = detail.get("report_type")
            if not rt or rt == report_type:
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
        remaining = deadline - time.monotonic()
        time.sleep(0.5 if remaining < 30 else 2)
    raise TimeoutError(f"Job {job_id} did not finish within {timeout_s}s")


def prepare_trial(mission_id: str, report_type: str) -> None:
    """Clear pending edits and wait for any in-flight pipeline before starting a trial."""
    from src.report_service import reject_all_edits

    cleanup_benchmark_mission(mission_id)
    wait_for_pipeline_idle(mission_id, max_wait_s=180.0)

    try:
        reject_all_edits(mission_id, report_type)
    except Exception as ex:
        print(f"    warning: pre-trial reject_all_edits: {ex}")


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
            "incremental_only": False,
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
        "incremental_only": m["incremental_only"],
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
    skip_judge: bool = False,
    judge_model: str | None = None,
    update_intent: str = "full_refresh",
) -> dict[str, Any]:
    import server
    from benchmark_judge import score_trial_edits
    from src.pipeline_job_service import get_pipeline_job
    from src.report_service import get_pending_edits, reject_all_edits

    prepare_trial(mission_id, report_type)
    drain_ollama_between_trials(model, when="pre-trial")
    set_active_model(model)
    print(f"  Trial {trial}: model={model} report={report_type} ...")

    t0 = time.monotonic()
    ok, err, job_id = server.request_mission_update(
        mission_id,
        report_types=[report_type],
        update_intent=update_intent,
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
            "incremental_only": False,
            "update_intent": update_intent,
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
        benchmark_abort_job(mission_id, job_id, timeout_err)
        wait_for_pipeline_idle(mission_id, max_wait_s=120.0)
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
    row["update_intent"] = update_intent
    print(
        f"    done status={row['job_status']} gen_ms={row['generation_ms']} "
        f"incr={row.get('incremental_only')} edits={row['accepted_edit_count']} "
        f"success={row['structured_success']}"
    )

    if not skip_judge and job_id:
        edits = get_pending_edits(mission_id, report_type)
        edit_rows, acc_summary = score_trial_edits(
            mission_id, model, edits, judge_model=judge_model
        )
        append_accuracy(mission_id, model, report_type, trial, job_id, edit_rows, acc_summary)
        print(
            f"    judge mean_grounding={acc_summary.get('mean_grounding_score')} "
            f"hallucination_rate={acc_summary.get('hallucination_rate')}"
        )

    try:
        reject_all_edits(mission_id, report_type)
    except Exception as ex:
        print(f"    warning: reject_all_edits: {ex}")

    wait_for_pipeline_idle(mission_id, max_wait_s=120.0)
    drain_ollama_between_trials(model, when="post-trial")

    return row


def load_completed_keys() -> set[tuple[str, int, str]]:
    """Triples already present in results.csv (for --resume)."""
    if not RESULTS_CSV.is_file():
        return set()
    done: set[tuple[str, int, str]] = set()
    with RESULTS_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                done.add((row["model"], int(row["trial"]), row["report_type"]))
            except (KeyError, ValueError, TypeError):
                continue
    return done


def append_results(rows: list[dict[str, Any]]) -> None:
    ensure_benchmark_dir()
    write_header = not RESULTS_CSV.is_file()
    with RESULTS_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def append_accuracy(
    mission_id: str,
    model: str,
    report_type: str,
    trial: int,
    job_id: str,
    edit_rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    ensure_benchmark_dir()
    write_header = not ACCURACY_CSV.is_file()
    with ACCURACY_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ACCURACY_FIELDS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        for er in edit_rows:
            w.writerow(
                {
                    "model": model,
                    "trial": trial,
                    "report_type": report_type,
                    "job_id": job_id,
                    "edit_id": er.get("edit_id"),
                    "grounding_score": er.get("grounding_score"),
                    "hallucination": er.get("hallucination"),
                    "checklist_items_addressed": er.get("checklist_items_addressed"),
                    "judge_model": summary.get("judge_model"),
                    "judge_error": er.get("judge_error"),
                    "rationale": er.get("rationale"),
                }
            )
    write_summary = not ACCURACY_SUMMARY_CSV.is_file()
    with ACCURACY_SUMMARY_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ACCURACY_SUMMARY_FIELDS, extrasaction="ignore")
        if write_summary:
            w.writeheader()
        w.writerow(
            {
                "model": model,
                "trial": trial,
                "report_type": report_type,
                "job_id": job_id,
                "mean_grounding_score": summary.get("mean_grounding_score"),
                "grounded_edit_rate": summary.get("grounded_edit_rate"),
                "checklist_recall": summary.get("checklist_recall"),
                "hallucination_rate": summary.get("hallucination_rate"),
                "judge_model": summary.get("judge_model"),
                "edit_count": summary.get("edit_count"),
            }
        )


def write_run_meta(
    models: list[str],
    mission_id: str,
    experiment_id: str | None = None,
    *,
    update_intent: str | None = None,
    seed_rmp: str | None = None,
) -> None:
    ensure_benchmark_dir()
    meta = {
        "created_at": _utc_now(),
        "mission_id": mission_id,
        "models": models,
        "report_types": DEFAULT_REPORT_TYPES,
        "ollama_list": ollama_list(),
        "experiment_id": experiment_id,
        "update_intent": update_intent,
        "seed_rmp": seed_rmp,
        "job_timeout_s": DEFAULT_JOB_TIMEOUT_S,
        "llm_invoke_timeout_s": BENCHMARK_LLM_INVOKE_TIMEOUT_S,
        "note": "RMP-only; structured_success = edits>0, no parse fail, no fallback; accuracy via local LLM judge; 5 min job / 3 min per-LLM caps",
    }
    META_JSON.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def run_benchmark(
    mission_id: str,
    models: list[str],
    report_types: list[str],
    trials: int,
    fresh_results: bool = True,
    timeout_s: float = DEFAULT_JOB_TIMEOUT_S,
    skip_judge: bool = False,
    judge_model: str | None = None,
    experiment_id: str | None = None,
    update_intent: str = "full_refresh",
    delta_dir: str | Path | None = None,
    resume: bool = False,
    invoke_timeout_s: float | None = None,
) -> None:
    global BENCHMARK_LLM_INVOKE_TIMEOUT_S
    if invoke_timeout_s is not None:
        BENCHMARK_LLM_INVOKE_TIMEOUT_S = float(invoke_timeout_s)
    init_server_state(invoke_timeout_s=BENCHMARK_LLM_INVOKE_TIMEOUT_S)
    print(
        f"Benchmark caps: job_timeout={timeout_s:.0f}s "
        f"per_invoke={BENCHMARK_LLM_INVOKE_TIMEOUT_S:.0f}s (structured retry off)"
    )
    from src.mission_service import get_mission

    source_path: Path | None = None
    delta_path: Path | None = Path(delta_dir).resolve() if delta_dir else None
    if delta_path:
        mission_row = get_mission(mission_id)
        if mission_row and mission_row.get("source_path"):
            source_path = Path(mission_row["source_path"]).resolve()
        else:
            raise SystemExit(f"Mission {mission_id} has no source_path for delta injection")
    lock_path = BENCHMARK_DIR / "benchmark.lock"
    acquire_benchmark_lock(lock_path)
    preflight_benchmark_clean(mission_id, experiment_id)
    time.sleep(1)

    if resume:
        fresh_results = False
    if fresh_results:
        archive_benchmark_results()
        for p in (RESULTS_CSV, ACCURACY_CSV, ACCURACY_SUMMARY_CSV):
            if p.is_file():
                p.unlink()
    completed = load_completed_keys() if resume else set()
    if resume and completed:
        print(f"Resume mode: skipping {len(completed)} completed trial(s) already in {RESULTS_CSV.name}")
    all_rows: list[dict[str, Any]] = []
    for model in models:
        print(f"\n=== Model batch: {model} ===")
        for trial in range(1, trials + 1):
            if source_path and delta_path:
                injected = inject_trial_delta(source_path, delta_path, trial)
                if injected:
                    print(f"  Injected delta: {injected.name}")
            for rt in report_types:
                if (model, trial, rt) in completed:
                    print(f"  Trial {trial}: skip model={model} report={rt} (already recorded)")
                    continue
                row = run_trial(
                    mission_id,
                    model,
                    rt,
                    trial,
                    timeout_s=timeout_s,
                    skip_judge=skip_judge,
                    judge_model=judge_model,
                    update_intent=update_intent,
                )
                all_rows.append(row)
                append_results([row])
        cooldown_between_models(mission_id, model)
    write_run_meta(
        models,
        mission_id,
        experiment_id=experiment_id,
        update_intent=update_intent,
        seed_rmp=str(SEED_RMP_PATH) if update_intent == "update_from_evidence" else None,
    )
    print(f"\nWrote {len(all_rows)} rows to {RESULTS_CSV}")
    _release_benchmark_lock()


def _csv_bool_series(series: Any) -> Any:
    """Coerce CSV True/False strings to booleans for plotting."""
    return series.map(lambda v: str(v).strip().lower() in ("true", "1", "yes"))


def _plot_generation_latency_figure(
    df: Any,
    models: list[str],
    out_dir: Path,
    *,
    success_only: bool,
    output_stem: str,
    dpi: int = 300,
    write_caption: bool = False,
) -> None:
    """
    Single-panel structured-edit generation latency (paper styling).
    Retrieval/parse overhead: see fig4_phase_breakdown_log.png.
    """
    import numpy as np
    import matplotlib.pyplot as plt

    bar_colors = ["#4C72B0", "#55A868", "#C44E52", "#8172B2"]
    if success_only:
        df_gen = df[_csv_bool_series(df["structured_success"])].copy()
        subtitle = "success trials only"
    else:
        df_gen = df
        subtitle = "all trials"

    trial_counts = df.groupby("model")["trial"].nunique().reindex(models)
    n_trials = int(trial_counts.min()) if not trial_counts.empty else 0

    means_s: list[float] = []
    err_lo: list[float] = []
    err_hi: list[float] = []
    n_labels: list[int] = []
    for model in models:
        sub = df_gen.loc[df_gen["model"] == model, "generation_ms"].dropna() / 1000.0
        n_labels.append(len(sub))
        if len(sub) == 0:
            means_s.append(0.0)
            err_lo.append(0.0)
            err_hi.append(0.0)
        else:
            m = float(sub.mean())
            means_s.append(m)
            err_lo.append(m - float(sub.min()))
            err_hi.append(float(sub.max()) - m)

    with plt.rc_context(
        {
            "font.size": 11,
            "axes.labelsize": 12,
            "axes.titlesize": 12,
            "legend.fontsize": 10,
        }
    ):
        fig, ax = plt.subplots(figsize=(8.5, 4.2))
        x = np.arange(len(models))
        bar_kw: dict[str, Any] = {
            "color": bar_colors[: len(models)],
            "edgecolor": "black",
            "linewidth": 0.6,
        }
        if any(n > 0 for n in n_labels):
            yerr = np.array([err_lo, err_hi])
            bar_kw["yerr"] = yerr
            bar_kw["capsize"] = 4
            bar_kw["error_kw"] = {"elinewidth": 1.0, "capthick": 1.0}
        ax.bar(x, means_s, **bar_kw)
        ax.set_ylabel("Mean time (s)")
        ax.set_title(f"Structured edit generation ({subtitle})")
        ax.set_xticks(x)
        ax.set_xticklabels(
            [f"{m}\n(n={n})" for m, n in zip(models, n_labels)],
            rotation=0,
            ha="center",
        )
        ax.set_ylim(bottom=0)

        fig.suptitle(
            f"RMP pipeline phase latency by local LLM ({n_trials} trials per model)",
            fontsize=13,
            y=1.02,
        )
        fig.tight_layout()
        fig.subplots_adjust(bottom=0.22)
        base = out_dir / output_stem
        fig.savefig(f"{base}.png", dpi=dpi, bbox_inches="tight")
        fig.savefig(f"{base}.pdf", bbox_inches="tight")
        plt.close(fig)

    if write_caption:
        n_note = ", ".join(f"{m}: n={n}" for m, n in zip(models, n_labels))
        if success_only:
            caption = (
                f"Figure X. RMP structured edit generation latency on identical mission documents "
                f"and hardware ({n_trials} trials per model). Mean generation time in seconds among "
                f"trials with valid structured output (no parse failure, no full-draft fallback); "
                f"whiskers show min–max within that subset ({n_note}). "
                f"Retrieval and parse/validate overhead: see phase breakdown figure (log scale). "
                f"Models: phi3, llama3.2:3b, and gemma2:2b via Ollama."
            )
        else:
            caption = (
                f"Figure X. RMP structured edit generation latency on identical mission documents "
                f"and hardware ({n_trials} trials per model). Mean generation time in seconds "
                f"across all trials (including timeouts and zero-edit completions); whiskers show "
                f"min–max ({n_note}). Retrieval and parse/validate overhead: see phase breakdown "
                f"figure (log scale). Models: phi3, llama3.2:3b, and gemma2:2b via Ollama."
            )
        (out_dir / f"{output_stem}_caption.txt").write_text(caption, encoding="utf-8")


def _plot_publication_phase_figure(df: Any, models: list[str], out_dir: Path) -> None:
    """Paper figure: structured-edit generation latency (success trials only)."""
    _plot_generation_latency_figure(
        df,
        models,
        out_dir,
        success_only=True,
        output_stem="fig_paper_pipeline_phases",
        dpi=300,
        write_caption=True,
    )


def _plot_paper_reliability_figure(df: Any, models: list[str], out_dir: Path) -> None:
    """Paper figure: structured success rate and fallback rate (n = all trials per model)."""
    import numpy as np
    import matplotlib.pyplot as plt

    bar_colors = ["#4C72B0", "#55A868", "#C44E52", "#8172B2"]
    success_pct = (
        df.groupby("model")["structured_success"]
        .apply(lambda s: _csv_bool_series(s).mean() * 100)
        .reindex(models)
        .fillna(0)
    )
    fallback_pct = (
        df.groupby("model")["fallback_used"]
        .apply(lambda s: _csv_bool_series(s).mean() * 100)
        .reindex(models)
        .fillna(0)
    )
    n_trials = int(df.groupby("model")["trial"].nunique().min())

    with plt.rc_context(
        {
            "font.size": 11,
            "axes.labelsize": 12,
            "axes.titlesize": 12,
            "legend.fontsize": 10,
        }
    ):
        fig, ax = plt.subplots(figsize=(8.5, 4.5))
        x = np.arange(len(models))
        w = 0.36
        ax.bar(
            x - w / 2,
            success_pct,
            w,
            label="Structured success",
            color="#66C2A5",
            edgecolor="black",
            linewidth=0.6,
        )
        ax.bar(
            x + w / 2,
            fallback_pct,
            w,
            label="Fallback (full-draft RAG)",
            color="#FC8D62",
            edgecolor="black",
            linewidth=0.6,
        )
        ax.set_ylim(0, 100)
        ax.set_ylabel("Rate (%)")
        ax.set_title("Structured edit reliability by local LLM")
        ax.set_xticks(x)
        ax.set_xticklabels(models, rotation=20, ha="right")
        ax.legend(loc="upper right", frameon=True)
        fig.suptitle(
            f"RMP structured edit outcomes (n = {n_trials} trials per model)",
            fontsize=13,
            y=1.02,
        )
        fig.tight_layout()
        base = out_dir / "fig_paper_structured_reliability"
        fig.savefig(f"{base}.png", dpi=300, bbox_inches="tight")
        fig.savefig(f"{base}.pdf", bbox_inches="tight")
        plt.close(fig)

    caption = (
        f"Figure Y. Structured edit reliability on identical RMP update jobs "
        f"(n = {n_trials} trials per model). Structured success: at least one accepted "
        f"block edit with no JSON parse failure and no full-draft fallback. Fallback: "
        f"pipeline invoked full-template RAG after zero valid structured edits. "
        f"Models: phi3, llama3.2:3b, and gemma2:2b via Ollama."
    )
    (out_dir / "fig_paper_structured_reliability_caption.txt").write_text(
        caption, encoding="utf-8"
    )


def _plot_success_tradeoff_figure(df: Any, models: list[str], out_dir: Path) -> None:
    """Paper figure: success rate vs mean structured-edit time (success trials only)."""
    import matplotlib.pyplot as plt

    marker_colors = ["#4C72B0", "#55A868", "#C44E52", "#8172B2"]
    xs: list[float] = []
    ys: list[float] = []
    colors: list[str] = []
    for i, model in enumerate(models):
        sub = df.loc[df["model"] == model]
        if sub.empty:
            continue
        ok = sub[_csv_bool_series(sub["structured_success"])]
        xs.append(_csv_bool_series(sub["structured_success"]).mean() * 100.0)
        if ok.empty or ok["generation_ms"].dropna().empty:
            ys.append(0.0)
        else:
            ys.append(float(ok["generation_ms"].mean() / 1000.0))
        colors.append(marker_colors[i % len(marker_colors)])

    n_trials = int(df.groupby("model")["trial"].nunique().min())
    y_max = max(100.0, max(ys, default=0) * 1.08)

    def _save_tradeoff(*, point_colors: list[str] | str, output_stem: str) -> None:
        with plt.rc_context(
            {
                "font.size": 11,
                "axes.labelsize": 12,
                "axes.titlesize": 12,
            }
        ):
            fig, ax = plt.subplots(figsize=(7.5, 5.5))
            ax.scatter(
                xs,
                ys,
                s=120,
                c=point_colors,
                edgecolors="black",
                linewidths=0.8,
                zorder=3,
            )
            ax.set_xlim(0, 105)
            ax.set_ylim(0, y_max)
            ax.set_xlabel("Structured success rate (%)")
            ax.set_ylabel("Avg. structured-edit time (seconds)")
            ax.grid(True, linestyle="--", linewidth=0.5, alpha=0.45)
            ax.set_axisbelow(True)
            fig.tight_layout()
            base = out_dir / output_stem
            fig.savefig(f"{base}.png", dpi=300, bbox_inches="tight")
            fig.savefig(f"{base}.pdf", bbox_inches="tight")
            plt.close(fig)

    _save_tradeoff(point_colors=colors, output_stem="fig_success_tradeoff")
    _save_tradeoff(point_colors="black", output_stem="fig_success_tradeoff_bw")

    caption = (
        f"Figure Z. Structured-edit reliability vs latency trade-off on identical RMP update jobs "
        f"(n = {n_trials} trials per model). Each point is one local Ollama model. "
        f"x-axis: structured success rate across all trials. y-axis: mean structured-edit "
        f"generation time among successful trials only. Models (left to right on x-axis): "
        f"llama3.2:3b (7%, n = 7 successes), phi3 (44%), gemma2:2b (100%)."
    )
    (out_dir / "fig_success_tradeoff_caption.txt").write_text(caption, encoding="utf-8")


def plot_results(out_dir: Path | None = None) -> Path:
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
    fig_dir = (out_dir or BENCHMARK_DIR).resolve()
    fig_dir.mkdir(parents=True, exist_ok=True)
    models = list(df["model"].unique())
    colors = ["#4C72B0", "#55A868", "#C44E52", "#8172B2", "#CCB974"]

    fig1, ax1 = plt.subplots(figsize=(8, 5))
    gen = df.groupby("model")["generation_ms"].agg(["mean", "std"]).reindex(models)
    n_trials_fig = int(df.groupby("model")["trial"].nunique().min())
    x = range(len(models))
    means_s = gen["mean"].fillna(0) / 1000.0
    stds_s = gen["std"].fillna(0) / 1000.0
    if n_trials_fig >= 5:
        ax1.bar(x, means_s, yerr=stds_s, capsize=5, color=colors[: len(models)])
    else:
        ax1.bar(x, means_s, color=colors[: len(models)])
    ax1.axhline(120, color="gray", linestyle="--", linewidth=1, label="120s reference")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(models, rotation=15, ha="right")
    ax1.set_ylabel("LLM generation time (seconds)")
    ax1.set_title("Structured edit generation latency by model")
    ax1.legend()
    fig1.tight_layout()
    fig1.savefig(fig_dir / "fig1_generation_latency.png", dpi=150)
    plt.close(fig1)

    import numpy as np

    fig2, ax2 = plt.subplots(figsize=(8, 5))
    x2 = np.arange(len(models))
    w2 = 0.36
    success_rate = (
        df.groupby("model")["structured_success"]
        .apply(lambda s: _csv_bool_series(s).mean() * 100)
        .reindex(models)
        .fillna(0)
    )
    fallback_rate = (
        df.groupby("model")["fallback_used"]
        .apply(lambda s: _csv_bool_series(s).mean() * 100)
        .reindex(models)
        .fillna(0)
    )
    ax2.bar(x2 - w2 / 2, success_rate, w2, label="Structured success", color="#66C2A5")
    ax2.bar(x2 + w2 / 2, fallback_rate, w2, label="Fallback", color="#FC8D62")
    ax2.set_ylim(0, 100)
    ax2.set_xticks(x2)
    ax2.set_xticklabels(models, rotation=15, ha="right")
    ax2.set_ylabel("Rate (%)")
    ax2.set_title("Structured edit reliability by model")
    ax2.legend(loc="upper right")
    fig2.tight_layout()
    fig2.savefig(fig_dir / "fig2_structured_success_rate.png", dpi=150)
    plt.close(fig2)

    _plot_generation_latency_figure(
        df,
        models,
        fig_dir,
        success_only=False,
        output_stem="fig3_phase_breakdown",
        dpi=300,
        write_caption=True,
    )

    # Fig4: grouped bars + log y-axis so retrieval/parse are visible (all trials).
    log_floor_s = 1e-3  # 1 ms floor when a phase mean is 0 (log scale requires > 0)
    r_log = (df.groupby("model")["retrieval_ms"].mean().reindex(models).fillna(0) / 1000.0).clip(
        lower=log_floor_s
    )
    g_log = (df.groupby("model")["generation_ms"].mean().reindex(models).fillna(0) / 1000.0).clip(
        lower=log_floor_s
    )
    p_log = (df.groupby("model")["parse_validate_ms"].mean().reindex(models).fillna(0) / 1000.0).clip(
        lower=log_floor_s
    )
    fig4_log, ax4_log = plt.subplots(figsize=(9, 5))
    x = np.arange(len(models))
    bar_w = 0.25
    ax4_log.bar(x - bar_w, r_log, bar_w, label="Retrieval", color="#8DA0CB")
    ax4_log.bar(x, g_log, bar_w, label="Generation", color="#FC8D62")
    ax4_log.bar(x + bar_w, p_log, bar_w, label="Parse/validate", color="#66C2A5")
    ax4_log.set_yscale("log")
    ax4_log.set_xticks(x)
    ax4_log.set_xticklabels(models, rotation=0, ha="center")
    ax4_log.set_ylabel("Mean time (seconds, log scale)")
    ax4_log.set_title("Pipeline phase breakdown by model (log y-axis)")
    ax4_log.legend(loc="upper right")
    fig4_log.tight_layout()
    fig4_log.subplots_adjust(bottom=0.13)
    fig4_log.text(
        0.02,
        0.02,
        "Note: log-scaled y-axis; phase means of 0 s plotted at 1 ms.",
        transform=fig4_log.transFigure,
        ha="left",
        va="bottom",
        fontsize=9,
        color="gray",
    )
    fig4_log.savefig(
        fig_dir / "fig4_phase_breakdown_log.png",
        dpi=150,
        bbox_inches="tight",
        pad_inches=0.12,
    )
    plt.close(fig4_log)

    _plot_publication_phase_figure(df, models, fig_dir)
    _plot_paper_reliability_figure(df, models, fig_dir)
    _plot_success_tradeoff_figure(df, models, fig_dir)

    summary = df.groupby("model").agg(
        trials=("trial", "count"),
        mean_generation_s=("generation_ms", lambda s: round(s.mean() / 1000, 2) if s.notna().any() else None),
        mean_wall_clock_s=("wall_clock_s", "mean"),
        mean_accepted_edits=("accepted_edit_count", "mean"),
        structured_success_rate=("structured_success", "mean"),
        fallback_rate=("fallback_used", "mean"),
        parse_failure_rate=("parse_failed", "mean"),
    )
    summary.to_csv(fig_dir / "summary_table.csv")

    if ACCURACY_SUMMARY_CSV.is_file():
        adf = pd.read_csv(ACCURACY_SUMMARY_CSV)
        if not adf.empty and "mean_grounding_score" in adf.columns:
            fig4, ax4 = plt.subplots(figsize=(8, 5))
            gmean = adf.groupby("model")["mean_grounding_score"].mean().reindex(models)
            ax4.bar(range(len(models)), gmean.fillna(0), color=colors[: len(models)])
            ax4.set_ylim(0, 5)
            ax4.set_xticks(range(len(models)))
            ax4.set_xticklabels(models, rotation=15, ha="right")
            ax4.set_ylabel("Mean grounding score (1-5)")
            ax4.set_title("LLM judge: factual grounding by model")
            fig4.tight_layout()
            fig4.savefig(fig_dir / "fig4_mean_grounding_score.png", dpi=150)
            plt.close(fig4)

            fig5, ax5 = plt.subplots(figsize=(8, 5))
            hr = adf.groupby("model")["hallucination_rate"].mean().reindex(models).fillna(0) * 100
            ax5.bar(range(len(models)), hr, color=colors[: len(models)])
            ax5.set_ylim(0, 100)
            ax5.set_xticks(range(len(models)))
            ax5.set_xticklabels(models, rotation=15, ha="right")
            ax5.set_ylabel("Hallucination rate (%)")
            ax5.set_title("LLM judge: edits flagged as hallucination")
            fig5.tight_layout()
            fig5.savefig(fig_dir / "fig5_hallucination_rate.png", dpi=150)
            plt.close(fig5)

            acc_summary = adf.groupby("model").agg(
                mean_grounding=("mean_grounding_score", "mean"),
                grounded_edit_rate=("grounded_edit_rate", "mean"),
                checklist_recall=("checklist_recall", "mean"),
                hallucination_rate=("hallucination_rate", "mean"),
            )
            acc_summary.to_csv(fig_dir / "accuracy_summary_table.csv")

    print(f"Charts saved under {fig_dir} (results unchanged at {RESULTS_CSV})")
    return fig_dir


def main() -> None:
    p = argparse.ArgumentParser(description="LLM benchmark for mission RAG platform")
    p.add_argument("--setup", action="store_true", help="Pull models and create/index mission")
    p.add_argument(
        "--setup-incremental",
        action="store_true",
        help="Experiment 3: seed partial RMP + baseline last_used_doc_paths",
    )
    p.add_argument("--run", action="store_true", help="Run benchmark trials")
    p.add_argument("--plot", action="store_true", help="Generate charts from results.csv")
    p.add_argument("--mission-id", default=None)
    p.add_argument("--models", default=",".join(DEFAULT_MODELS))
    p.add_argument("--report-types", default=",".join(DEFAULT_REPORT_TYPES))
    p.add_argument("--trials", type=int, default=10)
    p.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_JOB_TIMEOUT_S,
        help="Seconds to wait for each pipeline job (default: 300 = 5 min)",
    )
    p.add_argument(
        "--experiment-id",
        default="experiment2",
        help="Subfolder under output/benchmark/ for results (default: experiment2)",
    )
    p.add_argument(
        "--figures-dir",
        default=None,
        help="Subfolder under experiment output for charts (default: experiment dir itself). "
        "Use e.g. figures to avoid overwriting prior chart exports.",
    )
    p.add_argument(
        "--judge-model",
        default="llama3.2:3b",
        help="Default local judge model (cross-model rule when subject matches)",
    )
    p.add_argument("--skip-judge", action="store_true", help="Skip LLM-as-judge accuracy scoring")
    p.add_argument(
        "--resume",
        action="store_true",
        help="Append only missing trials; never delete existing results.csv",
    )
    p.add_argument(
        "--update-intent",
        default="full_refresh",
        help="Pipeline update intent (experiment3: update_from_evidence)",
    )
    p.add_argument(
        "--delta-dir",
        default=None,
        help="Directory of trial_XX.txt files injected per trial (incremental experiment)",
    )
    p.add_argument(
        "--seed-rmp",
        default=None,
        help="Path to seeded partial RMP HTML (with --setup-incremental)",
    )
    args = p.parse_args()

    if not (args.setup or args.setup_incremental or args.run or args.plot):
        p.print_help()
        raise SystemExit(1)

    configure_benchmark_dir(args.experiment_id if args.experiment_id else None)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    report_types = [r.strip() for r in args.report_types.split(",") if r.strip()]
    ensure_benchmark_dir()

    if args.setup:
        ensure_models(models)
        mid = setup_mission(args.mission_id)
        write_run_meta(models, mid)
        print(f"Setup complete. mission_id={mid}")

    if args.setup_incremental:
        ensure_models(models)
        seed = Path(args.seed_rmp).resolve() if args.seed_rmp else SEED_RMP_PATH
        mid = args.mission_id or INCREMENTAL_MISSION_ID
        mid = setup_incremental_mission(mid, seed_path=seed)
        write_run_meta(
            models,
            mid,
            experiment_id=args.experiment_id,
            update_intent="update_from_evidence",
            seed_rmp=str(seed),
        )
        print(f"Incremental setup complete. mission_id={mid}")

    if args.run:
        global BENCHMARK_LLM_INVOKE_TIMEOUT_S
        BENCHMARK_LLM_INVOKE_TIMEOUT_S = per_invoke_timeout_s(float(args.timeout))
        mid = load_mission_id(args.mission_id)
        delta_dir = args.delta_dir or (
            str(DEFAULT_DELTA_DIR) if args.update_intent == "update_from_evidence" else None
        )
        run_benchmark(
            mid,
            models,
            report_types,
            args.trials,
            fresh_results=not args.resume,
            timeout_s=float(args.timeout),
            skip_judge=args.skip_judge,
            judge_model=args.judge_model,
            experiment_id=args.experiment_id,
            update_intent=args.update_intent,
            delta_dir=delta_dir,
            resume=args.resume,
            invoke_timeout_s=BENCHMARK_LLM_INVOKE_TIMEOUT_S,
        )

    if args.plot:
        fig_out = Path(args.figures_dir) if args.figures_dir else None
        if fig_out and not fig_out.is_absolute():
            fig_out = BENCHMARK_DIR / fig_out
        plot_results(out_dir=fig_out)


if __name__ == "__main__":
    main()
