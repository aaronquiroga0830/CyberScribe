"""
Lightweight gap hints for pipeline structured-edit prompts (section vs filled blocks).
"""
from __future__ import annotations

import re


def build_structured_edit_gap_hints(current_html: str) -> str:
    """
    Return a short paragraph to bias JSON edits toward missing slots, or "" if none.
    """
    if not (current_html or "").strip():
        return ""
    plain = re.sub(r"<[^>]+>", " ", current_html)
    plain = " ".join(plain.split())
    if not plain:
        return ""

    bracket_like = len(re.findall(r"\[[^\]]{1,200}\]", plain))
    tbf = plain.lower().count("to be filled")
    timeline_hits = len(
        re.findall(r"\b\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}\b", plain)
    )

    hints: list[str] = []
    if tbf or bracket_like >= 2:
        hints.append(
            'The draft still has bracket placeholders or "to be filled" wording — prioritize '
            "replacing those with grounded facts from the context where evidence supports them."
        )
    if timeline_hits >= 3:
        hints.append(
            "Several dated timeline-style entries are present; watch for chronological gaps "
            "between adjacent lines and fill missing intervals when the context provides events in range."
        )
    if not hints:
        return ""
    return "Gap guidance (non-binding; still output valid JSON only):\n" + " ".join(hints)
