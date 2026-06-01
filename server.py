"""
FastAPI server: Mission RAG API + SSE streaming + Liquid Glass web UI.
Serves REST API, streaming, and static web app. Run from project root:
  uvicorn server:app --host 0.0.0.0 --port 8000
"""
import asyncio
import io
import json
import logging
import re
import queue
import threading
import time
import uuid
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, HTMLResponse, FileResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parent
WEB_DIR = PROJECT_ROOT / "web"
WEB_DIST = WEB_DIR / "dist"
# Vite build output (npm run build): prefer dist so bundled Tiptap + assets load correctly.
WEB_ROOT = WEB_DIST if (WEB_DIST / "index.html").is_file() else WEB_DIR

import sys
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src import auth_service
from src import mission_member_service
from src.mission_service import (
    ensure_db,
    create_mission,
    delete_mission,
    list_missions,
    list_missions_for_user,
    list_missions_enriched,
    list_missions_for_user_enriched,
    get_mission,
    update_mission_status,
    update_mission_last_ingest,
    update_mission_last_generated,
    update_mission_metadata,
)
from src.db.models import REPORT_TYPES
from src.report_service import (
    get_report,
    set_pending,
    set_pending_edits,
    get_report_docs_used,
    set_report_docs_used,
    accept_pending,
    reject_pending,
    save_user_edit,
    get_pending_edits,
    accept_edit,
    reject_edit,
    accept_all_edits,
    reject_all_edits,
    apply_accepted_edits,
    get_report_preview,
    reset_report_to_template,
)
from src.activity_service import mission_activity_feed
from src import chat_service
from src import presence_service
from src import auxiliary_service
from src.documents_registry import list_mission_documents
from src.pdf_export import html_to_pdf_bytes
from src import admin_debug_service
from src.merge_draft import merge_llm_into_draft
from src.index.build import build_mission_index, mission_index_exists
from src.retrieve.retriever import get_mission_retriever, get_new_docs_context_for_report
from src.agents.base import run_template_rag_agent, run_template_rag_agent_stream
from config.settings import get_ollama_base_url_for_report
from src.templates.prompts import (
    RMP_TEMPLATE_QUERY,
    TIMELINE_TEMPLATE_QUERY,
    RMP_GENERATION_PROMPT,
    TIMELINE_GENERATION_PROMPT,
    RMP_STRUCTURED_EDIT_PROMPT,
    TIMELINE_STRUCTURED_EDIT_PROMPT,
    AAR_TEMPLATE_QUERY,
    AAR_GENERATION_PROMPT,
    AAR_STRUCTURED_EDIT_PROMPT,
    SITREP_TEMPLATE_QUERY,
    SITREP_GENERATION_PROMPT,
    SITREP_STRUCTURED_EDIT_PROMPT,
)
from src.document_blocks import parse_html_to_blocks
from src.utils.context_cleaner import clean_context_for_llm
from src.revision_service import get_report_revision, list_report_revisions
from src.section_definitions import list_section_definitions_for_report_type
from src.grounded_update.policy import STRUCTURED_EDIT_GROUNDING_PREFIX
from src.grounded_update.pipeline_gap_hints import build_structured_edit_gap_hints
from src.inline_assist_service import run_inline_assist
from src.report_review_service import (
    add_comment,
    delete_comment,
    finalize_report_export,
    get_review_status,
    is_ai_update_locked,
    is_content_locked,
    list_approval_events,
    list_comments,
    transition_review_status,
)
from src.ingest.manifest import new_or_changed_files
from src.edit_dedupe import filter_near_duplicate_edits
from src.sections import sections_to_update
from src.evidence_checkpoint import evidence_delta_for_mission
from src.pipeline_job_service import (
    ALLOWED_UPDATE_INTENTS,
    add_pipeline_job_invalid_edits,
    append_pipeline_job_event,
    complete_pipeline_job,
    create_pipeline_job,
    fail_pipeline_job,
    get_pipeline_job,
    list_pipeline_jobs,
    mark_pipeline_job_fallback_used,
    mark_pipeline_job_running,
    resolve_update_intent_for_job,
)
from langchain_community.chat_models import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from config.settings import OLLAMA_MODEL

app = FastAPI(title="Mission RAG")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_AUTH_EXEMPT = frozenset(
    {"/api/auth/login", "/api/auth/logout", "/api/auth/bootstrap"}
)


class SessionAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)
        if path in _AUTH_EXEMPT:
            return await call_next(request)
        token = request.cookies.get("session")
        user = auth_service.get_user_by_session_token(token or "")
        if not user:
            return JSONResponse(
                status_code=401, content={"detail": "Not authenticated"}
            )
        request.state.user = user
        return await call_next(request)


app.add_middleware(SessionAuthMiddleware)

REPORT_SPECS = [
    ("rmp", RMP_TEMPLATE_QUERY, RMP_GENERATION_PROMPT),
    ("timeline", TIMELINE_TEMPLATE_QUERY, TIMELINE_GENERATION_PROMPT),
    ("aar", AAR_TEMPLATE_QUERY, AAR_GENERATION_PROMPT),
    ("sitrep", SITREP_TEMPLATE_QUERY, SITREP_GENERATION_PROMPT),
]

# Draft dependencies: report_type -> list of report types it depends on (run order + content injection).
REPORT_DEPENDENCIES: dict[str, list[str]] = {
    "rmp": ["timeline"],
    "timeline": [],
    "aar": [],
    "sitrep": [],
}


def _report_run_order(report_types: list[str]) -> list[str]:
    """Topological order so dependencies run before dependents."""
    order: list[str] = []
    seen: set[str] = set()

    def visit(rt: str) -> None:
        if rt in seen or rt not in REPORT_TYPES:
            return
        seen.add(rt)
        for dep in REPORT_DEPENDENCIES.get(rt, []):
            visit(dep)
        order.append(rt)

    for rt in report_types:
        visit(rt)
    return order


# All report types use structured edit proposals (collaborative editor).
USE_STRUCTURED_EDITS_FOR = {"rmp", "timeline", "aar", "sitrep"}

STRUCTURED_EDIT_SPECS = {
    "rmp": (RMP_TEMPLATE_QUERY, RMP_STRUCTURED_EDIT_PROMPT),
    "timeline": (TIMELINE_TEMPLATE_QUERY, TIMELINE_STRUCTURED_EDIT_PROMPT),
    "aar": (AAR_TEMPLATE_QUERY, AAR_STRUCTURED_EDIT_PROMPT),
    "sitrep": (SITREP_TEMPLATE_QUERY, SITREP_STRUCTURED_EDIT_PROMPT),
}


def _failure_kind_from_pipeline_error(error_msg: str, *, outer_exception: bool) -> str:
    if outer_exception:
        return "pipeline_error"
    el = error_msg.lower()
    if "json" in el or "parse" in el or "invalid" in el:
        return "parse_error"
    return "llm_error"


