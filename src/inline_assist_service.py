"""
Phase 3: fast scoped LLM assist for the report editor (not a full pipeline job).
Grounded policy: multi-query retrieval, citation metadata, draft duplication warnings.
Gap-aware path for Mission Timeline rows and light slot hints for placeholders.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from langchain_community.chat_models import ChatOllama
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from config.settings import OLLAMA_MODEL, get_ollama_base_url_for_report
from src.grounded_update.draft_dedupe import analyze_suggestion_against_draft
from src.grounded_update.evidence_attribution import filter_supporting_docs
from src.grounded_update.fill_placeholder import (
    build_fill_placeholder_retry_suffix,
    looks_like_outline_suggestion,
    looks_like_raw_log_dump,
    synthesize_fill_from_evidence,
)
from src.grounded_update.findings_gap import (
    FindingContinuation,
    build_findings_continuation_prompt,
    build_findings_retrieval_query,
    filter_docs_for_findings_gap,
    validate_finding_suggestion,
)
from src.grounded_update.gap_spec import (
    SlotKind,
    augment_standard_prompt,
    classify_gap_spec,
)
from src.grounded_update.retrieval import assign_chunk_ids, gather_inline_assist_documents
from src.grounded_update.timeline_gap import (
    build_timeline_gap_prompt,
    filter_chunks_for_timeline_gap,
    load_all_timeline_docs,
    mid_time_line,
    validate_timeline_suggestion,
)
from src.templates.inline_assist_prompts import (
    INLINE_ASSIST_ACTIONS,
    SELECTION_ACTIONS,
    build_inline_assist_prompt,
)
from src.utils.context_cleaner import clean_context_for_llm

logger = logging.getLogger(__name__)

_MAX_SELECTION = 12_000
_MAX_BEFORE = 8_000
_MAX_AFTER = 2_000
_MAX_DRAFT_HTML_FOR_DEDUPE = 500_000


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```\s*$", "", t)
    return t.strip().strip('"').strip("'")


def _unique_sources(docs: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for d in docs:
        src = (getattr(d, "metadata", None) or {}).get("source") or ""
        if isinstance(src, str) and src and src not in seen:
            seen.add(src)
            out.append(src)
    return out[:8]


def _invoke_assist_llm(prompt_text: str, report_type: str, *, temperature: float = 0.3) -> str:
    base_url = get_ollama_base_url_for_report(report_type)
    llm = ChatOllama(base_url=base_url, model=OLLAMA_MODEL, temperature=temperature)
    chain = ChatPromptTemplate.from_messages([("human", prompt_text)]) | llm | StrOutputParser()
    return chain.invoke({})


def run_inline_assist(
    mission_id: str,
    report_type: str,
    action: str,
    selection: str = "",
    before_cursor: str = "",
    after_cursor: str = "",
    current_draft_html: str | None = None,
    section_key: str | None = None,
) -> dict[str, Any]:
    if action not in INLINE_ASSIST_ACTIONS:
        raise ValueError(f"Invalid action; use one of: {sorted(INLINE_ASSIST_ACTIONS)}")
    sel = (selection or "")[:_MAX_SELECTION]
    before = (before_cursor or "")[-_MAX_BEFORE:]
    after = (after_cursor or "")[:_MAX_AFTER]
    if action in SELECTION_ACTIONS and not sel.strip():
        raise ValueError("This action requires a non-empty selection")

    draft_html = current_draft_html or ""
    if len(draft_html) > _MAX_DRAFT_HTML_FOR_DEDUPE:
        draft_html = draft_html[-_MAX_DRAFT_HTML_FOR_DEDUPE:]

    rt = (report_type or "").lower().strip()
    gap = classify_gap_spec(
        report_type=rt,
        action=action,
        selection=sel,
        before_cursor=before,
        after_cursor=after,
        current_draft_html=draft_html,
    )

    if gap and gap.slot_kind == SlotKind.TIMELINE_ROW:
        prev_line = gap.constraints["prev_line"]
        next_line = gap.constraints["next_line"]
        prev_dt = gap.constraints["prev_dt"]
        next_dt = gap.constraints["next_dt"]
        docs_timeline = load_all_timeline_docs(mission_id)
        filtered = filter_chunks_for_timeline_gap(docs_timeline, prev_dt, next_dt)
        raw_ev = "\n\n---\n\n".join(getattr(d, "page_content", str(d)) for d in filtered)
        evidence = clean_context_for_llm(raw_ev) if raw_ev else ""
        sources = _unique_sources(filtered)
        evidence_chunks = assign_chunk_ids(filtered)
        tbd_mid = mid_time_line(prev_dt, next_dt)
        prompt_text = build_timeline_gap_prompt(
            action, prev_line, next_line, prev_dt, next_dt, evidence, tbd_mid
        )
        try:
            raw_out = _invoke_assist_llm(prompt_text, report_type)
        except Exception as e:
            logger.exception("inline assist LLM failed (timeline gap path)")
            raise RuntimeError(str(e)) from e
        suggestion, val_warn = validate_timeline_suggestion(
            _strip_fences(raw_out or ""), prev_dt, next_dt
        )
        if suggestion:
            dup_warn = analyze_suggestion_against_draft(suggestion, draft_html)
            return {
                "suggestion": suggestion,
                "evidence_sources": sources,
                "evidence_chunks": evidence_chunks,
                "grounding_warnings": val_warn + dup_warn,
            }
        logger.warning(
            "Timeline gap assist failed validation; falling back to standard assist: %s",
            val_warn,
        )

    if gap and gap.slot_kind == SlotKind.FINDING_ROW:
        next_num = int(gap.constraints["next_num"])
        target_risk = str(gap.constraints["target_risk"])
        existing = tuple(gap.constraints["existing_findings"])
        cont = FindingContinuation(
            next_num=next_num,
            target_risk=target_risk,
            last_line=str(gap.constraints["last_line"]),
            existing_findings=existing,
        )
        sk = section_key or "findings"
        docs_findings = gather_inline_assist_documents(
            mission_id,
            rt,
            selection=sel,
            before_cursor=before,
            after_cursor=after,
            k=6,
            max_chunks=16,
            section_key=sk,
            action=action,
            retrieval_query_override=build_findings_retrieval_query(next_num, target_risk),
        )
        filtered = filter_docs_for_findings_gap(docs_findings, existing)
        raw_ev = "\n\n---\n\n".join(getattr(d, "page_content", str(d)) for d in filtered)
        evidence = clean_context_for_llm(raw_ev) if raw_ev else ""
        sources = _unique_sources(filtered)
        evidence_chunks = assign_chunk_ids(filtered)
        prompt_text = build_findings_continuation_prompt(action, cont, evidence)
        try:
            raw_out = _invoke_assist_llm(prompt_text, report_type, temperature=0.1)
        except Exception as e:
            logger.exception("inline assist LLM failed (findings gap path)")
            raise RuntimeError(str(e)) from e
        suggestion, val_warn = validate_finding_suggestion(
            _strip_fences(raw_out or ""),
            next_num=next_num,
            target_risk=target_risk,
            existing_findings=existing,
        )
        if not suggestion:
            retry_prompt = (
                prompt_text
                + f"\n\n---\n\nYour previous answer was invalid. Output ONLY this pattern:\n"
                f"Finding {next_num}: <new fact from evidence> (Risk: {target_risk})."
            )
            try:
                raw_retry = _invoke_assist_llm(retry_prompt, report_type, temperature=0.1)
            except Exception:
                raw_retry = ""
            suggestion, val_warn = validate_finding_suggestion(
                _strip_fences(raw_retry or ""),
                next_num=next_num,
                target_risk=target_risk,
                existing_findings=existing,
            )
        if suggestion:
            attributed_docs = filter_supporting_docs(suggestion, filtered)
            dup_warn = analyze_suggestion_against_draft(suggestion, draft_html)
            return {
                "suggestion": suggestion,
                "evidence_sources": _unique_sources(attributed_docs) or sources,
                "evidence_chunks": assign_chunk_ids(attributed_docs) or evidence_chunks,
                "grounding_warnings": val_warn + dup_warn,
            }
        logger.warning(
            "Findings gap assist failed validation; falling back to standard assist: %s",
            val_warn,
        )

    docs: list[Any] = gather_inline_assist_documents(
        mission_id,
        rt,
        selection=sel,
        before_cursor=before,
        after_cursor=after,
        k=6,
        max_chunks=16,
        section_key=section_key,
        action=action,
    )
    raw = "\n\n---\n\n".join(getattr(d, "page_content", str(d)) for d in docs)
    evidence = clean_context_for_llm(raw) if raw else ""
    attributed_docs: list[Any] = []
    used_evidence_fallback = False

    prompt_text = augment_standard_prompt(
        build_inline_assist_prompt(
            action, sel, before, after, evidence, report_type=rt, section_key=section_key
        ),
        gap,
    )
    try:
        llm_temp = 0.1 if action == "fill_placeholder" else 0.3
        raw_out = _invoke_assist_llm(prompt_text, report_type, temperature=llm_temp)
    except Exception as e:
        logger.exception("inline assist LLM failed")
        raise RuntimeError(str(e)) from e

    suggestion = _strip_fences(raw_out or "")
    if not suggestion:
        raise RuntimeError("Model returned empty suggestion")

    outline_reasons: list[str] = []
    if action == "fill_placeholder":
        if looks_like_raw_log_dump(suggestion):
            outline_reasons = ["raw log dump instead of section prose"]
        else:
            outline_reasons = looks_like_outline_suggestion(
                suggestion, report_type=rt, section_key=section_key
            )
        if outline_reasons:
            retry_prompt = prompt_text + build_fill_placeholder_retry_suffix(rt, section_key)
            try:
                raw_retry = _invoke_assist_llm(retry_prompt, report_type, temperature=0.1)
            except Exception:
                raw_retry = ""
            suggestion_retry = _strip_fences(raw_retry or "")
            retry_reasons: list[str] = []
            if suggestion_retry:
                if looks_like_raw_log_dump(suggestion_retry):
                    retry_reasons = ["raw log dump instead of section prose"]
                else:
                    retry_reasons = looks_like_outline_suggestion(
                        suggestion_retry, report_type=rt, section_key=section_key
                    )
            else:
                retry_reasons = ["empty retry suggestion"]
            if suggestion_retry and not retry_reasons:
                suggestion = suggestion_retry
                outline_reasons = []
            else:
                fallback, fallback_docs = (
                    synthesize_fill_from_evidence(
                        evidence,
                        report_type=rt,
                        section_key=section_key or "",
                        docs=docs,
                    )
                    if section_key
                    else (None, [])
                )
                fb_reasons: list[str] = []
                if fallback:
                    if looks_like_raw_log_dump(fallback):
                        fb_reasons = ["raw log dump instead of section prose"]
                    else:
                        fb_reasons = looks_like_outline_suggestion(
                            fallback, report_type=rt, section_key=section_key
                        )
                else:
                    fb_reasons = ["no evidence fallback"]
                if fallback and not fb_reasons:
                    suggestion = fallback
                    outline_reasons = []
                    used_evidence_fallback = True
                    attributed_docs = fallback_docs
                else:
                    raise RuntimeError(
                        "Fill placeholder could not produce section prose. "
                        "Try Update for a full grounded draft, or edit manually."
                    )

    if not attributed_docs:
        attributed_docs = filter_supporting_docs(suggestion, docs)
    sources = _unique_sources(attributed_docs)
    evidence_chunks = assign_chunk_ids(attributed_docs)

    grounding_warnings = analyze_suggestion_against_draft(suggestion, draft_html)
    if used_evidence_fallback:
        grounding_warnings = list(grounding_warnings) + [
            "Suggestion built from evidence excerpts because the model returned a document outline."
        ]
    if gap and gap.slot_kind == SlotKind.TIMELINE_ROW:
        grounding_warnings = (
            list(grounding_warnings)
            + ["Timeline gap-specific validation was skipped in fallback assist."]
        )

    return {
        "suggestion": suggestion,
        "evidence_sources": sources,
        "evidence_chunks": evidence_chunks,
        "grounding_warnings": grounding_warnings,
    }
