"""
Report state and review workflow: current (accepted/edited) vs pending (AI draft).
Accept → make pending the new current and write to mission output path.
Reject → discard pending. User can edit current and save (writes to output path).
Source traceability is shown during review only; final delivered document has no sources.
Output format: .docx (rich) with optional margins; HTML content is converted via html_to_docx.
"""
import json
import logging
import uuid
from pathlib import Path
from datetime import datetime
from typing import List, Optional

from src.db.models import get_connection, init_db, REPORT_TYPES
from src.revision_service import insert_report_revision
from src.html_to_docx import html_to_docx
from src.document_blocks import parse_html_to_blocks, blocks_to_html, apply_edits_to_blocks, apply_edits_to_blocks_for_preview
from src.templates.document_templates import get_document_template

logger = logging.getLogger(__name__)


def _touch_source_checkpoint(mission_id: str) -> None:
    """Phase 4: snapshot source tree after user commits content (save / accept / apply)."""
    try:
        from pathlib import Path

        from src.mission_service import get_mission
        from src.evidence_checkpoint import save_mission_source_checkpoint

        m = get_mission(mission_id)
        if not m:
            return
        sp = m.get("source_path")
        if not sp:
            return
        p = Path(sp)
        if p.is_dir():
            save_mission_source_checkpoint(mission_id, p)
    except Exception as e:
        logger.warning("source checkpoint skipped mission_id=%s: %s", mission_id, e)


def ensure_db() -> None:
    init_db()


