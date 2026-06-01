"""
Mission lifecycle: create (from UI), list, get.
Stores mission name, document pick-up location (source_path), drop-off location (output_path),
plus CPT, workflow_title, dates, operators, MEL, CCL, auto_update_frequency.
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Any

from src.db.models import get_connection, init_db, _slug, REPORT_TYPES
from src.templates.document_templates import get_document_template


def ensure_db() -> None:
    init_db()


def create_mission(
    name: str,
    source_path: str | Path,
    output_path: str | Path,
    mission_id: Optional[str] = None,
    cpt: Optional[str] = None,
    workflow_title: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    operators: Optional[list[dict[str, str]]] = None,
    mel: Optional[str] = None,
    ccl_host: Optional[list[str] | str] = None,
    ccl_network: Optional[list[str] | str] = None,
    auto_update_frequency: Optional[str] = None,
    created_by_user_id: Optional[str] = None,
) -> str:
    """
    Create a new mission and start it (status=active).
    Returns mission_id. source_path = input folder; output_path = drop-off.
    operators: list of {name, role: "Host"|"Network"}. ccl_host/ccl_network: list or comma-sep.
    auto_update_frequency: "off" | "hourly" | "6h" | "daily".
    """
    ensure_db()
    source_path = Path(source_path).resolve()
    output_path = Path(output_path).resolve()
    now = datetime.utcnow().isoformat() + "Z"
    mid = mission_id or _slug(name)
    with get_connection() as conn:
        existing = conn.execute("SELECT 1 FROM missions WHERE id = ?", (mid,)).fetchone()
        if existing:
            mid = f"{mid}_{datetime.utcnow().strftime('%Y%m%d%H%M')}"
        ops_json = json.dumps(operators) if operators else None
        ccl_h = json.dumps(ccl_host) if isinstance(ccl_host, list) else (ccl_host or None)
        ccl_n = json.dumps(ccl_network) if isinstance(ccl_network, list) else (ccl_network or None)
        conn.execute(
            """INSERT INTO missions (
                id, name, source_path, output_path, status, created_at, updated_at,
                cpt, workflow_title, start_date, end_date, operators, mel, ccl_host, ccl_network, auto_update_frequency
            ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mid, name, str(source_path), str(output_path), now, now,
                cpt or None, workflow_title or name, start_date, end_date, ops_json, mel, ccl_h, ccl_n,
                (auto_update_frequency or "off").strip() or "off",
            ),
        )
        for report_type in REPORT_TYPES:
            template = get_document_template(report_type)
            conn.execute(
                """INSERT INTO reports (mission_id, report_type, current_content, current_updated_at, review_status)
                   VALUES (?, ?, ?, ?, 'draft')""",
                (mid, report_type, template or None, now),
            )
        if created_by_user_id:
            try:
                conn.execute(
                    "UPDATE missions SET created_by_user_id = ? WHERE id = ?",
                    (created_by_user_id, mid),
                )
            except Exception:
                pass
            # Same connection as mission insert — avoid nested get_connection() (SQLite "database is locked").
            conn.execute(
                """
                INSERT INTO mission_members (mission_id, user_id, role, affiliation, created_at)
                VALUES (?, ?, 'mel', NULL, ?)
                ON CONFLICT(mission_id, user_id) DO UPDATE SET
                    role = excluded.role,
                    affiliation = excluded.affiliation
                """,
                (mid, created_by_user_id, now),
            )
    return mid


def list_missions(active_only: bool = False) -> list[dict]:
    """List all missions with status and last run times."""
    ensure_db()
    with get_connection() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT * FROM missions WHERE status = 'active' ORDER BY created_at DESC"
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM missions ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]


def list_missions_for_user(user_id: str, active_only: bool = False) -> list[dict]:
    """Missions where user is a member (planning pack RBAC)."""
    ensure_db()
    with get_connection() as conn:
        q = """
            SELECT m.* FROM missions m
            INNER JOIN mission_members mm ON mm.mission_id = m.id AND mm.user_id = ?
        """
        if active_only:
            q += " WHERE m.status = 'active'"
        q += " ORDER BY m.created_at DESC"
        rows = conn.execute(q, (user_id,)).fetchall()
        return [dict(r) for r in rows]


