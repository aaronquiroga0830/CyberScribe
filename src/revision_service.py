"""Report revision checkpoints (Phase 1): accept, save, apply-edits."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone

from src.db.models import get_connection, REPORT_TYPES


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def insert_report_revision(
    conn: sqlite3.Connection,
    mission_id: str,
    report_type: str,
    content_html: str,
    checkpoint_kind: str,
    source_job_id: str | None = None,
) -> str:
    """
    Insert one revision row and set reports.current_revision_id.
    checkpoint_kind: accept_pending | save | apply_edits
    """
    if report_type not in REPORT_TYPES:
        raise ValueError(f"report_type must be one of {REPORT_TYPES}")
    if checkpoint_kind not in ("accept_pending", "save", "apply_edits"):
        raise ValueError("checkpoint_kind must be accept_pending, save, or apply_edits")
    rev_id = str(uuid.uuid4())
    now = _utc_now()
    row = conn.execute(
        """
        SELECT COALESCE(MAX(revision_number), 0) + 1 AS n
        FROM report_revisions
        WHERE mission_id = ? AND report_type = ?
        """,
        (mission_id, report_type),
    ).fetchone()
    n = int(row["n"]) if row else 1
    conn.execute(
        """
        INSERT INTO report_revisions (
            id, mission_id, report_type, revision_number, content_html,
            checkpoint_kind, source_job_id, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rev_id,
            mission_id,
            report_type,
            n,
            content_html,
            checkpoint_kind,
            source_job_id,
            now,
        ),
    )
    conn.execute(
        """
        UPDATE reports SET current_revision_id = ?
        WHERE mission_id = ? AND report_type = ?
        """,
        (rev_id, mission_id, report_type),
    )
    return rev_id


def list_report_revisions(
    mission_id: str, report_type: str, limit: int = 50
) -> list[dict]:
    if report_type not in REPORT_TYPES:
        raise ValueError(f"report_type must be one of {REPORT_TYPES}")
    limit = max(1, min(200, limit))
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, mission_id, report_type, revision_number, checkpoint_kind,
                   source_job_id, created_at,
                   LENGTH(content_html) AS content_length
            FROM report_revisions
            WHERE mission_id = ? AND report_type = ?
            ORDER BY revision_number DESC
            LIMIT ?
            """,
            (mission_id, report_type, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_report_revision(mission_id: str, report_type: str, revision_id: str) -> dict | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, mission_id, report_type, revision_number, content_html,
                   checkpoint_kind, source_job_id, created_at
            FROM report_revisions
            WHERE id = ? AND mission_id = ? AND report_type = ?
            """,
            (revision_id, mission_id, report_type),
        ).fetchone()
    return dict(row) if row else None
