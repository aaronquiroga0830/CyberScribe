"""Mission-scoped membership, roster sync, and RBAC checks."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from typing import Any, Optional

from fastapi import HTTPException

from src.auth_service import create_user, get_user_by_login_id, normalize_login_id
from src.db.models import get_connection, init_db

VALID_ROLES = frozenset({"operator", "crew_lead", "mel", "viewer"})
VALID_AFF = frozenset({"host", "network"})

# Interim default for accounts created from mission form (operators / CCL). Do not use in production as-is.
MVP_TEAM_PROVISION_PASSWORD = "password"


def _ccl_login_list(val: list[str] | str | None) -> list[str]:
    if val is None:
        return []
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except json.JSONDecodeError:
            pass
        return [p.strip() for p in val.split(",") if p.strip()]
    return [str(x).strip() for x in val if str(x).strip()]


def _display_from_ccl_login(login: str) -> str:
    base = login.split("@", 1)[0].strip()
    if not base:
        return login
    parts = [p for p in re.split(r"[._-]+", base) if p]
    if not parts:
        return base
    return " ".join(p.capitalize() for p in parts)


def provision_mission_team_users(
    operators: list[dict[str, str]] | None,
    ccl_host: list[str] | str | None,
    ccl_network: list[str] | str | None,
    mel_login: str | None = None,
    mel_display: str | None = None,
) -> None:
    """Create missing user accounts so sync_roster and MEL assignment can attach users."""

    def try_create(login_raw: str, display_name: str | None) -> None:
        try:
            login = normalize_login_id(login_raw)
        except ValueError:
            return
        if get_user_by_login_id(login):
            return
        try:
            create_user(login, MVP_TEAM_PROVISION_PASSWORD, display_name=display_name)
        except sqlite3.IntegrityError:
            pass

    for op in operators or []:
        login_raw = (op.get("username") or op.get("email") or "").strip()
        if not login_raw:
            continue
        role_host = (op.get("role") or "").strip().lower()
        if role_host not in ("host", "network"):
            continue
        display = (op.get("name") or "").strip() or None
        try_create(login_raw, display)

    for login_raw in _ccl_login_list(ccl_host):
        if not login_raw.strip():
            continue
        try_create(login_raw, _display_from_ccl_login(login_raw))

    for login_raw in _ccl_login_list(ccl_network):
        if not login_raw.strip():
            continue
        try_create(login_raw, _display_from_ccl_login(login_raw))

    mel_raw = (mel_login or "").strip()
    if mel_raw:
        mel_disp = (mel_display or "").strip() or _display_from_ccl_login(mel_raw)
        try_create(mel_raw, mel_disp if mel_disp else None)

# (from_status, to_status) -> roles allowed (review-status PATCH)
_REVIEW_TRANSITION_ROLES: dict[tuple[str, str], frozenset[str]] = {
    ("draft", "in_review"): frozenset({"operator", "crew_lead", "mel"}),
    ("in_review", "draft"): frozenset({"operator", "crew_lead", "mel"}),
    ("in_review", "crew_lead_approved"): frozenset({"crew_lead", "mel"}),
    ("crew_lead_approved", "in_review"): frozenset({"crew_lead", "mel"}),
    ("crew_lead_approved", "mel_approved"): frozenset({"mel"}),
    ("mel_approved", "in_review"): frozenset({"mel"}),
    ("mel_approved", "final"): frozenset({"mel"}),  # also via finalize endpoint
    ("final", "draft"): frozenset({"mel"}),
}


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def get_membership(mission_id: str, user_id: str) -> Optional[dict[str, Any]]:
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT mission_id, user_id, role, affiliation, created_at
            FROM mission_members
            WHERE mission_id = ? AND user_id = ?
            """,
            (mission_id, user_id),
        ).fetchone()
    return dict(row) if row else None


def user_has_mel_role(user_id: str) -> bool:
    """True if this user is MEL on at least one mission."""
    if not user_id:
        return False
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM mission_members
            WHERE user_id = ? AND role = 'mel'
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
    return row is not None


def list_members(mission_id: str) -> list[dict[str, Any]]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT mm.mission_id, mm.user_id, mm.role, mm.affiliation, mm.created_at,
                   u.email AS login_id, u.display_name
            FROM mission_members mm
            JOIN users u ON u.id = mm.user_id
            WHERE mm.mission_id = ?
            ORDER BY mm.role, u.email
            """,
            (mission_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        if "login_id" in d:
            d["username"] = d.pop("login_id")
        out.append(d)
    return out


def add_member(
    mission_id: str,
    user_id: str,
    role: str,
    affiliation: str | None = None,
) -> None:
    init_db()
    r = role.strip().lower()
    if r not in VALID_ROLES:
        raise ValueError(f"Invalid role: {role}")
    aff = None
    if affiliation is not None:
        a = affiliation.strip().lower()
        aff = a if a in VALID_AFF else None
    if r in ("mel", "viewer"):
        aff = None
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO mission_members (mission_id, user_id, role, affiliation, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(mission_id, user_id) DO UPDATE SET
                role = excluded.role,
                affiliation = excluded.affiliation
            """,
            (mission_id, user_id, r, aff, _now()),
        )