def get_report(mission_id: str, report_type: str) -> dict:
    """Return current_content, pending_content, pending_at, pending_sources, current_updated_at."""
    ensure_db()
    if report_type not in REPORT_TYPES:
        raise ValueError(f"report_type must be one of {REPORT_TYPES}")
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT current_content, pending_content, pending_at, pending_sources,
                   current_updated_at, current_revision_id, review_status, content_json
            FROM reports WHERE mission_id = ? AND report_type = ?
            """,
            (mission_id, report_type),
        ).fetchone()
        if not row:
            return {
                "current_content": None,
                "pending_content": None,
                "pending_at": None,
                "pending_sources": None,
                "current_updated_at": None,
                "current_revision_id": None,
                "review_status": "draft",
                "content_json": None,
            }
        rs = row["review_status"] or "draft"
        if isinstance(rs, str):
            rs = rs.strip().lower() or "draft"
        else:
            rs = "draft"
        cj = row["content_json"] if "content_json" in row.keys() else None
        return {
            "current_content": row["current_content"],
            "pending_content": row["pending_content"],
            "pending_at": row["pending_at"],
            "pending_sources": row["pending_sources"],
            "current_updated_at": row["current_updated_at"],
            "current_revision_id": row["current_revision_id"],
            "review_status": rs,
            "content_json": cj,
        }


def set_pending(mission_id: str, report_type: str, content: str, sources: Optional[list[str]] = None) -> None:
    """Store new AI draft as pending (user can accept or reject). sources = list of file names for traceability during review only; not included in final product."""
    ensure_db()
    if report_type not in REPORT_TYPES:
        raise ValueError(f"report_type must be one of {REPORT_TYPES}")
    logger.info("set_pending mission_id=%s report_type=%s len=%s", mission_id, report_type, len(content))
    now = datetime.utcnow().isoformat() + "Z"
    sources_json = json.dumps(sources) if sources else None
    with get_connection() as conn:
        conn.execute(
            "UPDATE reports SET pending_content = ?, pending_at = ?, pending_sources = ? WHERE mission_id = ? AND report_type = ?",
            (content, now, sources_json, mission_id, report_type),
        )


def accept_pending(mission_id: str, report_type: str, output_path: Path) -> Path:
    """
    Make pending the new current, clear pending, checkpoint revision, write .docx.
    Returns path to written file.
    """
    ensure_db()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT pending_content FROM reports WHERE mission_id = ? AND report_type = ?",
            (mission_id, report_type),
        ).fetchone()
        if not row or not row["pending_content"]:
            raise ValueError("No pending content to accept")
        content = row["pending_content"]
        now = datetime.utcnow().isoformat() + "Z"
        conn.execute(
            """UPDATE reports SET current_content = ?, pending_content = NULL, pending_at = NULL, pending_sources = NULL, current_updated_at = ?
               WHERE mission_id = ? AND report_type = ?""",
            (content, now, mission_id, report_type),
        )
        insert_report_revision(
            conn, mission_id, report_type, content, "accept_pending", None
        )
    path = _report_output_path(output_path, report_type)
    html_to_docx(content, path, margins=None)
    _touch_source_checkpoint(mission_id)
    return path


def reject_pending(mission_id: str, report_type: str) -> None:
    """Discard pending AI draft."""
    ensure_db()
    now = datetime.utcnow().isoformat() + "Z"
    with get_connection() as conn:
        conn.execute(
            "UPDATE reports SET pending_content = NULL, pending_at = NULL, pending_sources = NULL WHERE mission_id = ? AND report_type = ?",
            (mission_id, report_type),
        )


def get_report_docs_used(mission_id: str, report_type: str) -> List[str]:
    """Return the list of doc paths last used for this report (empty if none or after reset)."""
    ensure_db()
    if report_type not in REPORT_TYPES:
        return []
    with get_connection() as conn:
        row = conn.execute(
            "SELECT last_used_doc_paths FROM reports WHERE mission_id = ? AND report_type = ?",
            (mission_id, report_type),
        ).fetchone()
    if not row or not row["last_used_doc_paths"]:
        return []
    try:
        out = json.loads(row["last_used_doc_paths"])
        return list(out) if isinstance(out, list) else []
    except (TypeError, json.JSONDecodeError):
        return []


def set_report_docs_used(mission_id: str, report_type: str, doc_paths: List[str]) -> None:
    """Store the set of doc paths used for the last update of this report (for incremental updates)."""
    ensure_db()
    if report_type not in REPORT_TYPES:
        raise ValueError(f"report_type must be one of {REPORT_TYPES}")
    paths_json = json.dumps(list(doc_paths))
    with get_connection() as conn:
        conn.execute(
            "UPDATE reports SET last_used_doc_paths = ? WHERE mission_id = ? AND report_type = ?",
            (paths_json, mission_id, report_type),
        )


def clear_report_docs_used(mission_id: str, report_type: str) -> None:
    """Clear last-used docs for this report so the next Update uses all documents."""
    ensure_db()
    if report_type not in REPORT_TYPES:
        return
    with get_connection() as conn:
        conn.execute(
            "UPDATE reports SET last_used_doc_paths = NULL WHERE mission_id = ? AND report_type = ?",
            (mission_id, report_type),
        )
    logger.info("clear_report_docs_used mission_id=%s report_type=%s", mission_id, report_type)


def reset_report_to_template(mission_id: str, report_type: str) -> None:
    """Reset this report's draft to the skeleton template. Clears pending_content and pending_edits, sets current_content to template, and clears docs-used so next Update uses all documents."""
    ensure_db()
    if report_type not in REPORT_TYPES:
        raise ValueError(f"report_type must be one of {REPORT_TYPES}")
    template = get_document_template(report_type) or ""
    now = datetime.utcnow().isoformat() + "Z"
    with get_connection() as conn:
        conn.execute(
            """UPDATE reports SET current_content = ?, current_updated_at = ?,
               pending_content = NULL, pending_at = NULL, pending_sources = NULL,
               last_used_doc_paths = NULL, review_status = 'draft'
               WHERE mission_id = ? AND report_type = ?""",
            (template, now, mission_id, report_type),
        )
        conn.execute(
            "DELETE FROM pending_edits WHERE mission_id = ? AND report_type = ?",
            (mission_id, report_type),
        )
    logger.info("reset_report_to_template mission_id=%s report_type=%s", mission_id, report_type)


