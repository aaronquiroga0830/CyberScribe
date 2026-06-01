"""Users, password hashing, and opaque session tokens (HTTP-only cookie)."""
from __future__ import annotations

import hashlib
import re
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

import bcrypt

from src.db.models import get_connection, init_db

SESSION_DAYS = 14

# Stored in DB column `users.email` (historic name); values are normalized login ids (username).
_LOGIN_ID_RE = re.compile(r"^[a-z0-9._@+-]{1,128}$")


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def normalize_login_id(raw: str) -> str:
    """
    Normalize username/login identifier. Allows letters, digits, . _ - @ +
    (@ kept for existing accounts and optional email-shaped ids).
    """
    s = (raw or "").strip().lower()
    if not s:
        raise ValueError("Username is required")
    if len(s) > 128 or not _LOGIN_ID_RE.match(s):
        raise ValueError(
            "Username must be 1–128 characters and may only contain "
            "letters, numbers, and . _ - @ +"
        )
    return s


def user_row_to_public(row: dict[str, Any]) -> dict[str, Any]:
    """Map DB row (column email = login id) to API shape."""
    d = dict(row)
    if "email" in d:
        d["username"] = d.pop("email")
    return d


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except Exception:
        return False


def count_users() -> int:
    init_db()
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
        return int(row["c"])


def create_user(
    username: str,
    password: str,
    *,
    display_name: str | None = None,
    is_admin: bool = False,
) -> str:
    init_db()
    login_norm = normalize_login_id(username)
    uid = str(uuid.uuid4())[:12]
    ph = hash_password(password)
    if display_name and str(display_name).strip():
        dn = str(display_name).strip()
    elif "@" in login_norm:
        dn = login_norm.split("@", 1)[0].strip() or login_norm
    else:
        dn = login_norm
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (id, email, password_hash, display_name, is_admin, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (uid, login_norm, ph, dn, 1 if is_admin else 0, _now()),
        )
    return uid


def get_user_by_login_id(login_id: str) -> Optional[dict[str, Any]]:
    """Lookup by username / login id (DB column email). Returns public API dict."""
    try:
        login_norm = normalize_login_id(login_id)
    except ValueError:
        return None
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, email, display_name, is_admin, created_at FROM users WHERE email = ?",
            (login_norm,),
        ).fetchone()
    return user_row_to_public(dict(row)) if row else None


def get_user_by_email(email: str) -> Optional[dict[str, Any]]:
    """Deprecated alias for roster code paths; same as get_user_by_login_id."""
    return get_user_by_login_id(email)


def get_user_by_id(user_id: str) -> Optional[dict[str, Any]]:
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, email, display_name, is_admin, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return user_row_to_public(dict(row)) if row else None


def verify_login(username: str, password: str) -> Optional[dict[str, Any]]:
    try:
        login_norm = normalize_login_id(username)
    except ValueError:
        return None
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, email, display_name, is_admin, created_at FROM users WHERE email = ?",
            (login_norm,),
        ).fetchone()
        if not row:
            return None
        full = conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (row["id"],)
        ).fetchone()
        if not full or not verify_password(password, full["password_hash"]):
            return None
        return user_row_to_public(dict(row))


def create_session(user_id: str) -> tuple[str, datetime]:
    """Return (opaque_token, expires_at)."""
    init_db()
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    exp = datetime.utcnow() + timedelta(days=SESSION_DAYS)
    exp_s = exp.isoformat() + "Z"
    sid = str(uuid.uuid4())[:12]
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_sessions (id, user_id, token_hash, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (sid, user_id, token_hash, exp_s, _now()),
        )
    return token, exp


def delete_session_by_token(token: str) -> None:
    if not token:
        return
    th = hashlib.sha256(token.encode()).hexdigest()
    with get_connection() as conn:
        conn.execute("DELETE FROM user_sessions WHERE token_hash = ?", (th,))


def get_user_by_session_token(token: str) -> Optional[dict[str, Any]]:
    if not token:
        return None
    init_db()
    th = hashlib.sha256(token.encode()).hexdigest()
    now = _now()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.email, u.display_name, u.is_admin, u.created_at
            FROM user_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at > ?
            """,
            (th, now),
        ).fetchone()
    return user_row_to_public(dict(row)) if row else None


def prune_expired_sessions() -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM user_sessions WHERE expires_at <= ?", (_now(),))


def clear_all_users() -> int:
    """
    Remove every account and related auth/RBAC rows (sessions, mission members, presence).
    Missions, reports, and chat text remain; chat_messages.user_id is cleared.
    Returns the number of user rows deleted.
    """
    init_db()
    with get_connection() as conn:
        n = int(conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"])
        conn.execute("DELETE FROM user_sessions")
        conn.execute("DELETE FROM mission_presence")
        conn.execute("DELETE FROM mission_members")
        try:
            conn.execute("UPDATE missions SET created_by_user_id = NULL")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute("UPDATE chat_messages SET user_id = NULL")
        except sqlite3.OperationalError:
            pass
        conn.execute("DELETE FROM users")
    return n
