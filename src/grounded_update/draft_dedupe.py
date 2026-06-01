"""
Compare generated inline assist text to current draft to flag likely duplication.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

# Paragraph-ish segments from HTML or plain text
_BLOCK_SPLIT = re.compile(r"\n\s*\n+|<\s*br\s*/?\s*>|<\s*/\s*p\s*>", re.I)


def _plain(s: str) -> str:
    t = re.sub(r"<[^>]+>", " ", s or "")
    return " ".join(t.split()).lower()


def _segments_from_draft(draft_html: str) -> list[str]:
    raw = draft_html or ""
    # Strip tags roughly for splitting
    parts = _BLOCK_SPLIT.split(re.sub(r"<[^>]+>", "\n", raw))
    segs = []
    for p in parts:
        pl = _plain(p)
        if len(pl) >= 60:
            segs.append(pl)
    return segs


def analyze_suggestion_against_draft(suggestion: str, draft_html: str, *, threshold: float = 0.88) -> list[str]:
    """
    Return human-readable warnings if suggestion is highly similar to existing draft segments.
    Does not alter suggestion text.
    """
    warnings: list[str] = []
    if not (suggestion or "").strip() or not (draft_html or "").strip():
        return warnings
    sug = _plain(suggestion)
    if len(sug) < 40:
        return warnings
    for seg in _segments_from_draft(draft_html):
        if len(seg) < 40:
            continue
        ratio = SequenceMatcher(None, sug[:2000], seg[:2000]).ratio()
        if ratio >= threshold:
            warnings.append(
                "Generated text is very similar to a paragraph already in the draft; "
                "verify it adds new information before accepting."
            )
            break
    return warnings