def remove_member(mission_id: str, user_id: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM mission_members WHERE mission_id = ? AND user_id = ?",
            (mission_id, user_id),
        )


def assert_mission_not_archived(mission_row: dict[str, Any]) -> None:
    st = (mission_row.get("lifecycle_status") or "active").lower()
    if st == "archived":
        raise HTTPException(403, "Mission is archived (read-only).")


def require_mission_member(user_id: str, mission_id: str) -> dict[str, Any]:
    m = get_membership(mission_id, user_id)
    if not m:
        raise HTTPException(403, "You are not a member of this mission.")
    return m


def require_role(
    user_id: str, mission_id: str, allowed: frozenset[str] | set[str]
) -> dict[str, Any]:
    mem = require_mission_member(user_id, mission_id)
    if mem["role"] not in allowed:
        raise HTTPException(403, "This action requires a different mission role.")
    return mem


def require_mel(user_id: str, mission_id: str) -> dict[str, Any]:
    return require_role(user_id, mission_id, frozenset({"mel"}))


def assert_can_read_reports(user_id: str, mission_id: str) -> dict[str, Any]:
    """viewer+"""
    return require_mission_member(user_id, mission_id)


def assert_can_edit_report(user_id: str, mission_id: str) -> dict[str, Any]:
    mem = require_mission_member(user_id, mission_id)
    if mem["role"] == "viewer":
        raise HTTPException(403, "Viewers cannot edit reports.")
    return mem


def assert_can_run_ai(user_id: str, mission_id: str) -> dict[str, Any]:
    mem = require_mission_member(user_id, mission_id)
    if mem["role"] == "viewer":
        raise HTTPException(403, "Viewers cannot run AI updates.")
    return mem


def assert_can_manage_mission(user_id: str, mission_id: str) -> dict[str, Any]:
    return require_mel(user_id, mission_id)


def assert_review_transition_allowed(
    user_id: str, mission_id: str, from_status: str, to_status: str
) -> None:
    mem = require_mission_member(user_id, mission_id)
    key = (from_status.strip().lower(), to_status.strip().lower())
    allowed_roles = _REVIEW_TRANSITION_ROLES.get(key)
    if not allowed_roles:
        raise HTTPException(400, "Invalid status transition.")
    if mem["role"] not in allowed_roles:
        raise HTTPException(403, "Your role cannot perform this status transition.")


def assert_can_finalize(user_id: str, mission_id: str) -> None:
    require_role(user_id, mission_id, frozenset({"mel"}))


def apply_designated_mel_after_create(
    mission_id: str,
    mel_login: str | None,
    created_by_user_id: str | None,
) -> None:
    """
    When the create-mission form names a MEL (mel_username), make that user MEL on the mission.
    The creator was inserted as MEL in create_mission; if they differ from the designated MEL,
    demote the creator to viewer so there is a single MEL row for RBAC.
    """
    if not mel_login or not created_by_user_id:
        return
    raw = str(mel_login).strip()
    if not raw:
        return
    try:
        login = normalize_login_id(raw)
    except ValueError:
        return
    u = get_user_by_login_id(login)
    if not u:
        return
    add_member(mission_id, u["id"], "mel")
    if u["id"] != created_by_user_id:
        add_member(mission_id, created_by_user_id, "viewer")


def sync_roster_from_mission_payload(
    mission_id: str,
    operators: list[dict[str, str]] | None,
    ccl_host: list[str] | str | None,
    ccl_network: list[str] | str | None,
) -> None:
    """
    Link roster entries to users by email (field 'email' on operators, or string as email in CCL lists).
    Does not remove existing members; adds/updates operator and crew_lead rows.
    """
    init_db()

    seen_pairs: set[tuple[str, str]] = set()

    for op in operators or []:
        login_raw = (op.get("username") or op.get("email") or "").strip()
        role_host = (op.get("role") or "").strip().lower()
        aff = "host" if role_host == "host" else "network" if role_host == "network" else None
        if not login_raw or aff not in VALID_AFF:
            continue
        u = get_user_by_login_id(login_raw)
        if not u:
            continue
        key = (mission_id, u["id"])
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        add_member(mission_id, u["id"], "operator", aff)

    for login_raw in _ccl_login_list(ccl_host):
        if not login_raw.strip():
            continue
        u = get_user_by_login_id(login_raw)
        if not u:
            continue
        key = (mission_id, u["id"])
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        add_member(mission_id, u["id"], "crew_lead", "host")

    for login_raw in _ccl_login_list(ccl_network):
        if not login_raw.strip():
            continue
        u = get_user_by_login_id(login_raw)
        if not u:
            continue
        key = (mission_id, u["id"])
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        add_member(mission_id, u["id"], "crew_lead", "network")