def _run_structured_edits(
    mission_id: str,
    report_type: str,
    shared_q: queue.Queue,
    base_url: str,
    job_id: str | None = None,
    update_intent: str | None = None,
) -> None:
    """
    Run update for one report type by retrieving context, prompting for JSON edits only, parsing and validating.
    Uses incremental context when last_used_doc_paths is set (only new/changed docs); otherwise full context.
    Puts (report_type, "edits", list_of_edits) on shared_q when done; or ("error", report_type, str) on failure.
    """
    try:
        from src.retrieve.retriever import get_mission_retriever

        spec = STRUCTURED_EDIT_SPECS.get(report_type)
        if not spec:
            shared_q.put(("error", report_type, f"Unknown report type: {report_type}"))
            return
        template_query, edit_prompt = spec
        report = get_report(mission_id, report_type)
        mission_row = get_mission(mission_id)
        last_used = get_report_docs_used(mission_id, report_type)
        if update_intent in ("full_refresh", "generate_first_draft"):
            last_used = None
        paths_used: list[str] = []
        raw_context: str
        retriever = None
        used_new_only = False

        t_retrieve_start = time.monotonic()
        if not last_used:
            # No baseline (e.g. after Reset or first run): use full retriever
            retriever = get_mission_retriever(mission_id=mission_id, report_type=report_type)
            docs = retriever.invoke(template_query)
            raw_context = "\n\n---\n\n".join(d.page_content for d in docs)
            paths_used = list({str(d.metadata.get("source")) for d in docs if d.metadata.get("source")})
        else:
            # Baseline exists: try new-or-changed docs only
            source_path = (mission_row or {}).get("source_path")
            if source_path:
                new_result = get_new_docs_context_for_report(mission_id, report_type, Path(source_path))
                if new_result:
                    raw_context, paths_new = new_result
                    paths_used = list(set(last_used) | set(paths_new))
                    used_new_only = True
                else:
                    retriever = get_mission_retriever(mission_id=mission_id, report_type=report_type)
                    docs = retriever.invoke(template_query)
                    raw_context = "\n\n---\n\n".join(d.page_content for d in docs)
                    paths_used = list({str(d.metadata.get("source")) for d in docs if d.metadata.get("source")})
            else:
                retriever = get_mission_retriever(mission_id=mission_id, report_type=report_type)
                docs = retriever.invoke(template_query)
                raw_context = "\n\n---\n\n".join(d.page_content for d in docs)
                paths_used = list({str(d.metadata.get("source")) for d in docs if d.metadata.get("source")})

        if job_id:
            append_pipeline_job_event(
                job_id,
                "retrieval_done",
                {
                    "report_type": report_type,
                    "ms": round((time.monotonic() - t_retrieve_start) * 1000),
                    "incremental_only": used_new_only,
                },
            )

        dirty_for_sections: list = []
        if mission_row and mission_row.get("source_path"):
            try:
                sp = Path(mission_row["source_path"])
                if sp.is_dir():
                    dirty_for_sections = new_or_changed_files(mission_id, sp)
            except Exception:
                pass
        section_pairs = sections_to_update(mission_id, dirty_for_sections)
        if job_id:
            append_pipeline_job_event(
                job_id,
                "coverage_scope",
                {
                    "report_type": report_type,
                    "new_changed_file_count": len(dirty_for_sections),
                    "sections_likely_dirty": [
                        {"report_type": rt, "section_key": sk} for rt, sk in section_pairs
                    ],
                },
            )

        context = clean_context_for_llm(raw_context)
        current_html = (report.get("current_content") or "").strip() or ""
        blocks = parse_html_to_blocks(current_html or "")
        block_ids = [b.block_id for b in blocks]
        if not block_ids:
            block_ids = ["section_0_block_0"]
        block_ids_str = ", ".join(block_ids)
        context_note = "Note: The following is new or changed material only; integrate it into the document.\n\n" if used_new_only else ""
        t_prompt0 = time.monotonic()
        gap_hints = build_structured_edit_gap_hints(current_html)
        grounding_block = STRUCTURED_EDIT_GROUNDING_PREFIX.strip()
        if gap_hints:
            grounding_block = grounding_block + "\n\n" + gap_hints
        prompt_text = grounding_block + "\n\n" + edit_prompt.format(
            current_document=current_html or "<p>Empty document.</p>",
            block_ids=block_ids_str,
            context_note=context_note,
            context=context or "(No source material)",
        )
        if job_id:
            append_pipeline_job_event(
                job_id,
                "prompt_assembly_done",
                {
                    "report_type": report_type,
                    "ms": round((time.monotonic() - t_prompt0) * 1000),
                },
            )
        llm = ChatOllama(base_url=base_url, model=OLLAMA_MODEL, temperature=0.2)
        chain = ChatPromptTemplate.from_messages([("human", prompt_text)]) | llm | StrOutputParser()
        t_gen_start = time.monotonic()
        response = chain.invoke({})
        if job_id:
            append_pipeline_job_event(
                job_id,
                "generation_done",
                {
                    "report_type": report_type,
                    "phase": "structured_edits",
                    "ms": round((time.monotonic() - t_gen_start) * 1000),
                },
            )
        raw = (response or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```\s*$", "", raw)
        t_parse0 = time.monotonic()
        parse_failed = False
        if not raw:
            edits_raw = []
        else:
            try:
                edits_raw = json.loads(raw)
            except json.JSONDecodeError as e:
                parse_failed = True
                logger.warning("Structured edits LLM returned invalid JSON mission_id=%s report_type=%s: %s", mission_id, report_type, e)
                if job_id:
                    append_pipeline_job_event(
                        job_id,
                        "structured_edits_parse_failed",
                        {"report_type": report_type, "detail": str(e)[:500]},
                    )
                edits_raw = []
        if not isinstance(edits_raw, list):
            edits_raw = [edits_raw]
        valid_ids = set(block_ids)
        edits: list[dict] = []
        invalid_target_count = 0
        for i, e in enumerate(edits_raw):
            if not isinstance(e, dict):
                continue
            tid = e.get("target_block_id")
            if tid and tid not in valid_ids:
                invalid_target_count += 1
                continue
            edit_id = e.get("edit_id") or str(uuid.uuid4())[:8]
            edits.append({
                "edit_id": edit_id,
                "section_id": e.get("section_id"),
                "target_block_id": tid or block_ids[-1] if block_ids else "section_0_block_0",
                "operation": (e.get("operation") or "replace").lower(),
                "reason": e.get("reason"),
                "evidence_refs": e.get("evidence") or e.get("evidence_refs") or [],
                "old_html": e.get("old_html"),
                "new_html": e.get("new_html"),
                "status": "pending",
                "ord": i,
            })
        edits, dup_suppressed = filter_near_duplicate_edits(edits)
        if job_id and dup_suppressed:
            append_pipeline_job_event(
                job_id,
                "duplicate_edits_suppressed",
                {"report_type": report_type, "count": dup_suppressed},
            )
        if job_id:
            append_pipeline_job_event(
                job_id,
                "parse_validate_done",
                {
                    "report_type": report_type,
                    "ms": round((time.monotonic() - t_parse0) * 1000),
                    "invalid_target_count": invalid_target_count,
                    "accepted_edit_count": len(edits),
                    "parse_failed": parse_failed,
                    "duplicate_edits_suppressed": dup_suppressed,
                },
            )
        if job_id and invalid_target_count:
            add_pipeline_job_invalid_edits(job_id, invalid_target_count)
        # When no valid structured edits (e.g. LLM returned empty/invalid JSON), fall back to full-draft RAG so the user sees new content.
        if len(edits) == 0:
            gen_spec = next((s for rt, *s in REPORT_SPECS if rt == report_type), None)
            if gen_spec:
                template_query_fb, gen_prompt = gen_spec[0], gen_spec[1]
                if retriever is None:
                    retriever = get_mission_retriever(mission_id=mission_id, report_type=report_type)
                try:
                    content, sources = run_template_rag_agent(
                        mission_id, template_query_fb, gen_prompt, retriever=retriever, base_url=base_url
                    )
                    merged = merge_llm_into_draft(current_html or "", content or "")
                    if merged.strip():
                        set_pending(mission_id, report_type, merged, sources)
                        logger.info("Structured edits fallback: set_pending full draft mission_id=%s report_type=%s", mission_id, report_type)
                        # paths_used for fallback = full retriever docs
                        docs_fb = retriever.invoke(template_query_fb)
                        paths_used = list({str(d.metadata.get("source")) for d in docs_fb if d.metadata.get("source")})
                        # One synthetic pending edit so the UI shows the proposed-changes panel and highlighted preview.
                        first_block = block_ids[0] if block_ids else "section_0_block_0"
                        logger.info("Structured edits fallback: adding synthetic pending edit mission_id=%s report_type=%s", mission_id, report_type)
                        edits = [{
                            "edit_id": "fallback-1",
                            "section_id": None,
                            "target_block_id": first_block,
                            "operation": "replace",
                            "reason": "Full draft update",
                            "evidence_refs": [],
                            "old_html": current_html or "",
                            "new_html": merged,
                            "status": "pending",
                            "ord": 0,
                            "suggestion_type": "full_document_replace",
                            **({"source_job_id": job_id} if job_id else {}),
                        }]
                        if job_id:
                            mark_pipeline_job_fallback_used(job_id)
                            append_pipeline_job_event(
                                job_id, "structured_edits_fallback", {"report_type": report_type}
                            )
                except Exception as fallback_e:
                    logger.warning("Structured edits fallback failed mission_id=%s report_type=%s: %s", mission_id, report_type, fallback_e)
        basename_refs = [Path(p).name for p in paths_used if p][:8]
        for e in edits:
            if not e.get("evidence_refs"):
                e["evidence_refs"] = list(basename_refs)
        if paths_used:
            set_report_docs_used(mission_id, report_type, paths_used)
        if job_id:
            append_pipeline_job_event(
                job_id,
                "structured_edits_queued",
                {"report_type": report_type, "edit_count": len(edits)},
            )
        shared_q.put((report_type, "edits", edits))
    except Exception as e:
        logger.exception("Structured edits failed mission_id=%s report_type=%s", mission_id, report_type)
        shared_q.put(("error", report_type, str(e)))


def _filter_pipeline_report_types(
    mission_id: str, report_types: list[str] | None
) -> tuple[list[str], str | None]:
    """Omit MEL-approved/final reports from AI pipeline runs. Returns (allowed_types, error_if_none)."""
    want = list(report_types) if report_types else list(REPORT_TYPES)
    valid = [rt for rt in want if rt in REPORT_TYPES]
    allowed = [rt for rt in valid if not is_ai_update_locked(mission_id, rt)]
    blocked = [rt for rt in valid if is_ai_update_locked(mission_id, rt)]
    if not allowed:
        msg = "No reports can run AI update (all requested are MEL-approved or final)."
        if blocked:
            msg += f" Blocked: {', '.join(blocked)}."
        return [], msg
    if blocked:
        logger.info("mission_id=%s skipping AI-locked reports %s", mission_id, blocked)
    return allowed, None


def request_mission_update(
    mission_id: str,
    report_types: list[str] | None = None,
    update_intent: str | None = None,
) -> tuple[bool, str | None, str | None]:
    """
    Main orchestrator entry point: request an update for a mission (all or specific report types).
    Returns (ok, error_message, job_id). job_id is set only when ok is True.
    """
    mission = get_mission(mission_id)
    if not mission:
        return False, "Mission not found", None
    allowed_rts, filter_err = _filter_pipeline_report_types(mission_id, report_types)
    if filter_err:
        return False, filter_err, None
    intent_opt = update_intent if update_intent in ALLOWED_UPDATE_INTENTS else None
    resolved_intent = resolve_update_intent_for_job(allowed_rts, intent_opt)
    logger.info(
        "update requested mission_id=%s report_types=%s update_intent=%s",
        mission_id,
        allowed_rts,
        resolved_intent,
    )
    source_path = Path(mission["source_path"])
    if not source_path.is_dir():
        return False, "Source path is not a directory", None
    job_id = create_pipeline_job(mission_id, allowed_rts, update_intent=intent_opt)
    with app.state.stream_lock:
        app.state.running_mission_id = mission_id
    threading.Thread(
        target=_run_pipeline,
        args=(mission_id, source_path),
        kwargs={
            "report_types": allowed_rts,
            "job_id": job_id,
            "update_intent": resolved_intent,
        },
        daemon=True,
    ).start()
    return True, None, job_id


def _run_pipeline(
    mission_id: str,
    source_path: Path,
    report_types: list[str] | None = None,
    job_id: str | None = None,
    update_intent: str | None = None,
) -> None:
    """Background thread: ingest, generate report(s). If report_types is None, run all; else only those. Respects dependencies (run order + content injection)."""
    run_types = report_types if report_types else [rt for rt, _, _ in REPORT_SPECS]
    run_types = [r for r in run_types if r in REPORT_TYPES]
    run_types = _report_run_order(run_types)
    if not run_types:
        logger.warning("pipeline aborted: no valid report types mission_id=%s", mission_id)
        if job_id:
            fail_pipeline_job(
                job_id,
                "No valid report types to run",
                failure_kind="pipeline_error",
            )
        with app.state.stream_lock:
            app.state.running_mission_id = None
        return

    logger.info("pipeline start mission_id=%s report_types=%s", mission_id, run_types)
    m = get_mission(mission_id)
    canonical_id = m["id"] if m else mission_id
    state = app.state
    loop = state.loop
    buffers = state.stream_buffers
    queues = state.stream_queues
    lock = state.stream_lock

    with lock:
        for rt in run_types:
            key = (canonical_id, rt)
            if key in buffers:
                del buffers[key]

    def push(report_type: str, chunk: str | None, full_content: str | None) -> None:
        key = (canonical_id, report_type)
        with lock:
            if full_content is not None:
                buffers[key] = full_content
            qs = list(queues.get(key, []))

        def put():
            for q in qs:
                try:
                    q.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass
        if qs:
            loop.call_soon_threadsafe(put)

    spec_map = {rt: (tq, gp) for rt, tq, gp in REPORT_SPECS}

    if job_id:
        mark_pipeline_job_running(job_id)
        append_pipeline_job_event(
            job_id, "pipeline_started", {"run_types": run_types, "mission_id": mission_id}
        )

    try:
        mission = get_mission(mission_id)
        cpt = mission.get("cpt") if mission else None
        if job_id:
            append_pipeline_job_event(job_id, "index_check", {})
        if not mission_index_exists(mission_id):
            if job_id:
                append_pipeline_job_event(job_id, "index_build_start", {})
            t_idx = time.monotonic()
            build_mission_index(mission_id=mission_id, source_path=source_path, cpt=cpt)
            update_mission_last_ingest(mission_id)
            if job_id:
                append_pipeline_job_event(
                    job_id,
                    "index_build_done",
                    {"ms": round((time.monotonic() - t_idx) * 1000)},
                )
        else:
            logger.info("mission_id=%s index exists, skipping rebuild", mission_id)
            if job_id:
                append_pipeline_job_event(job_id, "index_skipped", {"reason": "mission_index_exists"})
        shared_q = queue.Queue()

        def run_stream(
            report_type: str,
            template_query: str,
            gen_prompt: str,
            base_url: str,
            retriever,
            dep_sections: dict[str, str] | None = None,
            current_draft: str | None = None,
        ) -> None:
            logger.info("stream start mission_id=%s report_type=%s", mission_id, report_type)
            t_stream = time.monotonic()
            try:
                for kind, data in run_template_rag_agent_stream(
                    mission_id,
                    template_query,
                    gen_prompt,
                    retriever=retriever,
                    base_url=base_url,
                    dependency_sections=dep_sections,
                    current_draft=current_draft,
                ):
                    if job_id and kind == "sources":
                        append_pipeline_job_event(
                            job_id,
                            "stream_generation_done",
                            {
                                "report_type": report_type,
                                "ms": round((time.monotonic() - t_stream) * 1000),
                            },
                        )
                    shared_q.put((report_type, kind, data))
                logger.info("stream finished mission_id=%s report_type=%s", mission_id, report_type)
            except Exception as e:
                logger.warning("stream error mission_id=%s report_type=%s error=%s", mission_id, report_type, e)
                shared_q.put(("error", report_type, str(e)))

        for rt in run_types:
            if rt not in spec_map:
                continue
            if rt in USE_STRUCTURED_EDITS_FOR:
                threading.Thread(
                    target=_run_structured_edits,
                    args=(
                        mission_id,
                        rt,
                        shared_q,
                        get_ollama_base_url_for_report(rt),
                        job_id,
                        update_intent,
                    ),
                    daemon=True,
                ).start()
                continue
            deps = REPORT_DEPENDENCIES.get(rt, [])
            dep_sections = {}
            for d in deps:
                r = get_report(mission_id, d)
                if r.get("current_content"):
                    dep_sections[d] = r["current_content"]
            existing = get_report(mission_id, rt)
            current_draft = (existing.get("current_content") or "").strip() or None
            tq, gp = spec_map[rt]
            retriever = get_mission_retriever(mission_id=mission_id, report_type=rt)
            threading.Thread(
                target=run_stream,
                args=(rt, tq, gp, get_ollama_base_url_for_report(rt), retriever),
                kwargs={"dep_sections": dep_sections or None, "current_draft": current_draft},
                daemon=True,
            ).start()

        full = {rt: "" for rt in run_types}
        done = {rt: False for rt in run_types}
        chunk_count = {rt: 0 for rt in run_types}
        error_msg = None
        while not all(done.values()) and error_msg is None:
            try:
                report_type, kind, data = shared_q.get(timeout=0.05)
            except queue.Empty:
                continue
            if kind == "error":
                error_msg = f"{report_type}: {data}"
                logger.warning("pipeline error mission_id=%s report_type=%s error=%s", mission_id, report_type, data)
                break
            if kind == "edits":
                t_persist = time.monotonic()
                set_pending_edits(
                    mission_id,
                    report_type,
                    data,
                    source_job_id=job_id,
                )
                if job_id:
                    append_pipeline_job_event(
                        job_id,
                        "persist_pending_edits_done",
                        {
                            "report_type": report_type,
                            "ms": round((time.monotonic() - t_persist) * 1000),
                            "edit_count": len(data),
                        },
                    )
                done[report_type] = True
                if job_id:
                    append_pipeline_job_event(
                        job_id,
                        "report_completed",
                        {"report_type": report_type, "kind": "structured_edits", "edit_count": len(data)},
                    )
                if all(done.values()):
                    update_mission_last_generated(mission_id)
                push(report_type, None, None)
                continue
            if kind == "chunk":
                full[report_type] += data
                chunk_count[report_type] += 1
                if chunk_count[report_type] % 100 == 1:
                    logger.debug("chunks mission_id=%s report_type=%s count=%s", mission_id, report_type, chunk_count[report_type])
                display = re.sub(r"\n{3,}", "\n\n", full[report_type])
                push(report_type, data, display)
            elif kind == "sources" and report_type in REPORT_TYPES:
                logger.info("report done mission_id=%s report_type=%s", mission_id, report_type)
                existing = get_report(mission_id, report_type)
                current_draft = (existing.get("current_content") or "").strip() or ""
                merged_content = merge_llm_into_draft(current_draft, full[report_type])
                t_persist = time.monotonic()
                set_pending(mission_id, report_type, merged_content, sources=data)
                if job_id:
                    append_pipeline_job_event(
                        job_id,
                        "persist_pending_content_done",
                        {
                            "report_type": report_type,
                            "ms": round((time.monotonic() - t_persist) * 1000),
                        },
                    )
                done[report_type] = True
                if job_id:
                    append_pipeline_job_event(
                        job_id,
                        "report_completed",
                        {"report_type": report_type, "kind": "stream_pending"},
                    )
                if all(done.values()):
                    update_mission_last_generated(mission_id)
                push(report_type, None, full[report_type])
            else:
                logger.warning("pipeline unexpected message mission_id=%s kind=%s report_type=%s", mission_id, kind, report_type)

        logger.info("pipeline loop exit mission_id=%s all_done=%s error=%s", mission_id, all(done.values()), error_msg)
        for rt in run_types:
            push(rt, None, None)
        logger.info("pipeline cleanup mission_id=%s", mission_id)
        if job_id:
            if error_msg:
                fail_pipeline_job(
                    job_id,
                    error_msg,
                    failure_kind=_failure_kind_from_pipeline_error(
                        error_msg, outer_exception=False
                    ),
                )
            else:
                append_pipeline_job_event(
                    job_id, "pipeline_completed", {"run_types": run_types}
                )
                complete_pipeline_job(job_id)
        with lock:
            state.running_mission_id = None
    except Exception as e:
        logger.exception("pipeline exception mission_id=%s", mission_id)
        if job_id:
            fail_pipeline_job(
                job_id,
                str(e),
                failure_kind=_failure_kind_from_pipeline_error(
                    str(e), outer_exception=True
                ),
            )
        with lock:
            state.running_mission_id = None
        for rt in run_types:
            push(rt, None, None)


@app.on_event("startup")
def startup():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    ensure_db()
    app.state.loop = asyncio.get_event_loop()
    app.state.stream_buffers = {}
    app.state.stream_queues = {}
    app.state.stream_lock = threading.Lock()
    app.state.running_mission_id = None


# ---------- REST API ----------


class LoginBody(BaseModel):
    username: str
    password: str


class RegisterBody(BaseModel):
    username: str
    password: str
    display_name: str | None = None


class AdminCreateUserBody(BaseModel):
    username: str
    password: str
    display_name: str | None = None


class CreateMissionBody(BaseModel):
    name: str
    source_path: str
    output_path: str
    cpt: str | None = None
    workflow_title: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    operators: list[dict[str, str]] | None = None  # [{name, role: Host|Network}]
    mel: str | None = None
    mel_username: str | None = None  # login id for designated MEL (firstname.lastname); must match form pill
    ccl_host: list[str] | str | None = None
    ccl_network: list[str] | str | None = None
    auto_update_frequency: str | None = None  # off | hourly | 6h | daily


class UpdateStatusBody(BaseModel):
    status: str


class UpdateMissionMetadataBody(BaseModel):
    workflow_title: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    operators: list[dict[str, str]] | None = None
    mel: str | None = None
    ccl_host: list[str] | str | None = None
    ccl_network: list[str] | str | None = None
    auto_update_frequency: str | None = None
    ingest_mode: str | None = None  # auto | manual (Phase 1; pipeline still auto-ingests until confirm UX)
    lifecycle_status: str | None = None  # active | archived


class SaveReportBody(BaseModel):
    content: str
    margins: dict[str, float] | None = None  # top, right, bottom, left in inches
    content_json: str | None = None  # optional ProseMirror JSON string (dual-write)


class ChatBody(BaseModel):
    scope: str  # report | section | mission
    message: str
    section_key: str | None = None


class MissionChatBody(BaseModel):
    message: str


class AddMissionMemberBody(BaseModel):
    username: str
    role: str
    affiliation: str | None = None


class AuxiliarySourceBody(BaseModel):
    label: str
    path: str
    report_types: list[str] | None = None
    enabled: bool = True


class ExportPdfBody(BaseModel):
    use_preview: bool = False


class InlineAssistBody(BaseModel):
    """Phase 3: scoped editor assist; response is staged in the UI until the user accepts."""

    action: str
    selection: str = ""
    before_cursor: str = ""
    after_cursor: str = ""
    current_draft_html: str | None = None


class ReviewStatusBody(BaseModel):
    status: str
    actor_label: str | None = None
    transition_comment: str | None = None


class ReportCommentBody(BaseModel):
    body: str
    parent_id: str | None = None
    anchor_section_key: str | None = None
    """JSON-serializable anchor: from, to, sectionKey, quote (PM positions + metadata)."""
    anchor_json: dict | str | None = None
    author_label: str | None = None


class FinalizeReportBody(BaseModel):
    actor_label: str | None = None
    current_revision_id: str | None = None


def _require_content_unlocked(mission_id: str, report_type: str) -> None:
    if is_content_locked(mission_id, report_type):
        raise HTTPException(
            status_code=409,
            detail="Report is final. Reopen (change review status to draft) before editing.",
        )


def _require_ai_unlocked(mission_id: str, report_type: str) -> None:
    if is_ai_update_locked(mission_id, report_type):
        raise HTTPException(
            status_code=409,
            detail="Report is MEL-approved or final; AI update and inline assist are disabled.",
        )


def _uid(request: Request) -> str:
    u = getattr(request.state, "user", None)
    if not u:
        raise HTTPException(401, "Not authenticated")
    return u["id"]


def _require_mel_or_admin(request: Request, mission_id: str) -> None:
    u = getattr(request.state, "user", None) or {}
    if u.get("is_admin"):
        return
    mission_member_service.require_mel(_uid(request), mission_id)


def _require_auth(request: Request) -> None:
    _uid(request)


def _mission404(mission_id: str) -> dict:
    m = get_mission(mission_id)
    if not m:
        raise HTTPException(404, "Mission not found")
    return m


def _require_report_type(report_type: str) -> None:
    if report_type not in REPORT_TYPES:
        raise HTTPException(400, f"report_type must be one of {REPORT_TYPES}")


def _report_read(request: Request, mission_id: str, report_type: str) -> dict:
    _require_report_type(report_type)
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.assert_can_read_reports(_uid(request), mission_id)
    return m


def _report_edit(request: Request, mission_id: str, report_type: str) -> dict:
    m = _report_read(request, mission_id, report_type)
    mission_member_service.assert_can_edit_report(_uid(request), mission_id)
    return m


def _report_ai(request: Request, mission_id: str, report_type: str) -> dict:
    m = _report_read(request, mission_id, report_type)
    mission_member_service.assert_can_run_ai(_uid(request), mission_id)
    return m


@app.post("/api/auth/login")
def auth_login(body: LoginBody, response: Response):
    user = auth_service.verify_login(body.username, body.password)
    if not user:
        raise HTTPException(401, "Invalid username or password")
    token, _exp = auth_service.create_session(user["id"])
    response.set_cookie(
        key="session",
        value=token,
        httponly=True,
        samesite="lax",
        max_age=14 * 24 * 3600,
        path="/",
    )
    uid = user["id"]
    return {
        "ok": True,
        "user": {
            "id": uid,
            "username": user["username"],
            "display_name": user["display_name"],
            "is_admin": bool(user.get("is_admin")),
            "has_mel_role": mission_member_service.user_has_mel_role(uid),
        },
    }


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    auth_service.delete_session_by_token(request.cookies.get("session") or "")
    response.delete_cookie("session", path="/")
    return {"ok": True}


@app.post("/api/auth/bootstrap")
def auth_bootstrap(body: RegisterBody):
    """First user only (no session). Creates admin account."""
    if auth_service.count_users() != 0:
        raise HTTPException(403, "Bootstrap is only allowed when no users exist.")
    try:
        uid = auth_service.create_user(
            body.username,
            body.password,
            display_name=body.display_name,
            is_admin=True,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "id": uid}


@app.post("/api/auth/register")
def auth_register(request: Request, body: RegisterBody):
    u = getattr(request.state, "user", None)
    if not u or not u.get("is_admin"):
        raise HTTPException(403, "Only administrators can create users.")
    try:
        uid = auth_service.create_user(
            body.username, body.password, display_name=body.display_name, is_admin=False
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "id": uid}


@app.post("/api/auth/users")
def auth_admin_create_user(request: Request, body: AdminCreateUserBody):
    u = getattr(request.state, "user", None)
    if not u or not u.get("is_admin"):
        raise HTTPException(403, "Only administrators can create users.")
    try:
        uid = auth_service.create_user(
            body.username, body.password, display_name=body.display_name, is_admin=False
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "id": uid}


@app.get("/api/auth/me")
def auth_me(request: Request):
    u = getattr(request.state, "user", None)
    if not u:
        raise HTTPException(401, "Not authenticated")
    uid = u["id"]
    return {
        "id": uid,
        "username": u["username"],
        "display_name": u["display_name"],
        "is_admin": bool(u.get("is_admin")),
        "has_mel_role": mission_member_service.user_has_mel_role(uid),
    }


@app.get("/api/missions")
def api_list_missions(request: Request):
    actor = getattr(request.state, "user", None) or {}
    if actor.get("is_admin"):
        return list_missions_enriched()
    return list_missions_for_user_enriched(_uid(request))


@app.get("/api/missions/{mission_id}")
def api_get_mission(request: Request, mission_id: str):
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.assert_can_read_reports(_uid(request), mission_id)
    return m


@app.get("/api/missions/{mission_id}/evidence-delta")
def api_mission_evidence_delta(request: Request, mission_id: str):
    """Phase 4: read-only summary of new/changed source files vs last user checkpoint and vs index manifest."""
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.assert_can_read_reports(_uid(request), mission_id)
    sp = Path(m["source_path"])
    if not sp.is_dir():
        raise HTTPException(400, "Mission source path is not a directory")
    return evidence_delta_for_mission(mission_id, sp)


@app.post("/api/missions")
def api_create_mission(request: Request, body: CreateMissionBody):
    uid = _uid(request)
    try:
        mid = create_mission(
            body.name,
            body.source_path,
            body.output_path,
            cpt=body.cpt,
            workflow_title=body.workflow_title,
            start_date=body.start_date,
            end_date=body.end_date,
            operators=body.operators,
            mel=body.mel,
            ccl_host=body.ccl_host,
            ccl_network=body.ccl_network,
            auto_update_frequency=body.auto_update_frequency,
            created_by_user_id=uid,
        )
        mission_member_service.provision_mission_team_users(
            body.operators,
            body.ccl_host,
            body.ccl_network,
            mel_login=body.mel_username,
            mel_display=body.mel,
        )
        mission_member_service.sync_roster_from_mission_payload(
            mid, body.operators, body.ccl_host, body.ccl_network
        )
        mission_member_service.apply_designated_mel_after_create(
            mid, body.mel_username, uid
        )
        return {"id": mid, "name": body.name}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.delete("/api/missions/{mission_id}")
def api_delete_mission(request: Request, mission_id: str):
    _mission404(mission_id)
    _require_mel_or_admin(request, mission_id)
    try:
        delete_mission(mission_id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, str(e))


@app.patch("/api/missions/{mission_id}")
def api_update_mission_status(request: Request, mission_id: str, body: UpdateStatusBody):
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.require_mel(_uid(request), mission_id)
    try:
        update_mission_status(mission_id, body.status)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.patch("/api/missions/{mission_id}/metadata")
def api_update_mission_metadata(request: Request, mission_id: str, body: UpdateMissionMetadataBody):
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    _require_mel_or_admin(request, mission_id)
    try:
        update_mission_metadata(
            mission_id,
            workflow_title=body.workflow_title,
            start_date=body.start_date,
            end_date=body.end_date,
            operators=body.operators,
            mel=body.mel,
            ccl_host=body.ccl_host,
            ccl_network=body.ccl_network,
            auto_update_frequency=body.auto_update_frequency,
            ingest_mode=body.ingest_mode,
            lifecycle_status=body.lifecycle_status,
        )
        mission_member_service.provision_mission_team_users(
            body.operators, body.ccl_host, body.ccl_network
        )
        mission_member_service.sync_roster_from_mission_payload(
            mission_id, body.operators, body.ccl_host, body.ccl_network
        )
        return {"ok": True}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/api/missions/{mission_id}/members")
def api_list_mission_members(request: Request, mission_id: str):
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.assert_can_read_reports(_uid(request), mission_id)
    return {"members": mission_member_service.list_members(mission_id)}


@app.get("/api/missions/{mission_id}/reports/{report_type}")
def api_get_report(request: Request, mission_id: str, report_type: str):
    _report_read(request, mission_id, report_type)
    return get_report(mission_id, report_type)


@app.patch("/api/missions/{mission_id}/reports/{report_type}/review-status")
def api_patch_review_status(
    request: Request, mission_id: str, report_type: str, body: ReviewStatusBody
):
    _report_read(request, mission_id, report_type)
    uid = _uid(request)
    cur = get_review_status(mission_id, report_type)
    mission_member_service.assert_review_transition_allowed(
        uid, mission_id, cur, body.status.strip()
    )
    u = getattr(request.state, "user", {})
    actor = body.actor_label or u.get("display_name") or u.get("username")
    try:
        new = transition_review_status(
            mission_id,
            report_type,
            body.status.strip(),
            actor_label=actor,
            transition_comment=body.transition_comment,
        )
        return {"ok": True, "review_status": new}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/missions/{mission_id}/reports/{report_type}/comments")
def api_list_report_comments(request: Request, mission_id: str, report_type: str):
    _report_read(request, mission_id, report_type)
    return {"comments": list_comments(mission_id, report_type)}


@app.post("/api/missions/{mission_id}/reports/{report_type}/comments")
def api_post_report_comment(
    request: Request, mission_id: str, report_type: str, body: ReportCommentBody
):
    _report_read(request, mission_id, report_type)
    mission_member_service.assert_can_edit_report(_uid(request), mission_id)
    u = getattr(request.state, "user", {})
    actor = body.author_label or u.get("display_name") or u.get("username")
    try:
        cid = add_comment(
            mission_id,
            report_type,
            body.body,
            parent_id=body.parent_id,
            anchor_section_key=body.anchor_section_key,
            anchor_json=body.anchor_json,
            author_label=actor,
        )
        return {"ok": True, "id": cid}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/missions/{mission_id}/reports/{report_type}/comments/{comment_id}")
def api_delete_report_comment(
    request: Request, mission_id: str, report_type: str, comment_id: str
):
    _report_read(request, mission_id, report_type)
    mission_member_service.assert_can_edit_report(_uid(request), mission_id)
    try:
        delete_comment(mission_id, report_type, comment_id)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/missions/{mission_id}/reports/{report_type}/approval-log")
def api_report_approval_log(request: Request, mission_id: str, report_type: str, limit: int = 50):
    _report_read(request, mission_id, report_type)
    return {"events": list_approval_events(mission_id, report_type, limit=limit)}


@app.post("/api/missions/{mission_id}/reports/{report_type}/finalize")
def api_finalize_report(
    request: Request,
    mission_id: str,
    report_type: str,
    body: FinalizeReportBody | None = None,
):
    _report_read(request, mission_id, report_type)
    mission_member_service.assert_can_finalize(_uid(request), mission_id)
    b = body or FinalizeReportBody()
    u = getattr(request.state, "user", {})
    actor = b.actor_label or u.get("display_name") or u.get("username")
    try:
        finalize_report_export(
            mission_id,
            report_type,
            actor_label=actor,
            current_revision_id=b.current_revision_id,
        )
        return {"ok": True, "review_status": get_review_status(mission_id, report_type)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/missions/{mission_id}/reports/{report_type}/preview")
def api_get_report_preview(request: Request, mission_id: str, report_type: str):
    """Return HTML preview with all pending edits applied (for display in draft before accept)."""
    _report_read(request, mission_id, report_type)
    try:
        html = get_report_preview(mission_id, report_type)
        return {"preview_html": html}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/missions/{mission_id}/reports/{report_type}/blocks")
def api_get_report_blocks(request: Request, mission_id: str, report_type: str):
    """Return current_content parsed into blocks (block_id, section_id, html) for inline edit highlighting."""
    _report_read(request, mission_id, report_type)
    report = get_report(mission_id, report_type)
    html = (report.get("current_content") or "").strip()
    blocks = parse_html_to_blocks(html)
    return {
        "blocks": [
            {"block_id": b.block_id, "section_id": b.section_id, "html": b.html, "order": b.order}
            for b in blocks
        ]
    }


@app.post("/api/missions/{mission_id}/reports/{report_type}/accept")
def api_accept_pending(request: Request, mission_id: str, report_type: str):
    m = _report_edit(request, mission_id, report_type)
    _require_content_unlocked(mission_id, report_type)
    try:
        path = accept_pending(mission_id, report_type, Path(m["output_path"]))
        return {"ok": True, "path": str(path)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/missions/{mission_id}/reports/{report_type}/reject")
def api_reject_pending(request: Request, mission_id: str, report_type: str):
    _report_edit(request, mission_id, report_type)
    _require_content_unlocked(mission_id, report_type)
    reject_pending(mission_id, report_type)
    return {"ok": True}


@app.post("/api/missions/{mission_id}/reports/{report_type}/reset")
def api_reset_report(request: Request, mission_id: str, report_type: str):
    """Reset this report's draft to the skeleton template. Clears pending content and pending edits."""
    _report_edit(request, mission_id, report_type)
    _require_content_unlocked(mission_id, report_type)
    reset_report_to_template(mission_id, report_type)
    return {"ok": True}


@app.post("/api/missions/{mission_id}/reports/{report_type}/inline-assist")
def api_inline_assist(request: Request, mission_id: str, report_type: str, body: InlineAssistBody):
    """Phase 3: selection/cursor assist; returns a suggestion only (client applies on Accept)."""
    _report_ai(request, mission_id, report_type)
    _require_ai_unlocked(mission_id, report_type)
    try:
        return run_inline_assist(
            mission_id,
            report_type,
            body.action.strip(),
            selection=body.selection or "",
            before_cursor=body.before_cursor or "",
            after_cursor=body.after_cursor or "",
            current_draft_html=body.current_draft_html,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@app.post("/api/missions/{mission_id}/reports/{report_type}/save")
def api_save_edit(request: Request, mission_id: str, report_type: str, body: SaveReportBody):
    m = _report_edit(request, mission_id, report_type)
    _require_content_unlocked(mission_id, report_type)
    path = save_user_edit(
        mission_id,
        report_type,
        body.content,
        Path(m["output_path"]),
        margins=body.margins,
        content_json=body.content_json,
    )
    return {"ok": True, "path": str(path)}


# ---------- Structured edit proposals (collaborative editor) ----------


@app.get("/api/missions/{mission_id}/reports/{report_type}/pending-edits")
def api_get_pending_edits(request: Request, mission_id: str, report_type: str):
    _report_read(request, mission_id, report_type)
    return get_pending_edits(mission_id, report_type)


@app.post("/api/missions/{mission_id}/reports/{report_type}/edits/{edit_id}/accept")
def api_accept_edit(request: Request, mission_id: str, report_type: str, edit_id: str):
    m = _report_edit(request, mission_id, report_type)
    _require_content_unlocked(mission_id, report_type)
    accept_edit(mission_id, report_type, edit_id)
    return {"ok": True}


@app.post("/api/missions/{mission_id}/reports/{report_type}/edits/{edit_id}/reject")
def api_reject_edit(request: Request, mission_id: str, report_type: str, edit_id: str):
    _report_edit(request, mission_id, report_type)
    _require_content_unlocked(mission_id, report_type)
    reject_edit(mission_id, report_type, edit_id)
    return {"ok": True}


@app.post("/api/missions/{mission_id}/reports/{report_type}/accept-all-edits")
def api_accept_all_edits(request: Request, mission_id: str, report_type: str):
    _report_edit(request, mission_id, report_type)
    _require_content_unlocked(mission_id, report_type)
    accept_all_edits(mission_id, report_type)
    return {"ok": True}


@app.post("/api/missions/{mission_id}/reports/{report_type}/reject-all-edits")
def api_reject_all_edits(request: Request, mission_id: str, report_type: str):
    _report_edit(request, mission_id, report_type)
    _require_content_unlocked(mission_id, report_type)
    reject_all_edits(mission_id, report_type)
    return {"ok": True}


@app.post("/api/missions/{mission_id}/reports/{report_type}/apply-edits")
def api_apply_edits(request: Request, mission_id: str, report_type: str):
    m = _report_edit(request, mission_id, report_type)
    _require_content_unlocked(mission_id, report_type)
    try:
        path = apply_accepted_edits(mission_id, report_type, Path(m["output_path"]))
        return {"ok": True, "path": str(path)}
    except ValueError as e:
        raise HTTPException(400, str(e))


class RunPipelineBody(BaseModel):
    mission_id: str
    update_intent: str | None = None


class UpdateReportBody(BaseModel):
    update_intent: str | None = None


@app.post("/api/run-pipeline")
def run_pipeline_api(request: Request, body: RunPipelineBody):
    """Run pipeline for all report types. Delegates to main orchestrator."""
    m = _mission404(body.mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.assert_can_run_ai(_uid(request), body.mission_id)
    ok, err, job_id = request_mission_update(
        body.mission_id, report_types=None, update_intent=body.update_intent
    )
    if not ok:
        if err and "No reports can run AI update" in err:
            raise HTTPException(409, err)
        return {"ok": False, "error": err or "Unknown error"}
    return {"ok": True, "mission_id": body.mission_id, "job_id": job_id}


@app.post("/api/missions/{mission_id}/reports/{report_type}/update")
def api_update_report(
    request: Request,
    mission_id: str,
    report_type: str,
    body: UpdateReportBody | None = None,
):
    """Update a single report type. Delegates to main orchestrator."""
    _report_ai(request, mission_id, report_type)
    _require_ai_unlocked(mission_id, report_type)
    b = body or UpdateReportBody()
    ok, err, job_id = request_mission_update(
        mission_id, report_types=[report_type], update_intent=b.update_intent
    )
    if not ok:
        raise HTTPException(400, err or "Unknown error")
    return {"ok": True, "mission_id": mission_id, "report_type": report_type, "job_id": job_id}


@app.get("/api/missions/{mission_id}/pipeline-jobs")
def api_list_pipeline_jobs(request: Request, mission_id: str, limit: int = 25):
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.assert_can_read_reports(_uid(request), mission_id)
    return {"jobs": list_pipeline_jobs(mission_id, limit)}


@app.get("/api/missions/{mission_id}/pipeline-jobs/{job_id}")
def api_get_pipeline_job(request: Request, mission_id: str, job_id: str):
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.assert_can_read_reports(_uid(request), mission_id)
    row = get_pipeline_job(mission_id, job_id)
    if not row:
        raise HTTPException(404, "Job not found")
    return row


@app.get("/api/missions/{mission_id}/reports/{report_type}/revisions")
def api_list_report_revisions(
    request: Request, mission_id: str, report_type: str, limit: int = 50
):
    _report_read(request, mission_id, report_type)
    try:
        return {"revisions": list_report_revisions(mission_id, report_type, limit)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/missions/{mission_id}/reports/{report_type}/revisions/{revision_id}")
def api_get_report_revision(
    request: Request, mission_id: str, report_type: str, revision_id: str
):
    _report_read(request, mission_id, report_type)
    row = get_report_revision(mission_id, report_type, revision_id)
    if not row:
        raise HTTPException(404, "Revision not found")
    return row


@app.get("/api/report-types/{report_type}/sections")
def api_report_type_sections(request: Request, report_type: str):
    _require_auth(request)
    if report_type not in REPORT_TYPES:
        raise HTTPException(400, f"report_type must be one of {REPORT_TYPES}")
    return {"sections": list_section_definitions_for_report_type(report_type)}


@app.get("/api/status")
def status(request: Request):
    _require_auth(request)
    with app.state.stream_lock:
        mid = getattr(app.state, "running_mission_id", None)
    return {"running_mission_id": mid}


@app.get("/api/missions/{mission_id}/activity")
def api_mission_activity(request: Request, mission_id: str, limit: int = 60):
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.assert_can_read_reports(_uid(request), mission_id)
    return {"events": mission_activity_feed(mission_id, limit)}


@app.post("/api/missions/{mission_id}/chat")
def api_mission_chat(request: Request, mission_id: str, body: MissionChatBody):
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.assert_can_edit_report(_uid(request), mission_id)
    try:
        return chat_service.run_chat_turn(
            mission_id,
            _uid(request),
            body.message.strip(),
            "mission",
            None,
            None,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/missions/{mission_id}/reports/{report_type}/chat-messages")
def api_list_report_chat_messages(
    request: Request, mission_id: str, report_type: str, limit: int = 40
):
    _report_read(request, mission_id, report_type)
    return {
        "messages": chat_service.list_recent_messages(
            mission_id, report_type, limit=limit
        )
    }


@app.post("/api/missions/{mission_id}/reports/{report_type}/chat")
def api_report_chat(
    request: Request, mission_id: str, report_type: str, body: ChatBody
):
    _report_read(request, mission_id, report_type)
    mission_member_service.assert_can_edit_report(_uid(request), mission_id)
    sc = body.scope.strip().lower()
    if sc not in ("report", "section", "mission"):
        raise HTTPException(400, "scope must be report, section, or mission")
    try:
        return chat_service.run_chat_turn(
            mission_id,
            _uid(request),
            body.message.strip(),
            sc,
            report_type if sc in ("report", "section") else None,
            body.section_key,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/missions/{mission_id}/documents")
def api_mission_documents_registry(request: Request, mission_id: str):
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.assert_can_read_reports(_uid(request), mission_id)
    return list_mission_documents(mission_id, Path(m["source_path"]))


@app.post("/api/missions/{mission_id}/build-index")
def api_build_mission_index(request: Request, mission_id: str):
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.assert_can_run_ai(_uid(request), mission_id)
    sp = Path(m["source_path"])
    if not sp.is_dir():
        raise HTTPException(400, "Mission source path is not a directory")
    build_mission_index(mission_id, sp)
    return {"ok": True, "mission_id": mission_id}


@app.post("/api/missions/{mission_id}/reports/{report_type}/export/pdf")
def api_export_report_pdf(
    request: Request,
    mission_id: str,
    report_type: str,
    body: ExportPdfBody | None = None,
):
    _report_read(request, mission_id, report_type)
    b = body or ExportPdfBody()
    try:
        html = (
            get_report_preview(mission_id, report_type)
            if b.use_preview
            else (get_report(mission_id, report_type).get("current_content") or "")
        )
        pdf = html_to_pdf_bytes(html or "<html><body></body></html>")
    except ValueError as e:
        raise HTTPException(400, str(e))
    fname = f"{report_type}_{mission_id}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.post("/api/missions/{mission_id}/presence")
def api_presence_heartbeat(request: Request, mission_id: str):
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.assert_can_read_reports(_uid(request), mission_id)
    presence_service.heartbeat(mission_id, _uid(request))
    return {"ok": True}


@app.get("/api/missions/{mission_id}/presence")
def api_presence_list(request: Request, mission_id: str):
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.assert_can_read_reports(_uid(request), mission_id)
    return {"presence": presence_service.list_presence(mission_id)}


@app.get("/api/missions/{mission_id}/auxiliary")
def api_list_auxiliary(request: Request, mission_id: str):
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.assert_can_read_reports(_uid(request), mission_id)
    return {"sources": auxiliary_service.list_auxiliary(mission_id)}


@app.post("/api/missions/{mission_id}/auxiliary")
def api_add_auxiliary(request: Request, mission_id: str, body: AuxiliarySourceBody):
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.require_mel(_uid(request), mission_id)
    try:
        rid = auxiliary_service.add_auxiliary(
            mission_id,
            body.label,
            body.path,
            report_types=body.report_types,
            enabled=body.enabled,
        )
        return {"ok": True, "id": rid}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/missions/{mission_id}/auxiliary/{source_id}")
def api_delete_auxiliary(
    request: Request, mission_id: str, source_id: str
):
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.require_mel(_uid(request), mission_id)
    if not auxiliary_service.delete_auxiliary(mission_id, source_id):
        raise HTTPException(404, "Auxiliary source not found")
    return {"ok": True}


@app.post("/api/missions/{mission_id}/members")
def api_add_mission_member(
    request: Request, mission_id: str, body: AddMissionMemberBody
):
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.require_mel(_uid(request), mission_id)
    u = auth_service.get_user_by_login_id(body.username)
    if not u:
        raise HTTPException(400, "No user account for that username")
    try:
        mission_member_service.add_member(
            mission_id, u["id"], body.role, body.affiliation
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.delete("/api/missions/{mission_id}/members/{member_user_id}")
def api_remove_mission_member(
    request: Request, mission_id: str, member_user_id: str
):
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.require_mel(_uid(request), mission_id)
    if member_user_id == _uid(request):
        raise HTTPException(400, "Cannot remove yourself")
    mission_member_service.remove_member(mission_id, member_user_id)
    return {"ok": True}


@app.get("/api/missions/{mission_id}/export/bundle")
def api_mission_export_bundle(request: Request, mission_id: str):
    m = _mission404(mission_id)
    uid = _uid(request)
    actor = getattr(request.state, "user", {})
    if not actor.get("is_admin"):
        mission_member_service.require_mel(uid, mission_id)
    buf = io.BytesIO()
    op = Path(m["output_path"])
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if op.is_dir():
            for f in op.rglob("*"):
                if f.is_file():
                    try:
                        zf.write(f, arcname=f"output/{f.relative_to(op)}")
                    except OSError:
                        pass
        zf.writestr(
            "mission_meta.json",
            json.dumps(
                {"mission_id": m["id"], "name": m.get("name")},
                indent=0,
            ),
        )
    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{mission_id}_bundle.zip"'
        },
    )


@app.get("/api/debug/global")
def api_debug_global(request: Request):
    actor = getattr(request.state, "user", None)
    if not actor or not actor.get("is_admin"):
        raise HTTPException(403, "Admin only")
    return admin_debug_service.global_debug_snapshot()


@app.get("/api/missions/{mission_id}/debug")
def api_debug_mission(request: Request, mission_id: str):
    m = _mission404(mission_id)
    uid = _uid(request)
    actor = getattr(request.state, "user", {})
    if not actor.get("is_admin"):
        mission_member_service.require_mel(uid, mission_id)
    return admin_debug_service.mission_debug_snapshot(mission_id)


# ---------- SSE streaming ----------

async def _sse_stream(mission_id: str, report_type: str, request: Request):
    state = request.app.state
    buffers = state.stream_buffers
    queues = state.stream_queues
    lock = state.stream_lock
    m = get_mission(mission_id)
    canonical_id = m["id"] if m else mission_id
    key = (canonical_id, report_type)

    q = asyncio.Queue()
    with lock:
        buffers.setdefault(key, "")
        queues.setdefault(key, []).append(q)

    try:
        with lock:
            buf = buffers.get(key, "")
        if buf:
            yield f"data: {json.dumps({'t': 'buf', 'text': buf})}\n\n"

        while True:
            try:
                chunk = await asyncio.wait_for(q.get(), timeout=30.0)
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'t': 'ping'})}\n\n"
                continue
            if chunk is None:
                yield f"data: {json.dumps({'t': 'done'})}\n\n"
                break
            yield f"data: {json.dumps({'t': 'chunk', 'text': chunk})}\n\n"
    finally:
        with lock:
            if key in queues:
                try:
                    queues[key].remove(q)
                except ValueError:
                    pass


@app.get("/api/stream/{mission_id}/{report_type}")
async def stream_sse(mission_id: str, report_type: str, request: Request):
    if report_type not in REPORT_TYPES:
        raise HTTPException(400, "Invalid report_type")
    m = _mission404(mission_id)
    mission_member_service.assert_mission_not_archived(m)
    mission_member_service.assert_can_read_reports(_uid(request), mission_id)
    return StreamingResponse(
        _sse_stream(mission_id, report_type, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------- Web app (Liquid Glass UI) ----------

if WEB_DIR.is_dir():
    _assets = WEB_ROOT / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets, html=False), name="assets")

    @app.get("/")
    def serve_app():
        return FileResponse(WEB_ROOT / "index.html")

    @app.get("/{path:path}")
    def serve_app_fallback(path: str):
        """SPA fallback: non-API paths without a file extension serve index.html."""
        if path.startswith("api/") or path == "api":
            raise HTTPException(404)
        ext = Path(path).suffix.lower()
        if ext in (".html", ".css", ".js", ".ico", ".png", ".jpg", ".svg", ".woff2"):
            f = WEB_ROOT / path
            if f.is_file():
                return FileResponse(f)
            if WEB_ROOT == WEB_DIR:
                pub = WEB_DIR / "public" / path
                if pub.is_file():
                    return FileResponse(pub)
        return FileResponse(WEB_ROOT / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        timeout_graceful_shutdown=5,
    )
