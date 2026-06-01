"""Lightweight mission presence (SQLite heartbeats)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from src.db.models import get_connection, init_db


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def heartbeat(mission_id: str, user_id: str) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO mission_presence (mission_id, user_id, last_seen_at)
            VALUES (?, ?, ?)
            ON CONFLICT(mission_id, user_id) DO UPDATE SET last_seen_at = excluded.last_seen_at
            """,
            (mission_id, user_id, _now()),
        )


def list_presence(mission_id: str, ttl_seconds: int = 90) -> list[dict[str, Any]]:
    init_db()
    cutoff = (datetime.utcnow() - timedelta(seconds=ttl_seconds)).isoformat() + "Z"
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT mp.user_id, mp.last_seen_at, u.email AS login_id, u.display_name
            FROM mission_presence mp
            JOIN users u ON u.id = mp.user_id
            WHERE mp.mission_id = ? AND mp.last_seen_at >= ?
            ORDER BY mp.last_seen_at DESC
            """,
            (mission_id, cutoff),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        if "login_id" in d:
            d["username"] = d.pop("login_id")
        out.append(d)
    return out
