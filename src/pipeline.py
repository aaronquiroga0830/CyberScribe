"""
Long-running pipeline: for a mission, ingest from source_path and generate reports.
Saves AI output as pending for user review (accept/reject in UI).
Called by the scheduler daily over the mission lifecycle (e.g. 5 months).

Scheduler runs use the same `pipeline_jobs` records as HTTP-triggered updates (Phase 0).
"""
from pathlib import Path
import time

from src.mission_service import (
    get_mission,
    list_missions,
    update_mission_last_ingest,
    update_mission_last_generated,
)
from src.report_service import set_pending
from src.index.build import build_mission_index
from src.retrieve.retriever import get_mission_retriever
from src.agents.base import run_template_rag_agent
from config.settings import get_ollama_base_url_for_report
from src.templates.prompts import (
    RMP_TEMPLATE_QUERY,
    RMP_GENERATION_PROMPT,
)
from src.pipeline_job_service import (
    append_pipeline_job_event,
    complete_pipeline_job,
    create_pipeline_job,
    fail_pipeline_job,
    mark_pipeline_job_running,
)


def run_mission_cycle(mission_id: str, retriever_k: int = 8) -> dict[str, str] | None:
    """
    For one mission: rebuild index from source_path, run RMP agent,
    save result as pending. Updates last_ingest_at and last_generated_at.
    Returns dict of report_type -> content, or None if mission not found/inactive.
    """
    mission = get_mission(mission_id)
    if not mission or mission["status"] != "active":
        return None
    source_path = Path(mission["source_path"])
    if not source_path.is_dir():
        return None

    job_id = create_pipeline_job(
        mission_id,
        ["rmp"],
        job_kind="scheduler_cycle",
        update_intent="scheduled_cycle",
    )
    mark_pipeline_job_running(job_id)
    append_pipeline_job_event(
        job_id,
        "pipeline_started",
        {"run_types": ["rmp"], "source": "scheduler"},
    )

    try:
        append_pipeline_job_event(job_id, "index_build_start", {})
        t_idx = time.monotonic()
        build_mission_index(mission_id=mission_id, source_path=source_path)
        append_pipeline_job_event(
            job_id,
            "index_build_done",
            {"ms": round((time.monotonic() - t_idx) * 1000)},
        )
        update_mission_last_ingest(mission_id)

        retriever_rmp = get_mission_retriever(mission_id=mission_id, report_type="rmp")

        t0 = time.monotonic()
        content, sources = run_template_rag_agent(
            mission_id=mission_id,
            template_query=RMP_TEMPLATE_QUERY,
            generation_prompt_template=RMP_GENERATION_PROMPT,
            retriever=retriever_rmp,
            base_url=get_ollama_base_url_for_report("rmp"),
        )
        set_pending(mission_id, "rmp", content, sources=sources)
        append_pipeline_job_event(
            job_id,
            "report_completed",
            {
                "report_type": "rmp",
                "kind": "scheduler_pending",
                "ms": round((time.monotonic() - t0) * 1000),
            },
        )

        update_mission_last_generated(mission_id)
        append_pipeline_job_event(
            job_id, "pipeline_completed", {"run_types": ["rmp"]}
        )
        complete_pipeline_job(job_id)
        return {"rmp": content}
    except Exception as e:
        fail_pipeline_job(job_id, str(e), failure_kind="pipeline_error")
        raise


def run_all_active_missions(retriever_k: int = 8) -> dict[str, dict[str, str] | None]:
    """Run pipeline for every active mission. Returns {mission_id: results or None}."""
    missions = list_missions(active_only=True)
    out = {}
    for m in missions:
        mid = m["id"]
        try:
            out[mid] = run_mission_cycle(mid, retriever_k=retriever_k)
        except Exception:
            out[mid] = None  # caller can log e
    return out
