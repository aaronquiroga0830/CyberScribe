"""Match inline-assist suggestions to the evidence chunks that support them."""
from __future__ import annotations

import re
from typing import Any

_STOP = frozenset(
    "about after also been from have into more other some than that their there these "
    "this those through under until while with would mission partner network".split()
)

_IDENT_RE = re.compile(r"\b(?:SRV-\d+|NIST|SNMP|RDP|\d{1,3}(?:\.\d{1,3}){3})\b", re.I)


def _support_score(suggestion: str, content: str) -> float:
    if not (suggestion or "").strip() or not (content or "").strip():
        return 0.0
    sug = suggestion.lower()
    score = 0.0
    for ident in _IDENT_RE.findall(content):
        if ident.lower() in sug:
            score += 3.0
    tokens = {t for t in re.findall(r"\b[a-z0-9]{5,}\b", content.lower()) if t not in _STOP}
    if tokens:
        hits = sum(1 for t in tokens if t in sug)
        score += float(hits)
        if hits >= 4:
            score += 2.0
    for sent in re.split(r"[.!?\n]+", content):
        words = [w for w in re.findall(r"\b[a-z]{5,}\b", sent.lower()) if w not in _STOP]
        if len(words) >= 4 and sum(1 for w in words if w in sug) >= 4:
            score += 4.0
            break
    return score


def filter_supporting_docs(suggestion: str, docs: list[Any], *, min_score: float = 4.0) -> list[Any]:
    """Return docs whose content substantively overlaps the suggestion."""
    if not docs:
        return []
    scored = [(d, _support_score(suggestion, getattr(d, "page_content", "") or str(d))) for d in docs]
    kept = [d for d, s in scored if s >= min_score]
    if kept:
        kept.sort(key=lambda d: _support_score(suggestion, getattr(d, "page_content", "") or str(d)), reverse=True)
        return kept
    best = max(scored, key=lambda x: x[1])
    if best[1] > 0:
        return [best[0]]
    return []
