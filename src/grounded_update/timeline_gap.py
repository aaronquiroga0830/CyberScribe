"""
Mission Timeline: detect gap between two timestamp bullets, filter crew_log chunks, validate one line.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

# Leading bullet, ISO date, time, optional colon, rest of line
TIMELINE_BULLET_PATTERN = re.compile(
    r"^\s*-\s*(\d{4}-\d{2}-\d{2})\s+(\d{1,2}:\d{2})\s*:?\s*(.*)$",
    re.MULTILINE,
)

TIMELINE_DT_IN_TEXT = re.compile(
    r"(?<![0-9])\b(\d{4}-\d{2}-\d{2})[ T](\d{1,2}:\d{2})\b(?![0-9])"
)


def _parse_bullet_line(line: str) -> tuple[datetime, str] | None:
    m = TIMELINE_BULLET_PATTERN.match(line.strip())
    if not m:
        return None
    date_part, time_part, _rest = m.group(1), m.group(2), m.group(3)
    try:
        hh, mm = time_part.split(":")
        dt = datetime(int(date_part[:4]), int(date_part[5:7]), int(date_part[8:10]), int(hh), int(mm))
        return (dt, line.strip())
    except (ValueError, IndexError):
        return None


def _last_timeline_line_before(text: str) -> str | None:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    for ln in reversed(lines):
        if _parse_bullet_line(ln):
            return ln.strip()
    return None


def _first_timeline_line_after(text: str) -> str | None:
    for ln in (text or "").splitlines():
        if ln.strip() and _parse_bullet_line(ln):
            return ln.strip()
    return None


def try_parse_timeline_neighbors(
    before_cursor: str,
    after_cursor: str,
) -> tuple[str, str, datetime, datetime] | None:
    """
    If cursor sits strictly between two ordered timeline bullets, return
    (prev_line, next_line, prev_dt, next_dt). Else None.
    """
    prev_raw = _last_timeline_line_before(before_cursor)
    next_raw = _first_timeline_line_after(after_cursor)
    if not prev_raw or not next_raw:
        return None
    p = _parse_bullet_line(prev_raw)
    n = _parse_bullet_line(next_raw)
    if not p or not n:
        return None
    prev_dt, prev_line = p[0], p[1]
    next_dt, next_line = n[0], n[1]
    if prev_dt >= next_dt:
        return None
    return (prev_line, next_line, prev_dt, next_dt)


def _dts_in_window(text: str, low: datetime, high: datetime) -> bool:
    for m in TIMELINE_DT_IN_TEXT.finditer(text or ""):
        try:
            d_s, t_s = m.group(1), m.group(2)
            hh, mm = t_s.split(":")
            dt = datetime(int(d_s[:4]), int(d_s[5:7]), int(d_s[8:10]), int(hh), int(mm))
            if low < dt < high:
                return True
        except (ValueError, IndexError):
            continue
    return False


def filter_chunks_for_timeline_gap(
    docs: list[Any],
    prev_dt: datetime,
    next_dt: datetime,
    *,
    max_chunks: int = 14,
    max_chars: int = 12_000,
) -> list[Any]:
    """Keep documents whose page_content references a datetime strictly between prev and next."""
    out: list[Any] = []
    total = 0
    for d in docs:
        body = getattr(d, "page_content", None) or str(d)
        if _dts_in_window(body, prev_dt, next_dt):
            out.append(d)
            total += len(body)
            if len(out) >= max_chunks or total >= max_chars:
                break
    if out:
        return out
    # Fallback: include first chunks so model still has some crew_log context
    for d in docs[:max_chunks]:
        out.append(d)
    return out


def mid_time_line(prev_dt: datetime, next_dt: datetime) -> str:
    """ISO-like time midpoint for TBD scaffolding (same calendar day preferred)."""
    delta = (next_dt - prev_dt).total_seconds() / 2
    from datetime import timedelta

    mid = prev_dt + timedelta(seconds=max(60, delta))
    return f"{mid.strftime('%Y-%m-%d %H:%M')}:"


def build_timeline_gap_prompt(
    action: str,
    prev_line: str,
    next_line: str,
    prev_dt: datetime,
    next_dt: datetime,
    evidence: str,
    tbd_mid_prefix: str,
) -> str:
    grounding = (
        "You are filling ONE missing Mission Timeline bullet between two existing entries.\n"
        "Grounding rules:\n"
        "- Output EXACTLY ONE line of plain text.\n"
        "- The line MUST start with: '- YYYY-MM-DD HH:MM: ' (same format as neighbors), "
        "then a short factual description.\n"
        "- The timestamp MUST be strictly AFTER the previous line's time and strictly BEFORE "
        "the next line's time.\n"
        "- Use ONLY facts supported by the evidence snippets below. If no snippet supports "
        "a concrete event in that window, output exactly one line using this time prefix "
        f"with description only 'TBD (not found in source material)':\n  - {tbd_mid_prefix} TBD (not found in source material)\n"
        "- Do not mention dates or events outside the open interval between the two neighbor times unless they appear inside that interval in the evidence.\n"
        "- No markdown fences, no brackets like [---], no extra bullets, no preamble.\n"
    )
    parts = [
        grounding,
        "",
        "---",
        "",
        "Previous timeline line (do not repeat):",
        prev_line,
        "",
        "Next timeline line (do not repeat):",
        next_line,
        "",
        f"Required time window (exclusive): after {prev_dt.isoformat(timespec='minutes')} "
        f"and before {next_dt.isoformat(timespec='minutes')}.",
        "",
        "---",
        "",
        "Evidence snippets (filtered for timestamps/events between those lines when possible):",
        evidence or "(empty — use the TBD line format above)",
        "",
        "---",
        "",
        f"Assist action context: {action}",
        "",
        "Respond with that single timeline line only.",
    ]
    return "\n".join(parts)


def validate_timeline_suggestion(
    raw: str,
    prev_dt: datetime,
    next_dt: datetime,
) -> tuple[str | None, list[str]]:
    """
    Return (cleaned single line or None, warnings). None means caller should reject empty.
    """
    warnings: list[str] = []
    t = (raw or "").strip()
    if not t:
        return None, ["Timeline assist returned empty text after validation."]
    first_line = t.splitlines()[0].strip()
    m = TIMELINE_BULLET_PATTERN.match(first_line)
    if not m:
        warnings.append(
            "Timeline line did not match required '- YYYY-MM-DD HH:MM: ...' format; dropped."
        )
        return None, warnings
    try:
        date_part, time_part = m.group(1), m.group(2)
        hh, mm = time_part.split(":")
        prop = datetime(
            int(date_part[:4]),
            int(date_part[5:7]),
            int(date_part[8:10]),
            int(hh),
            int(mm),
        )
    except (ValueError, IndexError):
        return None, warnings + ["Could not parse suggested timeline timestamp."]

    if not (prev_dt < prop < next_dt):
        warnings.append(
            f"Suggested time {prop.isoformat(timespec='minutes')} is not strictly between "
            f"{prev_dt.isoformat(timespec='minutes')} and {next_dt.isoformat(timespec='minutes')}; dropped."
        )
        return None, warnings
    return first_line, warnings


def load_all_timeline_docs(mission_id: str) -> list[Any]:
    """All crew_log (+ aux) chunks for timeline retriever."""
    from src.index.build import mission_index_exists
    from src.retrieve.retriever import get_mission_retriever

    if not mission_index_exists(mission_id):
        return []
    retriever = get_mission_retriever(mission_id=mission_id, k=50, report_type="timeline")
    return list(retriever.invoke("mission timeline crew log chronological"))