def save_user_edit(
    mission_id: str,
    report_type: str,
    content: str,
    output_path: Path,
    margins: Optional[dict[str, float]] = None,
    content_json: Optional[str] = None,
) -> Path:
    """
    Update current content with user edits and write to output_path as .docx.
    margins: optional dict with keys top, right, bottom, left (inches).
    content_json: optional canonical ProseMirror/Tiptap JSON string (dual-write).
    Returns path to written file.
    """
    ensure_db()
    if report_type not in REPORT_TYPES:
        raise ValueError(f"report_type must be one of {REPORT_TYPES}")
    now = datetime.utcnow().isoformat() + "Z"
    with get_connection() as conn:
        if content_json is not None:
            conn.execute(
                """UPDATE reports SET current_content = ?, content_json = ?, current_updated_at = ?
                   WHERE LOWER(mission_id) = LOWER(?) AND report_type = ?""",
                (content, content_json, now, mission_id, report_type),
            )
        else:
            conn.execute(
                """UPDATE reports SET current_content = ?, current_updated_at = ?
                   WHERE LOWER(mission_id) = LOWER(?) AND report_type = ?""",
                (content, now, mission_id, report_type),
            )
        insert_report_revision(conn, mission_id, report_type, content, "save", None)
    path = _report_output_path(output_path, report_type)
    html_to_docx(content, path, margins=margins)
    _touch_source_checkpoint(mission_id)
    return path


def _report_output_path(output_path: Path, report_type: str) -> Path:
    """File name for report in drop-off folder (.docx)."""
    names = {
        "rmp": "Risk_Mitigation_Plan.docx",
        "timeline": "Mission_Timeline.docx",
        "aar": "After_Action_Report.docx",
        "sitrep": "SITREP.docx",
    }
    return Path(output_path) / names.get(report_type, f"{report_type}.docx")


# ---------- Structured edit proposals (collaborative editor) ----------


def get_pending_edits(mission_id: str, report_type: str) -> list[dict]:
    """Return list of pending edits for the report, ordered by ord."""
    ensure_db()
    if report_type not in REPORT_TYPES:
        raise ValueError(f"report_type must be one of {REPORT_TYPES}")
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT edit_id, section_id, target_block_id, operation, reason, evidence_refs,
                   old_html, new_html, status, ord,
                   suggestion_type, source_job_id, created_against_revision_id
            FROM pending_edits WHERE mission_id = ? AND report_type = ? ORDER BY ord
            """,
            (mission_id, report_type),
        ).fetchall()
    return [
        {
            "edit_id": r["edit_id"],
            "section_id": r["section_id"],
            "target_block_id": r["target_block_id"],
            "operation": r["operation"],
            "reason": r["reason"],
            "evidence_refs": json.loads(r["evidence_refs"]) if r["evidence_refs"] else [],
            "old_html": r["old_html"],
            "new_html": r["new_html"],
            "status": r["status"],
            "ord": r["ord"],
            "suggestion_type": r["suggestion_type"] or "structured_block_edit",
            "source_job_id": r["source_job_id"],
            "created_against_revision_id": r["created_against_revision_id"],
        }
        for r in rows
    ]


def set_pending_edits(
    mission_id: str,
    report_type: str,
    edits: list[dict],
    *,
    source_job_id: Optional[str] = None,
    default_suggestion_type: str = "structured_block_edit",
) -> None:
    """Replace all pending edits for this report. Optionally bind to a pipeline job and current revision."""
    ensure_db()
    if report_type not in REPORT_TYPES:
        raise ValueError(f"report_type must be one of {REPORT_TYPES}")
    with get_connection() as conn:
        rev_row = conn.execute(
            "SELECT current_revision_id FROM reports WHERE mission_id = ? AND report_type = ?",
            (mission_id, report_type),
        ).fetchone()
        baseline_revision_id = rev_row["current_revision_id"] if rev_row else None
        conn.execute(
            "DELETE FROM pending_edits WHERE mission_id = ? AND report_type = ?",
            (mission_id, report_type),
        )
        seen_edit_ids: set[str] = set()
        for i, e in enumerate(edits):
            sug = e.get("suggestion_type") or default_suggestion_type
            job_id = e.get("source_job_id") or source_job_id
            edit_id = (e.get("edit_id") or "").strip()
            if not edit_id or edit_id in seen_edit_ids:
                edit_id = f"edit_{uuid.uuid4().hex[:12]}"
            seen_edit_ids.add(edit_id)
            conn.execute(
                """
                INSERT INTO pending_edits (
                    mission_id, report_type, edit_id, section_id, target_block_id, operation,
                    reason, evidence_refs, old_html, new_html, status, ord,
                    suggestion_type, source_job_id, created_against_revision_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mission_id,
                    report_type,
                    edit_id,
                    e.get("section_id"),
                    e.get("target_block_id", ""),
                    e.get("operation", "replace"),
                    e.get("reason"),
                    json.dumps(e.get("evidence_refs") or e.get("evidence") or []),
                    e.get("old_html"),
                    e.get("new_html"),
                    e.get("status", "pending"),
                    e.get("ord", i),
                    sug,
                    job_id,
                    e.get("created_against_revision_id") or baseline_revision_id,
                ),
            )
    logger.info("set_pending_edits mission_id=%s report_type=%s count=%s", mission_id, report_type, len(edits))


