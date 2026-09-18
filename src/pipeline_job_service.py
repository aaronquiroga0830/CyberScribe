"""Durable pipeline job records (Phase 0 migration): decouple status from SSE streams."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from src.db.models import get_connection

_lock = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


UPDATE_INTENT_LABELS: dict[str, str] = {
    "generate_first_draft": "Generate first draft from sources",
    "update_from_evidence": "Update from new or changed evidence",
    "full_refresh": "Full refresh (all sources)",
    "scoped_single_report": "Scoped: single report update",
    "scheduled_cycle": "Scheduled cycle (RMP + Timeline)",
}

ALLOWED_UPDATE_INTENTS = frozenset(UPDATE_INTENT_LABELS.keys())


def resolve_update_intent_for_job(
    report_types: list[str] | None, explicit: str | None = None
) -> str:
    if explicit and explicit in ALLOWED_UPDATE_INTENTS:
        return explicit
    if not report_types:
        return "full_refresh"
    if len(report_types) == 1:
        return "scoped_single_report"
    return "update_from_evidence"


def create_pipeline_job(
    mission_id: str,
    report_types: list[str] | None,
    *,
    job_kind: str | None = None,
    update_intent: str | None = None,
) -> str:
    job_id = str(uuid.uuid4())
    rt_json = json.dumps(report_types) if report_types else None
    kind = job_kind or ("pipeline_partial" if report_types else "pipeline_all")
    intent = resolve_update_intent_for_job(report_types, update_intent)
    scope_type = "mission"
    if report_types:
        scope_type = "report" if len(report_types) == 1 else "multi_report"
    job_type = kind
    now = _utc_now()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO pipeline_jobs (
                id, mission_id, report_types, job_kind, status, progress_json,
                created_at, update_intent, job_type, scope_type, retrieval_mode
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                mission_id,
                rt_json,
                kind,
                "queued",
                "[]",
                now,
                intent,
                job_type,
                scope_type,
                None,
            ),
        )
    return job_id


def intent_display_label(update_intent: str | None) -> str | None:
    if not update_intent:
        return None
    return UPDATE_INTENT_LABELS.get(update_intent, update_intent)


def mark_pipeline_job_running(job_id: str) -> None:
    now = _utc_now()
    with _lock:
        with get_connection() as conn:
            conn.execute(
                "UPDATE pipeline_jobs SET status = ?, started_at = ? WHERE id = ?",
                ("running", now, job_id),
            )


def append_pipeline_job_event(job_id: str, step: str, detail: dict[str, Any] | None = None) -> None:
    entry = {"t": _utc_now(), "step": step, "detail": detail or {}}
    with _lock:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT progress_json FROM pipeline_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if not row:
                return
            events = json.loads(row["progress_json"] or "[]")
            if not isinstance(events, list):
                events = []
            events.append(entry)
            conn.execute(
                "UPDATE pipeline_jobs SET progress_json = ? WHERE id = ?",
                (json.dumps(events), job_id),
            )


def mark_pipeline_job_fallback_used(job_id: str) -> None:
    with _lock:
        with get_connection() as conn:
            conn.execute(
                "UPDATE pipeline_jobs SET fallback_used = 1 WHERE id = ?", (job_id,)
            )


def complete_pipeline_job(job_id: str) -> None:
    now = _utc_now()
    with _lock:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE pipeline_jobs
                SET status = ?, finished_at = ?, error_message = NULL, failure_kind = NULL
                WHERE id = ?
                """,
                ("completed", now, job_id),
            )


def fail_pipeline_job(
    job_id: str, error_message: str, failure_kind: str | None = None
) -> None:
    now = _utc_now()
    with _lock:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE pipeline_jobs
                SET status = ?, finished_at = ?, error_message = ?, failure_kind = ?
                WHERE id = ?
                """,
                ("failed", now, error_message[:4000], failure_kind, job_id),
            )


def cancel_pipeline_job(job_id: str, reason: str) -> None:
    """Mark a job failed/cancelled (benchmark harness or operator abort)."""
    fail_pipeline_job(job_id, reason, failure_kind="cancelled")


def is_pipeline_job_cancelled(mission_id: str, job_id: str) -> bool:
    job = get_pipeline_job(mission_id, job_id)
    if not job:
        return True
    return job.get("status") == "failed" and job.get("failure_kind") == "cancelled"


def fail_stale_running_jobs(mission_id: str, reason: str) -> int:
    """Fail queued/running jobs for a mission (e.g. before benchmark resume)."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id FROM pipeline_jobs
            WHERE mission_id = ? AND status IN ('queued', 'running')
            """,
            (mission_id,),
        ).fetchall()
    n = 0
    for row in rows:
        cancel_pipeline_job(row[0], reason)
        n += 1
    return n


def add_pipeline_job_invalid_edits(job_id: str, count: int) -> None:
    if count <= 0:
        return
    with _lock:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE pipeline_jobs
                SET invalid_edit_count = COALESCE(invalid_edit_count, 0) + ?
                WHERE id = ?
                """,
                (count, job_id),
            )


def get_pipeline_job(mission_id: str, job_id: str) -> dict[str, Any] | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, mission_id, report_types, job_kind, status, progress_json,
                   error_message, failure_kind, fallback_used, invalid_edit_count,
                   update_intent, job_type, scope_type, retrieval_mode,
                   created_at, started_at, finished_at
            FROM pipeline_jobs WHERE id = ? AND mission_id = ?
            """,
            (job_id, mission_id),
        ).fetchone()
    if not row:
        return None
    return _row_to_dict(row)


def list_pipeline_jobs(mission_id: str, limit: int = 25) -> list[dict[str, Any]]:
    limit = max(1, min(100, limit))
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, mission_id, report_types, job_kind, status, progress_json,
                   error_message, failure_kind, fallback_used, invalid_edit_count,
                   update_intent, job_type, scope_type, retrieval_mode,
                   created_at, started_at, finished_at
            FROM pipeline_jobs
            WHERE mission_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (mission_id, limit),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def _row_to_dict(row: Any) -> dict[str, Any]:
    d = dict(row)
    if d.get("progress_json"):
        try:
            d["progress"] = json.loads(d["progress_json"])
        except json.JSONDecodeError:
            d["progress"] = []
    else:
        d["progress"] = []
    del d["progress_json"]
    ui = d.get("update_intent")
    d["intent_label"] = intent_display_label(ui) if isinstance(ui, str) else None
    if d.get("report_types"):
        try:
            d["report_types"] = json.loads(d["report_types"])
        except json.JSONDecodeError:
            pass
    return d
