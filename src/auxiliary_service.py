"""MEL-managed auxiliary knowledge paths per mission (retrieval augmentation)."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from langchain_core.documents import Document

from src.db.models import get_connection, init_db
from src.ingest.loaders import load_file


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def list_auxiliary(mission_id: str) -> list[dict[str, Any]]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, mission_id, label, path, report_types, enabled, created_at
            FROM auxiliary_knowledge_sources
            WHERE mission_id = ?
            ORDER BY created_at
            """,
            (mission_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("report_types"):
            try:
                d["report_types"] = json.loads(d["report_types"])
            except (TypeError, json.JSONDecodeError):
                d["report_types"] = []
        else:
            d["report_types"] = []
        d["enabled"] = bool(d.get("enabled"))
        out.append(d)
    return out


def add_auxiliary(
    mission_id: str,
    label: str,
    path: str,
    report_types: list[str] | None = None,
    enabled: bool = True,
) -> str:
    init_db()
    p = Path(path).expanduser()
    if not p.is_file():
        raise ValueError("Auxiliary path must be an existing file")
    rid = str(uuid.uuid4())[:12]
    rt_json = json.dumps(list(report_types or []))
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO auxiliary_knowledge_sources
            (id, mission_id, label, path, report_types, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (rid, mission_id, label.strip() or p.name, str(p.resolve()), rt_json, 1 if enabled else 0, _now()),
        )
    return rid


def delete_auxiliary(mission_id: str, source_id: str) -> bool:
    init_db()
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM auxiliary_knowledge_sources WHERE mission_id = ? AND id = ?",
            (mission_id, source_id),
        )
        return cur.rowcount > 0


def load_auxiliary_documents(
    mission_id: str, report_type: Optional[str] = None
) -> list[Document]:
    """Load enabled auxiliary files as Documents for retrieval merge."""
    init_db()
    rows = list_auxiliary(mission_id)
    docs: list[Document] = []
    for row in rows:
        if not row.get("enabled"):
            continue
        allowed = row.get("report_types") or []
        if report_type and allowed and report_type not in allowed:
            continue
        p = Path(row["path"])
        if not p.is_file():
            continue
        try:
            loaded = load_file(p)
        except Exception:
            continue
        for d in loaded:
            d.metadata.setdefault("source", str(p))
            d.metadata["auxiliary"] = True
            d.metadata["aux_label"] = row.get("label") or p.name
            docs.append(d)
    return docs
