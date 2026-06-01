"""Mission/report chat: persist messages; LLM + retrieval; optional pending_edits from JSON reply."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any, Optional

from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from config.settings import OLLAMA_MODEL, get_ollama_base_url_for_report
from src.db.models import get_connection, init_db
from src.mission_service import get_mission
from src.report_service import get_report, get_pending_edits, set_pending_edits
from src.retrieve.retriever import get_mission_retriever


def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"


def append_message(
    mission_id: str,
    *,
    user_id: str | None,
    role: str,
    content: str,
    scope: str,
    report_type: str | None = None,
    section_key: str | None = None,
) -> str:
    init_db()
    mid = str(uuid.uuid4())[:12]
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO chat_messages
            (id, mission_id, report_type, user_id, scope, section_key, role, content, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mid,
                mission_id,
                report_type,
                user_id,
                scope,
                section_key,
                role,
                content,
                _now(),
            ),
        )
    return mid


def list_recent_messages(
    mission_id: str, report_type: str | None, limit: int = 30
) -> list[dict[str, Any]]:
    init_db()
    limit = max(1, min(limit, 100))
    with get_connection() as conn:
        if report_type:
            rows = conn.execute(
                """
                SELECT id, mission_id, report_type, user_id, scope, section_key, role, content, created_at
                FROM chat_messages
                WHERE mission_id = ? AND (report_type = ? OR report_type IS NULL)
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (mission_id, report_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, mission_id, report_type, user_id, scope, section_key, role, content, created_at
                FROM chat_messages
                WHERE mission_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (mission_id, limit),
            ).fetchall()
    return [dict(r) for r in reversed(rows)]


def _retrieve_context(mission_id: str, query: str, report_type: str | None) -> str:
    rt = report_type or "rmp"
    try:
        retriever = get_mission_retriever(mission_id, k=6, report_type=rt)
        docs = retriever.invoke(query)
        parts = []
        for d in docs[:12]:
            if getattr(d, "page_content", None):
                parts.append(d.page_content.strip())
        return "\n\n".join(parts)[:12000]
    except Exception:
        return ""


def run_chat_turn(
    mission_id: str,
    user_id: str,
    message: str,
    scope: str,
    report_type: str | None,
    section_key: str | None,
    *,
    apply_suggestions: bool = True,
) -> dict[str, Any]:
    """
    Stores user message, runs LLM with retrieval context.
    If model returns JSON with keys assistant_reply and pending_edits (array), pending_edits are stored (never auto-applied).
    """
    init_db()
    append_message(
        mission_id,
        user_id=user_id,
        role="user",
        content=message,
        scope=scope,
        report_type=report_type,
        section_key=section_key,
    )

    m = get_mission(mission_id)
    if not m:
        raise ValueError("Mission not found")

    context = _retrieve_context(mission_id, message, report_type)
    report_snip = ""
    if report_type:
        rep = get_report(mission_id, report_type)
        cc = (rep.get("current_content") or "")[:8000]
        report_snip = f"\n\nCurrent report HTML excerpt:\n{cc}"

    section_note = f"\nFocus section key: {section_key}\n" if section_key else ""

    prompt = f"""You are a mission writing assistant. The user message is below.
Use SOURCE CONTEXT when grounding answers. Do not invent facts not in context.
If you propose document changes, respond with ONLY a JSON object (no markdown fences) with this shape:
{{"assistant_reply": "string for the user", "pending_edits": []}}
pending_edits must be an array of objects with keys:
edit_id (unique string), section_id, target_block_id, operation (replace|insert_before|insert_after),
reason, evidence_refs (array of strings), old_html, new_html, status (always "pending"), ord (integer).
If no document edits, use "pending_edits": [].

SCOPE: {scope}. Report type (if any): {report_type or "mission-wide"}.
{section_note}
SOURCE CONTEXT:
{context}
{report_snip}

USER MESSAGE:
{message}
"""

    rt = report_type or "rmp"
    base_url = get_ollama_base_url_for_report(rt)
    llm = ChatOllama(base_url=base_url, model=OLLAMA_MODEL, temperature=0.2)
    chain = ChatPromptTemplate.from_messages([("human", "{text}")]) | llm | StrOutputParser()
    raw = chain.invoke({"text": prompt}).strip()

    reply_text = raw
    edits_applied = 0

    json_blob = raw
    m_fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if m_fence:
        json_blob = m_fence.group(1).strip()
    try:
        parsed = json.loads(json_blob)
        if isinstance(parsed, dict):
            reply_text = str(parsed.get("assistant_reply") or parsed.get("reply") or raw)
            edits = parsed.get("pending_edits")
            if (
                apply_suggestions
                and isinstance(edits, list)
                and edits
                and report_type
                and report_type in ("rmp", "timeline", "aar", "sitrep")
            ):
                all_e = get_pending_edits(mission_id, report_type)
                terminal = {"accepted", "rejected"}
                kept = [
                    e
                    for e in all_e
                    if (e.get("status") or "").lower() in terminal
                ]
                pending = [
                    e
                    for e in all_e
                    if (e.get("status") or "").lower() not in terminal
                ]
                max_ord = max((e.get("ord") or 0) for e in pending) if pending else -1
                for i, ne in enumerate(edits):
                    if not isinstance(ne, dict):
                        continue
                    ne.setdefault("status", "pending")
                    ne["ord"] = max_ord + 1 + i
                    if not ne.get("edit_id"):
                        ne["edit_id"] = f"chat_{uuid.uuid4().hex[:10]}"
                merged = kept + pending + [e for e in edits if isinstance(e, dict)]
                set_pending_edits(mission_id, report_type, merged)
                edits_applied = len([e for e in edits if isinstance(e, dict)])
    except (json.JSONDecodeError, TypeError):
        pass

    append_message(
        mission_id,
        user_id=None,
        role="assistant",
        content=reply_text,
        scope=scope,
        report_type=report_type,
        section_key=section_key,
    )

    return {
        "reply": reply_text,
        "pending_edits_staged": edits_applied,
    }
