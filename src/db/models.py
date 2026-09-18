"""
SQLite persistence for missions and report state.
Enables long-running (e.g. 5-month) workflows with accept/reject and user edits.
"""
import sqlite3
import re
import uuid
from datetime import datetime
from contextlib import contextmanager
from typing import Iterator

from config.settings import DATA_DIR

DB_PATH = DATA_DIR / "agentic_rag.db"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Wait for locks (seconds). Reduces "database is locked" when another process/thread holds SQLite briefly.
_SQLITE_LOCK_TIMEOUT_S = 30.0

REPORT_TYPES = ("rmp", "timeline", "aar", "sitrep")


def _configure_sqlite_connection(conn: sqlite3.Connection) -> None:
    """WAL + busy timeout: fewer lock errors under concurrent API + scheduler / jobs."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")


def _slug(name: str) -> str:
    """Mission id: lowercase alphanumeric + underscores."""
    s = re.sub(r"[^\w\s-]", "", name.lower())
    s = re.sub(r"[-\s]+", "_", s).strip("_")
    return s or str(uuid.uuid4())[:8]


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(DB_PATH), timeout=_SQLITE_LOCK_TIMEOUT_S)
    conn.row_factory = sqlite3.Row
    _configure_sqlite_connection(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS missions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                source_path TEXT NOT NULL,
                output_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_ingest_at TEXT,
                last_generated_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                mission_id TEXT NOT NULL,
                report_type TEXT NOT NULL,
                current_content TEXT,
                pending_content TEXT,
                pending_at TEXT,
                pending_sources TEXT,
                current_updated_at TEXT,
                PRIMARY KEY (mission_id, report_type),
                FOREIGN KEY (mission_id) REFERENCES missions(id)
            )
        """)
        try:
            conn.execute("ALTER TABLE reports ADD COLUMN pending_sources TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists (e.g. after schema update)
        try:
            conn.execute("ALTER TABLE reports ADD COLUMN last_used_doc_paths TEXT")
        except sqlite3.OperationalError:
            pass  # column already exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_edits (
                mission_id TEXT NOT NULL,
                report_type TEXT NOT NULL,
                edit_id TEXT NOT NULL,
                section_id TEXT,
                target_block_id TEXT NOT NULL,
                operation TEXT NOT NULL,
                reason TEXT,
                evidence_refs TEXT,
                old_html TEXT,
                new_html TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                ord INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (mission_id, report_type, edit_id),
                FOREIGN KEY (mission_id) REFERENCES missions(id)
            )
        """)
        # Mission metadata (plan: CPT, workflow title, dates, operators, MEL, CCL, auto_update_frequency)
        for col, col_type in [
            ("cpt", "TEXT"),
            ("workflow_title", "TEXT"),
            ("start_date", "TEXT"),
            ("end_date", "TEXT"),
            ("operators", "TEXT"),  # JSON: list of {name, role: Host|Network}
            ("mel", "TEXT"),
            ("ccl_host", "TEXT"),   # JSON array or comma-sep
            ("ccl_network", "TEXT"),
            ("auto_update_frequency", "TEXT"),  # off | hourly | 6h | daily
        ]:
            try:
                conn.execute(f"ALTER TABLE missions ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_jobs (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                report_types TEXT,
                job_kind TEXT NOT NULL,
                status TEXT NOT NULL,
                progress_json TEXT NOT NULL DEFAULT '[]',
                error_message TEXT,
                fallback_used INTEGER NOT NULL DEFAULT 0,
                invalid_edit_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                FOREIGN KEY (mission_id) REFERENCES missions(id)
            )
        """)
        for col in ("failure_kind", "update_intent"):
            try:
                conn.execute(f"ALTER TABLE pipeline_jobs ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass
        for col in ("job_type", "scope_type", "retrieval_mode"):
            try:
                conn.execute(f"ALTER TABLE pipeline_jobs ADD COLUMN {col} TEXT")
            except sqlite3.OperationalError:
                pass

        try:
            conn.execute("ALTER TABLE missions ADD COLUMN ingest_mode TEXT DEFAULT 'auto'")
        except sqlite3.OperationalError:
            pass

        for ck_col in ("last_source_checkpoint_json", "last_source_checkpoint_at"):
            try:
                conn.execute(f"ALTER TABLE missions ADD COLUMN {ck_col} TEXT")
            except sqlite3.OperationalError:
                pass

        try:
            conn.execute("ALTER TABLE reports ADD COLUMN current_revision_id TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("ALTER TABLE reports ADD COLUMN review_status TEXT DEFAULT 'draft'")
        except sqlite3.OperationalError:
            pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS report_comments (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                report_type TEXT NOT NULL,
                parent_id TEXT,
                anchor_section_key TEXT,
                author_label TEXT,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (mission_id) REFERENCES missions(id)
            )
        """)
        try:
            conn.execute("ALTER TABLE report_comments ADD COLUMN anchor_json TEXT")
        except sqlite3.OperationalError:
            pass
        conn.execute("""
            CREATE TABLE IF NOT EXISTS report_approval_events (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                report_type TEXT NOT NULL,
                event_type TEXT NOT NULL,
                from_status TEXT,
                to_status TEXT,
                actor_label TEXT,
                detail_json TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (mission_id) REFERENCES missions(id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS report_revisions (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                report_type TEXT NOT NULL,
                revision_number INTEGER NOT NULL,
                content_html TEXT NOT NULL,
                checkpoint_kind TEXT NOT NULL,
                source_job_id TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (mission_id) REFERENCES missions(id),
                UNIQUE (mission_id, report_type, revision_number)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS report_section_definitions (
                report_type TEXT NOT NULL,
                section_key TEXT NOT NULL,
                display_title TEXT NOT NULL,
                sort_order INTEGER NOT NULL,
                policy TEXT NOT NULL DEFAULT 'editable',
                PRIMARY KEY (report_type, section_key)
            )
        """)

        for col, col_type in [
            ("suggestion_type", "TEXT"),
            ("source_job_id", "TEXT"),
            ("created_against_revision_id", "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE pending_edits ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass

        from src.section_definitions import seed_report_section_definitions

        seed_report_section_definitions(conn)

        # --- Auth & mission RBAC (planning pack waves 1–3) ---
        # users.email column stores normalized login username (legacy column name).
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mission_members (
                mission_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                affiliation TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (mission_id, user_id),
                FOREIGN KEY (mission_id) REFERENCES missions(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        try:
            conn.execute(
                "ALTER TABLE missions ADD COLUMN lifecycle_status TEXT DEFAULT 'active'"
            )
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute(
                "ALTER TABLE missions ADD COLUMN created_by_user_id TEXT REFERENCES users(id)"
            )
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute(
                "ALTER TABLE reports ADD COLUMN content_json TEXT"
            )
        except sqlite3.OperationalError:
            pass

        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                report_type TEXT,
                user_id TEXT,
                scope TEXT NOT NULL,
                section_key TEXT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (mission_id) REFERENCES missions(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mission_presence (
                mission_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                PRIMARY KEY (mission_id, user_id),
                FOREIGN KEY (mission_id) REFERENCES missions(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS auxiliary_knowledge_sources (
                id TEXT PRIMARY KEY,
                mission_id TEXT NOT NULL,
                label TEXT NOT NULL,
                path TEXT NOT NULL,
                report_types TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY (mission_id) REFERENCES missions(id)
            )
        """)

        _backfill_single_user_mel_memberships(conn)


def _backfill_single_user_mel_memberships(conn: sqlite3.Connection) -> None:
    """If exactly one user exists and missions have no members, attach MEL."""
    n_users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if n_users != 1:
        return
    row = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
    if not row:
        return
    uid = row["id"]
    mids = conn.execute(
        """
        SELECT m.id FROM missions m
        WHERE NOT EXISTS (
            SELECT 1 FROM mission_members mm WHERE mm.mission_id = m.id
        )
        """
    ).fetchall()
    now = datetime.utcnow().isoformat() + "Z"
    for r in mids:
        conn.execute(
            """
            INSERT OR IGNORE INTO mission_members (mission_id, user_id, role, affiliation, created_at)
            VALUES (?, ?, 'mel', NULL, ?)
            """,
            (r["id"], uid, now),
        )
