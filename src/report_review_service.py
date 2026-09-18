"""
Phase 5: report review status, threaded comments, and auditable approval events.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any

from src.db.models import REPORT_TYPES, get_connection, init_db

logger = logging.getLogger(__name__)

REVIEW_STATUSES = ("draft", "in_review", "crew_lead_approved", "mel_approved", "final")

# Allowed transitions (enforced on PATCH review-status).
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "draft": frozenset({"in_review"}),
    "in_review": frozenset({"draft", "crew_lead_approved"}),
    "crew_lead_approved": frozenset({"in_review", "mel_approved"}),
    "mel_approved": frozenset({"in_review", "final"}),
    "final": frozenset({"draft"}),
}


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def normalize_review_status(raw: str | None) -> str:
    s = (raw or "draft").strip().lower()
    return s if s in REVIEW_STATUSES else "draft"


def is_ai_update_locked(mission_id: str, report_type: str) -> bool:
    """Block pipeline Update and inline-assist when MEL has approved or document is final."""
    st = get_review_status(mission_id, report_type)
    return st in ("mel_approved", "final")


def is_content_locked(mission_id: str, report_type: str) -> bool:
    """Block human save / apply / accept pending / reset when final."""
    return get_review_status(mission_id, report_type) == "final"


def get_review_status(mission_id: str, report_type: str) -> str:
    init_db()
    if report_type not in REPORT_TYPES:
        return "draft"
    with get_connection() as conn:
        row = conn.execute(
            "SELECT review_status FROM reports WHERE mission_id = ? AND report_type = ?",
            (mission_id, report_type),
        ).fetchone()
    return normalize_review_status(row["review_status"] if row else None)


def _log_event(
    conn,
    mission_id: str,
    report_type: str,
    event_type: str,
    *,
    from_status: str | None = None,
    to_status: str | None = None,
    actor_label: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    eid = str(uuid.uuid4())[:12]
    conn.execute(
        """
        INSERT INTO report_approval_events (
            id, mission_id, report_type, event_type, from_status, to_status, actor_label, detail_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            eid,
            mission_id,
            report_type,
            event_type,
            from_status,
            to_status,
            actor_label,
            json.dumps(detail) if detail else None,
            _now(),
        ),
    )


def transition_review_status(
    mission_id: str,
    report_type: str,
    new_status: str,
    *,
    actor_label: str | None = None,
    transition_comment: str | None = None,
) -> str:
    """Validate and apply status change. Returns new status. Raises ValueError if illegal."""
    init_db()
    if report_type not in REPORT_TYPES:
        raise ValueError("Invalid report_type")
    target = normalize_review_status(new_status)
    if target not in REVIEW_STATUSES:
        raise ValueError(f"status must be one of: {REVIEW_STATUSES}")

    with get_connection() as conn:
        row = conn.execute(
            "SELECT review_status FROM reports WHERE mission_id = ? AND report_type = ?",
            (mission_id, report_type),
        ).fetchone()
        if not row:
            raise ValueError("Report not found")
        cur = normalize_review_status(row["review_status"])
        allowed = ALLOWED_TRANSITIONS.get(cur, frozenset())
        if target not in allowed:
            raise ValueError(f"Cannot transition from '{cur}' to '{target}'")
        conn.execute(
            "UPDATE reports SET review_status = ? WHERE mission_id = ? AND report_type = ?",
            (target, mission_id, report_type),
        )
        tc = (transition_comment or "").strip()
        detail: dict[str, Any] | None = {"transition_comment": tc} if tc else None
        _log_event(
            conn,
            mission_id,
            report_type,
            "status_change",
            from_status=cur,
            to_status=target,
            actor_label=actor_label,
            detail=detail,
        )
    logger.info(
        "review_status mission_id=%s report_type=%s %s -> %s actor=%s",
        mission_id,
        report_type,
        cur,
        target,
        actor_label,
    )
    return target


def finalize_report_export(
    mission_id: str,
    report_type: str,
    *,
    actor_label: str | None = None,
    current_revision_id: str | None = None,
) -> None:
    """mel_approved → final with audit log (§11.4). Raises ValueError if wrong state."""
    init_db()
    cur = get_review_status(mission_id, report_type)
    if cur != "mel_approved":
        raise ValueError("Finalize is only allowed when status is mel_approved")
    with get_connection() as conn:
        conn.execute(
            "UPDATE reports SET review_status = 'final' WHERE mission_id = ? AND report_type = ?",
            (mission_id, report_type),
        )
        _log_event(
            conn,
            mission_id,
            report_type,
            "final_export",
            from_status="mel_approved",
            to_status="final",
            actor_label=actor_label,
            detail={"current_revision_id": current_revision_id} if current_revision_id else None,
        )


