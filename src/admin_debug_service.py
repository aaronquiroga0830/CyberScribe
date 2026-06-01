"""Read-only debug aggregates for admins / MEL."""
from __future__ import annotations

from typing import Any

from config.settings import INDEX_DIR
from src.db.models import get_connection, init_db
from src.ingest.manifest import read_manifest


def mission_debug_snapshot(mission_id: str) -> dict[str, Any]:
    init_db()
    manifest = read_manifest(mission_id)
    manifest_path = INDEX_DIR / mission_id / "manifest.json"
    job_row = None
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, status, error_message, failure_kind, created_at, finished_at, job_kind
            FROM pipeline_jobs
            WHERE mission_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (mission_id,),
        ).fetchone()
        if row:
            job_row = dict(row)
        n_pending = conn.execute(
            "SELECT COUNT(*) AS c FROM pending_edits WHERE mission_id = ?",
            (mission_id,),
        ).fetchone()["c"]
    return {
        "mission_id": mission_id,
        "last_pipeline_job": job_row,
        "pending_edits_count": int(n_pending),
        "manifest_entries": len(manifest),
        "manifest_path": str(manifest_path),
        "manifest_path_exists": manifest_path.is_file(),
    }


def global_debug_snapshot() -> dict[str, Any]:
    init_db()
    with get_connection() as conn:
        users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        missions = conn.execute("SELECT COUNT(*) AS c FROM missions").fetchone()["c"]
        jobs_running = conn.execute(
            "SELECT COUNT(*) AS c FROM pipeline_jobs WHERE status = 'running'"
        ).fetchone()["c"]
    idx_root = INDEX_DIR
    index_dirs = 0
    if idx_root.is_dir():
        index_dirs = sum(1 for p in idx_root.iterdir() if p.is_dir())
    return {
        "users_count": int(users),
        "missions_count": int(missions),
        "pipeline_jobs_running": int(jobs_running),
        "index_mission_dirs": index_dirs,
        "index_root": str(idx_root),
    }
