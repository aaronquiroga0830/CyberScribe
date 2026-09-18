"""
Classify editor focus into slot kinds for gap-aware assist.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

class SlotKind(str, Enum):
    TIMELINE_ROW = "timeline_row"
    FINDING_ROW = "finding_row"
    BRACKET_PLACEHOLDER = "bracket_placeholder"
    SECTION_EMPTY = "section_empty"
    FREEFORM = "freeform"


@dataclass
class GapSpec:
    slot_kind: SlotKind
    constraints: dict[str, Any] = field(default_factory=dict)
    neighbor_summary: str = ""


def _has_bracket_placeholder(before: str, after: str, selection: str) -> bool:
    window = f"{before[-800:]}{selection}{after[:800]}"
    return "[" in window and "]" in window


def classify_gap_spec(
    *,
    report_type: str,
    action: str,
    selection: str,
    before_cursor: str,
    after_cursor: str,
    current_draft_html: str | None,
) -> GapSpec | None:
    """
    Return a GapSpec when a specialized gap path applies; None for default assist.
    Selection actions (rewrite, etc.) skip timeline gap — user explicitly selected text.
    """
    rt = (report_type or "").lower().strip()
    cursorish = action in (
        "suggest_next_sentence",
        "insert_paragraph",
        "fill_placeholder",
    )

    if cursorish and rt == "timeline":
        from src.grounded_update.timeline_gap import try_parse_timeline_neighbors

        parsed = try_parse_timeline_neighbors(before_cursor, after_cursor)
        if parsed:
            prev_line, next_line, prev_dt, next_dt = parsed
            return GapSpec(
                slot_kind=SlotKind.TIMELINE_ROW,
                constraints={
                    "prev_line": prev_line,
                    "next_line": next_line,
                    "prev_dt": prev_dt,
                    "next_dt": next_dt,
                },
                neighbor_summary=f"Between timeline entries:\n{prev_line}\n{next_line}",
            )

    if cursorish and rt == "rmp":
        from src.grounded_update.findings_gap import try_parse_finding_continuation

        cont = try_parse_finding_continuation(before_cursor, after_cursor)
        if cont:
            return GapSpec(
                slot_kind=SlotKind.FINDING_ROW,
                constraints={
                    "next_num": cont.next_num,
                    "target_risk": cont.target_risk,
                    "last_line": cont.last_line,
                    "existing_findings": cont.existing_findings,
                },
                neighbor_summary=f"After finding list; next is Finding {cont.next_num} (Risk: {cont.target_risk}).",
            )

    if cursorish:
        win = f"{before_cursor[-500:]}{selection}{after_cursor[:500]}"
        if "[to be filled" in win.lower():
            return GapSpec(
                slot_kind=SlotKind.SECTION_EMPTY,
                constraints={},
                neighbor_summary="Placeholder-style section text near cursor.",
            )

    if cursorish and _has_bracket_placeholder(before_cursor, after_cursor, selection):
        sec_hint = ""
        if current_draft_html and "data-section-key" in current_draft_html:
            sec_hint = "Cursor is inside a structured report section."
        return GapSpec(
            slot_kind=SlotKind.BRACKET_PLACEHOLDER,
            constraints={"section_hint": sec_hint},
            neighbor_summary="Bracket-style placeholder near cursor.",
        )

    return None


def augment_standard_prompt(base_prompt: str, gap: GapSpec | None) -> str:
    """Append slot-specific instructions for non-timeline gap specs (timeline uses its own prompt)."""
    if not gap or gap.slot_kind == SlotKind.TIMELINE_ROW:
        return base_prompt
    if gap.slot_kind == SlotKind.BRACKET_PLACEHOLDER:
        return (
            base_prompt
            + "\n\n---\n\nSlot focus: Fill the bracket/placeholder using only evidence and draft context. "
            "Output only the replacement wording — no square brackets, no labels."
        )
    if gap.slot_kind == SlotKind.SECTION_EMPTY:
        return (
            base_prompt
            + "\n\n---\n\nSlot focus: Prefer concrete facts from evidence for this section; "
            "if unsupported, output a short explicit TBD-style phrase rather than inventing details. "
            "Do NOT output document titles, section headings, or outlines of other sections."
        )
    return base_prompt