def list_approval_events(mission_id: str, report_type: str, *, limit: int = 50) -> list[dict[str, Any]]:
    init_db()
    if report_type not in REPORT_TYPES:
        return []
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, event_type, from_status, to_status, actor_label, detail_json, created_at
            FROM report_approval_events
            WHERE mission_id = ? AND report_type = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (mission_id, report_type, limit),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        detail = None
        if r["detail_json"]:
            try:
                detail = json.loads(r["detail_json"])
            except json.JSONDecodeError:
                detail = None
        out.append(
            {
                "id": r["id"],
                "event_type": r["event_type"],
                "from_status": r["from_status"],
                "to_status": r["to_status"],
                "actor_label": r["actor_label"],
                "detail": detail,
                "created_at": r["created_at"],
            }
        )
    return out


_ANCHOR_JSON_MAX_BYTES = 8192


def _normalize_anchor_json_payload(
    anchor_json: Any,
) -> tuple[str | None, str | None]:
    """Return (json string for DB or None, sectionKey extracted for anchor_section_key)."""
    if anchor_json is None:
        return None, None
    if isinstance(anchor_json, str):
        s = anchor_json.strip()
        if not s:
            return None, None
        try:
            obj = json.loads(s)
        except json.JSONDecodeError as e:
            raise ValueError(f"anchor_json must be valid JSON: {e}") from e
    elif isinstance(anchor_json, dict):
        obj = anchor_json
    else:
        raise ValueError("anchor_json must be an object or JSON string")
    dumped = json.dumps(obj, separators=(",", ":"))
    if len(dumped.encode("utf-8")) > _ANCHOR_JSON_MAX_BYTES:
        raise ValueError("anchor_json is too large")
    sk = obj.get("sectionKey") if isinstance(obj.get("sectionKey"), str) else None
    if sk is not None:
        sk = sk.strip() or None
    return dumped, sk


def add_comment(
    mission_id: str,
    report_type: str,
    body: str,
    *,
    parent_id: str | None = None,
    anchor_section_key: str | None = None,
    anchor_json: Any = None,
    author_label: str | None = None,
) -> str:
    init_db()
    if report_type not in REPORT_TYPES:
        raise ValueError("Invalid report_type")
    text = (body or "").strip()
    if not text:
        raise ValueError("Comment body is required")
    aj_str, sk_from_anchor = _normalize_anchor_json_payload(anchor_json)
    section_key = (anchor_section_key or "").strip() or None
    if sk_from_anchor:
        section_key = section_key or sk_from_anchor
    cid = str(uuid.uuid4())[:12]
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO report_comments (
                id, mission_id, report_type, parent_id, anchor_section_key, author_label, body, anchor_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cid,
                mission_id,
                report_type,
                parent_id,
                section_key,
                author_label,
                text,
                aj_str,
                _now(),
            ),
        )
        _log_event(
            conn,
            mission_id,
            report_type,
            "comment",
            actor_label=author_label,
            detail={
                "comment_id": cid,
                "anchor_section_key": section_key,
                "has_anchor": bool(aj_str),
            },
        )
    return cid


def list_comments(mission_id: str, report_type: str) -> list[dict[str, Any]]:
    init_db()
    if report_type not in REPORT_TYPES:
        return []
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, parent_id, anchor_section_key, author_label, body, anchor_json, created_at
            FROM report_comments
            WHERE mission_id = ? AND report_type = ?
            ORDER BY created_at ASC
            """,
            (mission_id, report_type),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        raw = d.get("anchor_json")
        parsed: dict[str, Any] | None = None
        if raw:
            try:
                p = json.loads(raw) if isinstance(raw, str) else None
                if isinstance(p, dict):
                    parsed = p
            except json.JSONDecodeError:
                parsed = None
        d["anchor"] = parsed
        d.pop("anchor_json", None)
        out.append(d)
    return out


def delete_comment(mission_id: str, report_type: str, comment_id: str) -> None:
    """Remove one comment. Deleting a root comment also removes all replies (parent_id = root)."""
    init_db()
    if report_type not in REPORT_TYPES:
        raise ValueError("Invalid report_type")
    cid = (comment_id or "").strip()
    if not cid:
        raise ValueError("Comment id is required")
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, parent_id FROM report_comments
            WHERE mission_id = ? AND report_type = ? AND id = ?
            """,
            (mission_id, report_type, cid),
        ).fetchone()
        if not row:
            raise ValueError("Comment not found")
        parent_id = row["parent_id"]
        is_root = parent_id is None or str(parent_id).strip() == ""
        if is_root:
            conn.execute(
                """
                DELETE FROM report_comments
                WHERE mission_id = ? AND report_type = ? AND (id = ? OR parent_id = ?)
                """,
                (mission_id, report_type, cid, cid),
            )
        else:
            conn.execute(
                """
                DELETE FROM report_comments
                WHERE mission_id = ? AND report_type = ? AND id = ?
                """,
                (mission_id, report_type, cid),
            )
        _log_event(
            conn,
            mission_id,
            report_type,
            "comment_deleted",
            detail={"comment_id": cid, "removed_thread": is_root},
        )
