"""
Multi-query retrieval for inline assist: primary + neighbor context + placeholder hint.
"""
from __future__ import annotations

import hashlib
from typing import Any

from src.index.build import mission_index_exists
from src.retrieve.retriever import get_mission_retriever


def _doc_fingerprint(d: Any) -> str:
    src = (getattr(d, "metadata", None) or {}).get("source") or ""
    body = (getattr(d, "page_content", None) or str(d))[:500]
    h = hashlib.sha256(f"{src}\0{body}".encode("utf-8", errors="ignore")).hexdigest()[:24]
    return h


def _neighbor_queries(before_cursor: str, after_cursor: str) -> list[str]:
    out: list[str] = []
    before_lines = [ln.strip() for ln in (before_cursor or "").strip().splitlines() if ln.strip()]
    after_lines = [ln.strip() for ln in (after_cursor or "").strip().splitlines() if ln.strip()]
    if before_lines:
        tail = " ".join(before_lines[-3:])
        if len(tail) > 20:
            out.append(tail[:800])
    if after_lines:
        head = " ".join(after_lines[:3])
        if len(head) > 20:
            out.append(head[:800])
    if before_lines and after_lines:
        bridge = f"{before_lines[-1][:400]} \n {after_lines[0][:400]}"
        out.append(bridge[:800])
    return out


def _placeholder_query(before_cursor: str, after_cursor: str, selection: str) -> str | None:
    window = f"{before_cursor[-600:]}{selection}{after_cursor[:600]}"
    if "[" in window and "]" in window:
        return "mission report bracket placeholder fill from crew log findings evidence facts"
    return None


def gather_inline_assist_documents(
    mission_id: str,
    report_type: str,
    *,
    selection: str,
    before_cursor: str,
    after_cursor: str,
    k: int = 4,
    max_chunks: int = 14,
    section_key: str | None = None,
    action: str = "",
    retrieval_query_override: str | None = None,
) -> list[Any]:
    """
    Run primary + auxiliary retriever queries and return de-duplicated documents (order preserved).
    Uses report_type for retriever doc-type scoping when applicable.
    """
    if not mission_index_exists(mission_id):
        return []

    queries: list[str] = []
    if retrieval_query_override and retrieval_query_override.strip():
        primary = retrieval_query_override.strip()[:800]
    else:
        primary = (selection.strip() or before_cursor.strip() or "mission report context")[:800]
        if action == "fill_placeholder" and section_key:
            from src.templates.inline_assist_prompts import _section_display_title

            title = _section_display_title(report_type, section_key) or section_key
            primary = f"{title} mission evidence crew logs findings risks summary"
    queries.append(primary)
    queries.extend(_neighbor_queries(before_cursor, after_cursor))
    pq = _placeholder_query(before_cursor, after_cursor, selection)
    if pq:
        queries.append(pq)

    seen: set[str] = set()
    merged: list[Any] = []
    try:
        retriever = get_mission_retriever(
            mission_id=mission_id,
            k=k,
            report_type=report_type if report_type in ("rmp", "timeline", "aar", "sitrep") else None,
        )
    except Exception:
        retriever = get_mission_retriever(mission_id=mission_id, k=k, report_type=None)

    for q in queries:
        q_clean = (q or "").strip()
        if not q_clean:
            continue
        try:
            batch = list(retriever.invoke(q_clean))
        except Exception:
            continue
        # Timeline/RMP fixed-list retriever returns all chunks; one query is enough.
        if len(batch) > 20:
            batch = batch[:max_chunks]
            for d in batch:
                fp = _doc_fingerprint(d)
                if fp in seen:
                    continue
                seen.add(fp)
                merged.append(d)
            return merged
        batch = batch[:k]
        for d in batch:
            fp = _doc_fingerprint(d)
            if fp in seen:
                continue
            seen.add(fp)
            merged.append(d)
            if len(merged) >= max_chunks:
                return merged
    return merged


def assign_chunk_ids(docs: list[Any]) -> list[dict[str, str]]:
    """Stable ids for API: basename + content hash slice."""
    out: list[dict[str, str]] = []
    for idx, d in enumerate(docs):
        meta = getattr(d, "metadata", None) or {}
        src = meta.get("source") or ""
        base = src.replace("\\", "/").split("/")[-1] if src else f"chunk_{idx}"
        fp = _doc_fingerprint(d)
        out.append({"chunk_id": f"{base}#{fp[:12]}", "source": src})
    return out