def accept_edit(mission_id: str, report_type: str, edit_id: str) -> None:
    """Set status of one edit to accepted."""
    ensure_db()
    with get_connection() as conn:
        conn.execute(
            "UPDATE pending_edits SET status = 'accepted' WHERE mission_id = ? AND report_type = ? AND edit_id = ?",
            (mission_id, report_type, edit_id),
        )


def reject_edit(mission_id: str, report_type: str, edit_id: str) -> None:
    """Set status of one edit to rejected."""
    ensure_db()
    with get_connection() as conn:
        conn.execute(
            "UPDATE pending_edits SET status = 'rejected' WHERE mission_id = ? AND report_type = ? AND edit_id = ?",
            (mission_id, report_type, edit_id),
        )


def accept_all_edits(mission_id: str, report_type: str) -> None:
    """Set all pending edits for this report to accepted."""
    ensure_db()
    with get_connection() as conn:
        conn.execute(
            "UPDATE pending_edits SET status = 'accepted' WHERE mission_id = ? AND report_type = ?",
            (mission_id, report_type),
        )


def reject_all_edits(mission_id: str, report_type: str) -> None:
    """Remove all pending edits for this report (or set all to rejected). We delete so report has no pending edits."""
    ensure_db()
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM pending_edits WHERE mission_id = ? AND report_type = ?",
            (mission_id, report_type),
        )


def get_report_preview(mission_id: str, report_type: str) -> str:
    """
    Return HTML preview of current_content with all pending edits applied (for display).
    Lets the user see proposed content in the draft before accepting.
    """
    if report_type not in REPORT_TYPES:
        raise ValueError(f"report_type must be one of {REPORT_TYPES}")
    report = get_report(mission_id, report_type)
    current = report.get("current_content") or ""
    edits_raw = get_pending_edits(mission_id, report_type)
    if not edits_raw:
        return current
    blocks = parse_html_to_blocks(current)
    edited_blocks = apply_edits_to_blocks_for_preview(blocks, edits_raw)
    return blocks_to_html(edited_blocks)


def apply_accepted_edits(mission_id: str, report_type: str, output_path: Path) -> Path:
    """
    Apply all accepted edits to current_content (block parse -> apply -> serialize), update current_content,
    clear pending_edits, write .docx. Returns path to written file.
    """
    ensure_db()
    if report_type not in REPORT_TYPES:
        raise ValueError(f"report_type must be one of {REPORT_TYPES}")
    report = get_report(mission_id, report_type)
    current = report.get("current_content") or ""
    edits_raw = get_pending_edits(mission_id, report_type)
    accepted_list = [e for e in edits_raw if (e.get("status") or "").lower() == "accepted"]
    if not accepted_list:
        raise ValueError("No accepted edits to apply")
    blocks = parse_html_to_blocks(current)
    edited_blocks = apply_edits_to_blocks(blocks, accepted_list)
    new_html = blocks_to_html(edited_blocks)
    now = datetime.utcnow().isoformat() + "Z"
    accepted_ids = [e.get("edit_id") for e in accepted_list if e.get("edit_id")]
    with get_connection() as conn:
        conn.execute(
            "UPDATE reports SET current_content = ?, current_updated_at = ? WHERE mission_id = ? AND report_type = ?",
            (new_html, now, mission_id, report_type),
        )
        insert_report_revision(
            conn, mission_id, report_type, new_html, "apply_edits", None
        )
        if accepted_ids:
            placeholders = ",".join("?" * len(accepted_ids))
            conn.execute(
                "DELETE FROM pending_edits WHERE mission_id = ? AND report_type = ? AND edit_id IN (" + placeholders + ")",
                (mission_id, report_type, *accepted_ids),
            )
    path = _report_output_path(output_path, report_type)
    html_to_docx(new_html, path, margins=None)
    logger.info("apply_accepted_edits mission_id=%s report_type=%s", mission_id, report_type)
    _touch_source_checkpoint(mission_id)
    return path
