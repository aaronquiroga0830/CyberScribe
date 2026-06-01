"""Unified activity feed: jobs, approvals, comments, chat."""
from __future__ import annotations

import json
from typing import Any

from src.db.models import get_connection, init_db


def mission_activity_feed(mission_id: str, limit: int = 80) -> list[dict[str, Any]]:
    init_db()
    limit = max(1, min(limit, 200))
    events: list[dict[str, Any]] = []

    with get_connection() as conn:
        for row in conn.execute(
            """
            SELECT id, report_types, status, error_message, created_at, finished_at, job_kind
            FROM pipeline_jobs
            WHERE mission_id = ? AND finished_at IS NOT NULL
            ORDER BY finished_at DESC
            LIMIT ?
            """,
            (mission_id, limit),
        ).fetchall():
            events.append(
                {
                    "kind": "pipeline_job",
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "report_types": row["report_types"],
                    "status": row["status"],
                    "error_message": row["error_message"],
                    "finished_at": row["finished_at"],
                    "job_kind": row["job_kind"],
                }
            )

        for row in conn.execute(
            """
            SELECT id, report_type, event_type, from_status, to_status, actor_label, created_at
            FROM report_approval_events
            WHERE mission_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (mission_id, limit),
        ).fetchall():
            events.append(
                {
                    "kind": "approval",
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "report_type": row["report_type"],
                    "event_type": row["event_type"],
                    "from_status": row["from_status"],
                    "to_status": row["to_status"],
                    "actor_label": row["actor_label"],
                }
            )

        for row in conn.execute(
            """
            SELECT id, report_type, author_label, body, created_at, parent_id
            FROM report_comments
            WHERE mission_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (mission_id, limit),
        ).fetchall():
            events.append(
                {
                    "kind": "comment",
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "report_type": row["report_type"],
                    "author_label": row["author_label"],
                    "body": row["body"],
                    "parent_id": row["parent_id"],
                }
            )

        for row in conn.execute(
            """
            SELECT id, report_type, user_id, scope, role, content, created_at, section_key
            FROM chat_messages
            WHERE mission_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (mission_id, limit),
        ).fetchall():
            events.append(
                {
                    "kind": "chat",
                    "id": row["id"],
                    "created_at": row["created_at"],
                    "report_type": row["report_type"],
                    "user_id": row["user_id"],
                    "scope": row["scope"],
                    "role": row["role"],
                    "content": row["content"],
                    "section_key": row["section_key"],
                }
            )

    def sort_key(e: dict[str, Any]) -> str:
        return e.get("created_at") or e.get("finished_at") or ""

    events.sort(key=sort_key, reverse=True)
    return events[:limit]
