"""
Phase 4 §10.1–10.2: snapshot mission source files when the user commits a report (save / accept / apply),
and expose a read-only delta for the UI (no auto-edit).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.db.models import get_connection, init_db
from src.ingest.manifest import new_or_changed_files, scan_source_files
from src.sections import sections_to_update


def save_mission_source_checkpoint(mission_id: str, source_path: Path) -> None:
    """Record current source tree (path, doc_type, mtime) on the mission row."""
    init_db()
    source_path = Path(source_path)
    if not source_path.is_dir():
        return
    files = scan_source_files(source_path)
    now = datetime.utcnow().isoformat() + "Z"
    payload = json.dumps(files, ensure_ascii=False)
    with get_connection() as conn:
        conn.execute(
            """UPDATE missions SET last_source_checkpoint_json = ?, last_source_checkpoint_at = ?, updated_at = ?
               WHERE LOWER(id) = LOWER(?)""",
            (payload, now, now, mission_id),
        )


def evidence_delta_for_mission(mission_id: str, source_path: Path) -> dict[str, Any]:
    """
    Compare current disk state to last checkpoint and to index manifest.
    Does not run the pipeline or modify reports.
    """
    init_db()
    source_path = Path(source_path)
    if not source_path.is_dir():
        return {
            "baseline": "invalid",
            "checkpoint_at": None,
            "message": "Source path is not a directory.",
            "new_files": 0,
            "changed_files": 0,
            "removed_files": 0,
            "sample_paths": [],
            "sections_likely_dirty": [],
            "since_index_new_changed": 0,
        }

    current = scan_source_files(source_path)
    cur_map = {x["path"]: x for x in current}
    since_index = new_or_changed_files(mission_id, source_path)
    sec_from_index = [
        {"report_type": rt, "section_key": sk} for rt, sk in sections_to_update(mission_id, since_index)
    ]

    with get_connection() as conn:
        row = conn.execute(
            "SELECT last_source_checkpoint_json, last_source_checkpoint_at FROM missions WHERE LOWER(id) = LOWER(?)",
            (mission_id,),
        ).fetchone()

    if not row or not row["last_source_checkpoint_json"]:
        return {
            "baseline": "none",
            "checkpoint_at": None,
            "message": "No baseline yet. Save edits or accept / apply suggestions on a report to record one.",
            "new_files": len(since_index),
            "changed_files": 0,
            "removed_files": 0,
            "sample_paths": [Path(x["path"]).name for x in since_index[:6]],
            "sections_likely_dirty": sec_from_index,
            "since_index_new_changed": len(since_index),
        }

    try:
        ck = json.loads(row["last_source_checkpoint_json"])
        if not isinstance(ck, list):
            ck = []
    except (json.JSONDecodeError, TypeError):
        ck = []
    ck_map = {x["path"]: x for x in ck if isinstance(x, dict) and x.get("path")}

    new_paths = [p for p in cur_map if p not in ck_map]
    changed_paths = [
        p for p in cur_map if p in ck_map and cur_map[p].get("mtime") != ck_map[p].get("mtime")
    ]
    removed_paths = [p for p in ck_map if p not in cur_map]

    dirty_items = [cur_map[p] for p in new_paths] + [cur_map[p] for p in changed_paths]
    sec_pairs = sections_to_update(mission_id, dirty_items)
    sections_checkpoint = [{"report_type": rt, "section_key": sk} for rt, sk in sec_pairs]

    sample = [Path(p).name for p in (new_paths + changed_paths)[:8]]

    return {
        "baseline": "checkpoint",
        "checkpoint_at": row["last_source_checkpoint_at"],
        "message": None,
        "new_files": len(new_paths),
        "changed_files": len(changed_paths),
        "removed_files": len(removed_paths),
        "sample_paths": sample,
        "sections_likely_dirty": sections_checkpoint,
        "since_index_new_changed": len(since_index),
    }
