"""
Phase 4 §10.4: drop structured edits where new_html is nearly identical to old_html (no user value).
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any


def _plain(html: str) -> str:
    t = re.sub(r"<[^>]+>", " ", html or "")
    return " ".join(t.split()).lower()


def filter_near_duplicate_edits(
    edits: list[dict[str, Any]], *, threshold: float = 0.92
) -> tuple[list[dict[str, Any]], int]:
    """Return (kept_edits, suppressed_count)."""
    out: list[dict[str, Any]] = []
    suppressed = 0
    for e in edits:
        old_h = e.get("old_html") or ""
        new_h = e.get("new_html") or ""
        a, b = _plain(old_h), _plain(new_h)
        if a and b and SequenceMatcher(None, a, b).ratio() >= threshold:
            suppressed += 1
            continue
        out.append(e)
    return out, suppressed
