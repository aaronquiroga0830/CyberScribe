"""
Explicit section identity per report template (Phase 1).
Seeded into `report_section_definitions` for section-aware updates in later phases.
"""
from __future__ import annotations

import sqlite3

# (report_type, section_key, display_title, sort_order, policy)
# policy: editable | locked_heading
SECTION_DEFINITION_SEED: list[tuple[str, str, str, int, str]] = [
    ("rmp", "title", "Risk Mitigation Plan", 0, "locked_heading"),
    ("rmp", "body_intro", "Introduction body", 1, "editable"),
    ("rmp", "executive_summary", "Executive Summary", 2, "editable"),
    ("rmp", "findings", "Findings", 3, "editable"),
    ("rmp", "recommendations", "Recommendations", 4, "editable"),
    ("timeline", "title", "Mission Timeline", 0, "locked_heading"),
    ("timeline", "body_intro", "Introduction body", 1, "editable"),
    ("timeline", "chronological_events", "Chronological Events", 2, "editable"),
    ("aar", "title", "After Action Report", 0, "locked_heading"),
    ("aar", "body_intro", "Introduction body", 1, "editable"),
    ("aar", "mission_summary", "Mission Summary", 2, "editable"),
    ("aar", "objectives", "Objectives", 3, "editable"),
    ("aar", "actions_taken", "Actions Taken", 4, "editable"),
    ("aar", "outcomes", "Outcomes and Lessons Learned", 5, "editable"),
    ("sitrep", "title", "Situation Report", 0, "locked_heading"),
    ("sitrep", "body_intro", "Introduction body", 1, "editable"),
    ("sitrep", "current_status", "Current Status", 2, "editable"),
    ("sitrep", "key_events", "Key Events", 3, "editable"),
    ("sitrep", "risks", "Risks and Updates", 4, "editable"),
]


def seed_report_section_definitions(conn: sqlite3.Connection) -> None:
    """Idempotent: PRIMARY KEY (report_type, section_key) + INSERT OR IGNORE."""
    for report_type, section_key, display_title, sort_order, policy in SECTION_DEFINITION_SEED:
        conn.execute(
            """
            INSERT OR IGNORE INTO report_section_definitions
            (report_type, section_key, display_title, sort_order, policy)
            VALUES (?, ?, ?, ?, ?)
            """,
            (report_type, section_key, display_title, sort_order, policy),
        )


def list_section_definitions_for_report_type(report_type: str) -> list[dict]:
    from src.db.models import get_connection  # local import avoids cycles at import time

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT report_type, section_key, display_title, sort_order, policy
            FROM report_section_definitions
            WHERE report_type = ?
            ORDER BY sort_order, section_key
            """,
            (report_type,),
        ).fetchall()
    return [dict(r) for r in rows]
