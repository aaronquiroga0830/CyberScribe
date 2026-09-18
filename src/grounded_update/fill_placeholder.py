"""Validate and refine fill_placeholder inline assist output."""
from __future__ import annotations

import re
from typing import Any

from src.grounded_update.evidence_attribution import filter_supporting_docs
from src.section_definitions import SECTION_DEFINITION_SEED
from src.templates.inline_assist_prompts import _section_display_title

_PLACEHOLDER_RE = re.compile(r"\[\s*to be filled|\[tbd\b", re.I)
_LOG_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+-")
_LOG_LINE_PREFIX_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+-\s*(?:Operator\s+\w+:\s*)?",
    re.I,
)


def _other_section_titles(report_type: str, section_key: str) -> list[str]:
    rt = (report_type or "").lower().strip()
    sk = (section_key or "").strip()
    out: list[str] = []
    for row_rt, row_sk, title, *_ in SECTION_DEFINITION_SEED:
        if row_rt != rt or row_sk in (sk, "title"):
            continue
        out.append(title)
    return out


def _line_is_section_heading(line: str, title: str) -> bool:
    stripped = line.strip().lower()
    t = title.strip().lower()
    return stripped == t or stripped.startswith(t + ":") or stripped.startswith(t + " —")


def looks_like_outline_suggestion(
    suggestion: str,
    *,
    report_type: str,
    section_key: str | None,
) -> list[str]:
    """Return rejection reasons when output mimics the document skeleton."""
    reasons: list[str] = []
    text = (suggestion or "").strip()
    if not text:
        return ["empty suggestion"]

    if _PLACEHOLDER_RE.search(text):
        reasons.append("still contains bracket placeholder text")

    if section_key:
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        for title in _other_section_titles(report_type, section_key):
            if any(_line_is_section_heading(ln, title) for ln in lines):
                reasons.append(f"contains section heading line '{title}'")

        short_lines = [ln for ln in lines if len(ln) <= 45]
        if len(short_lines) >= 2 and len(lines) == len(short_lines):
            reasons.append("multiple short lines look like a section outline")

        current = _section_display_title(report_type, section_key)
        if current and any(_line_is_section_heading(ln, current) for ln in lines):
            reasons.append(f"repeats current section heading '{current}'")

    return reasons


def looks_like_raw_log_dump(suggestion: str) -> bool:
    """True when output is pasted crew-log lines instead of report prose."""
    return bool(_LOG_TIMESTAMP_RE.search(suggestion or ""))


def _extract_facts_from_evidence(
    evidence: str,
    *,
    report_type: str,
    section_key: str,
) -> list[str]:
    facts: list[str] = []
    chunks = re.split(r"\n\s*---\s*\n", evidence or "")
    if len(chunks) <= 1:
        chunks = [c for c in re.split(r"\n\s*\n", evidence or "") if c.strip()]
    for chunk in chunks:
        for raw_line in chunk.splitlines():
            line = raw_line.strip().lstrip("-•* ").strip()
            if len(line) < 15:
                continue
            line = _LOG_LINE_PREFIX_RE.sub("", line).strip()
            if len(line) < 15 or _PLACEHOLDER_RE.search(line):
                continue
            facts.append(line.rstrip("."))
            if len(facts) >= 4:
                return facts
    return facts


def _prose_for_section(section_key: str, facts: list[str]) -> str:
    if not facts:
        return ""
    f0 = facts[0]
    f1 = facts[1] if len(facts) > 1 else None

    if section_key == "executive_summary":
        lead = f0[0].upper() + f0[1:] if f0 else f0
        if f1:
            follow = f1[0].lower() + f1[1:] if len(f1) > 1 else f1.lower()
            return f"{lead}. {follow[0].upper() + follow[1:] if follow else follow}."
        return f"{lead}."

    if section_key == "findings":
        return " ".join(f"{f}." for f in facts[:3])

    if section_key == "recommendations":
        base = f0[0].lower() + f0[1:] if f0 else f0
        return f"The team should {base} and track completion in follow-on mission reporting."

    return " ".join(f"{f}." for f in facts[:2])


def synthesize_fill_from_evidence(
    evidence: str,
    *,
    report_type: str,
    section_key: str,
    docs: list[Any] | None = None,
) -> tuple[str | None, list[Any]]:
    """Build section prose; return (text, doc objects that supplied facts)."""
    used_docs: list[Any] = []
    facts: list[str] = []

    if docs:
        for d in docs:
            content = getattr(d, "page_content", "") or ""
            added = 0
            for raw_line in content.splitlines():
                line = raw_line.strip().lstrip("-•* ").strip()
                if len(line) < 15:
                    continue
                line = _LOG_LINE_PREFIX_RE.sub("", line).strip()
                if len(line) < 15 or _PLACEHOLDER_RE.search(line):
                    continue
                facts.append(line.rstrip("."))
                added += 1
                if added == 1:
                    used_docs.append(d)
                if len(facts) >= 4:
                    break
            if len(facts) >= 4:
                break
    else:
        facts = _extract_facts_from_evidence(evidence, report_type=report_type, section_key=section_key)

    if not facts:
        return None, []

    prose = _prose_for_section(section_key, facts)
    if not prose or looks_like_raw_log_dump(prose):
        return None, []
    reject = looks_like_outline_suggestion(prose, report_type=report_type, section_key=section_key)
    if reject:
        return None, []

    if not used_docs and docs:
        used_docs = filter_supporting_docs(prose, docs, min_score=2.0) or docs[:1]
    elif not used_docs:
        used_docs = []

    return prose, used_docs


def build_fill_placeholder_retry_suffix(report_type: str, section_key: str | None) -> str:
    title = _section_display_title(report_type, section_key or "") or "this section"
    return (
        f"\n\nCRITICAL CORRECTION: Your previous answer was rejected because it looked like a document "
        f"outline or listed other sections. Output ONLY 2-4 complete sentences of plain prose for "
        f"{title}. No headings, no bullet lists of sections, no square brackets, no labels."
    )