def _operator_count_subquery() -> str:
    return """COALESCE((
            SELECT COUNT(*) FROM mission_members mm_op
            WHERE mm_op.mission_id = m.id AND mm_op.role = 'operator'
        ), 0) AS operator_count"""


def list_missions_enriched(active_only: bool = False) -> list[dict]:
    """All missions plus operator_count (mission_members role=operator)."""
    ensure_db()
    with get_connection() as conn:
        where = " WHERE m.status = 'active'" if active_only else ""
        rows = conn.execute(
            f"""
            SELECT m.*, {_operator_count_subquery()}, NULL AS membership_role
            FROM missions m
            {where}
            ORDER BY m.created_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]


def list_missions_for_user_enriched(user_id: str, active_only: bool = False) -> list[dict]:
    """Member missions plus operator_count and caller's membership_role (mel, operator, …)."""
    ensure_db()
    with get_connection() as conn:
        q = f"""
            SELECT m.*, {_operator_count_subquery()}, mm.role AS membership_role
            FROM missions m
            INNER JOIN mission_members mm ON mm.mission_id = m.id AND mm.user_id = ?
        """
        if active_only:
            q += " WHERE m.status = 'active'"
        q += " ORDER BY m.created_at DESC"
        rows = conn.execute(q, (user_id,)).fetchall()
        return [dict(r) for r in rows]


def get_mission(mission_id: str) -> Optional[dict]:
    """Get one mission by id."""
    ensure_db()
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM missions WHERE id = ?", (mission_id,)).fetchone()
        return dict(row) if row else None


def reset_mission_reports_to_templates(mission_id: str) -> None:
    """
    Reset all report rows for a mission to their document templates.
    Clears pending_content, pending_edits, and sets current_content to the template for each report type.
    Use to recover from corrupted or oversized content (e.g. after a crash).
    """
    ensure_db()
    now = datetime.utcnow().isoformat() + "Z"
    with get_connection() as conn:
        for report_type in REPORT_TYPES:
            template = get_document_template(report_type)
            conn.execute(
                """UPDATE reports SET current_content = ?, current_updated_at = ?,
                   pending_content = NULL, pending_at = NULL, pending_sources = NULL,
                   review_status = 'draft'
                   WHERE LOWER(mission_id) = LOWER(?) AND report_type = ?""",
                (template or None, now, mission_id, report_type),
            )
        conn.execute(
            "DELETE FROM pending_edits WHERE LOWER(mission_id) = LOWER(?)",
            (mission_id,),
        )


def update_mission_status(mission_id: str, status: str) -> None:
    """Set status: 'active' | 'paused' | 'completed'."""
    if status not in ("active", "paused", "completed"):
        raise ValueError("status must be active, paused, or completed")
    ensure_db()
    now = datetime.utcnow().isoformat() + "Z"
    with get_connection() as conn:
        conn.execute(
            "UPDATE missions SET status = ?, updated_at = ? WHERE LOWER(id) = LOWER(?)",
            (status, now, mission_id),
        )


def update_mission_last_ingest(mission_id: str) -> None:
    now = datetime.utcnow().isoformat() + "Z"
    with get_connection() as conn:
        conn.execute(
            "UPDATE missions SET last_ingest_at = ?, updated_at = ? WHERE LOWER(id) = LOWER(?)",
            (now, now, mission_id),
        )


def update_mission_last_generated(mission_id: str) -> None:
    now = datetime.utcnow().isoformat() + "Z"
    with get_connection() as conn:
        conn.execute(
            "UPDATE missions SET last_generated_at = ?, updated_at = ? WHERE LOWER(id) = LOWER(?)",
            (now, now, mission_id),
        )


def delete_mission(mission_id: str) -> None:
    """
    Remove a mission and all dependent SQLite rows (reports, members, jobs, etc.).
    Does not delete on-disk indexes or mission folders under data/.

    Users who were only on this mission (no other mission_members rows) are removed
    from ``users`` along with their sessions; administrators (is_admin) are never deleted.
    """
    m = get_mission(mission_id)
    if not m:
        raise ValueError("Mission not found")
    mid = m["id"]
    ensure_db()
    with get_connection() as conn:
        member_rows = conn.execute(
            "SELECT DISTINCT user_id FROM mission_members WHERE mission_id = ?",
            (mid,),
        ).fetchall()
        member_user_ids = [str(r["user_id"]) for r in member_rows]

        for stmt, params in (
            ("DELETE FROM pending_edits WHERE mission_id = ?", (mid,)),
            ("DELETE FROM report_comments WHERE mission_id = ?", (mid,)),
            ("DELETE FROM report_approval_events WHERE mission_id = ?", (mid,)),
            ("DELETE FROM report_revisions WHERE mission_id = ?", (mid,)),
            ("DELETE FROM pipeline_jobs WHERE mission_id = ?", (mid,)),
            ("DELETE FROM chat_messages WHERE mission_id = ?", (mid,)),
            ("DELETE FROM mission_presence WHERE mission_id = ?", (mid,)),
            ("DELETE FROM auxiliary_knowledge_sources WHERE mission_id = ?", (mid,)),
            ("DELETE FROM mission_members WHERE mission_id = ?", (mid,)),
            ("DELETE FROM reports WHERE mission_id = ?", (mid,)),
            ("DELETE FROM missions WHERE id = ?", (mid,)),
        ):
            conn.execute(stmt, params)

        for uid in member_user_ids:
            urow = conn.execute(
                "SELECT is_admin FROM users WHERE id = ?", (uid,)
            ).fetchone()
            if not urow or int(urow["is_admin"] or 0):
                continue
            other = conn.execute(
                "SELECT 1 FROM mission_members WHERE user_id = ? LIMIT 1",
                (uid,),
            ).fetchone()
            if other:
                continue
            conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM mission_presence WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM chat_messages WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM users WHERE id = ?", (uid,))


def update_mission_metadata(
    mission_id: str,
    *,
    workflow_title: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    operators: Optional[list[dict[str, str]]] = None,
    mel: Optional[str] = None,
    ccl_host: Optional[list[str] | str] = None,
    ccl_network: Optional[list[str] | str] = None,
    auto_update_frequency: Optional[str] = None,
    ingest_mode: Optional[str] = None,
    lifecycle_status: Optional[str] = None,
) -> None:
    """Update mission Overview fields. Only provided fields are updated."""
    ensure_db()
    now = datetime.utcnow().isoformat() + "Z"
    updates = ["updated_at = ?"]
    params: list[Any] = [now]
    if workflow_title is not None:
        updates.append("workflow_title = ?")
        params.append(workflow_title)
    if start_date is not None:
        updates.append("start_date = ?")
        params.append(start_date)
    if end_date is not None:
        updates.append("end_date = ?")
        params.append(end_date)
    if operators is not None:
        updates.append("operators = ?")
        params.append(json.dumps(operators))
    if mel is not None:
        updates.append("mel = ?")
        params.append(mel)
    if ccl_host is not None:
        val = json.dumps(ccl_host) if isinstance(ccl_host, list) else ccl_host
        updates.append("ccl_host = ?")
        params.append(val)
    if ccl_network is not None:
        val = json.dumps(ccl_network) if isinstance(ccl_network, list) else ccl_network
        updates.append("ccl_network = ?")
        params.append(val)
    if auto_update_frequency is not None:
        updates.append("auto_update_frequency = ?")
        params.append(auto_update_frequency.strip() or "off")
    if ingest_mode is not None:
        im = (ingest_mode or "auto").strip().lower()
        if im not in ("auto", "manual"):
            raise ValueError("ingest_mode must be 'auto' or 'manual'")
        updates.append("ingest_mode = ?")
        params.append(im)
    if lifecycle_status is not None:
        ls = (lifecycle_status or "active").strip().lower()
        if ls not in ("active", "archived"):
            raise ValueError("lifecycle_status must be 'active' or 'archived'")
        updates.append("lifecycle_status = ?")
        params.append(ls)
    if len(params) <= 1:
        return
    params.append(mission_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE missions SET {', '.join(updates)} WHERE LOWER(id) = LOWER(?)",
            params,
        )
