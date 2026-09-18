"""
Short prompts for Phase 3 inline assist (scoped actions, not full-document update).
Model must return plain replacement text only — no markdown fences, no preamble.
"""

from src.grounded_update.policy import build_grounding_preamble_for_action

INLINE_ASSIST_ACTIONS: frozenset[str] = frozenset(
    {
        "rewrite",
        "shorten",
        "expand",
        "formalize",
        "operationalize",
        "to_bullets",
        "to_paragraph",
        "suggest_next_sentence",
        "insert_paragraph",
        "fill_placeholder",
    }
)

# Actions that require a non-empty text selection in the editor.
SELECTION_ACTIONS: frozenset[str] = frozenset(
    {
        "rewrite",
        "shorten",
        "expand",
        "formalize",
        "operationalize",
        "to_bullets",
        "to_paragraph",
    }
)

ACTION_INSTRUCTIONS: dict[str, str] = {
    "rewrite": "Rewrite the selected text for clarity and flow. Preserve meaning and tone appropriate to a military mission report. Output only the replacement text.",
    "shorten": "Shorten the selected text while keeping the essential facts. Output only the replacement text.",
    "expand": "Expand the selected text with reasonable operational detail (still concise). Do not invent facts not implied by the selection. Output only the replacement text.",
    "formalize": "Make the selected text more formal and suitable for an official report. Output only the replacement text.",
    "operationalize": "Rewrite the selection in concise operational military style (clear subject–verb–object, active voice where possible). Output only the replacement text.",
    "to_bullets": "Convert the selected text into a bullet list. Each bullet on its own line, starting with '- '. Output only the bullet lines, no heading.",
    "to_paragraph": "Convert the selected bullet or list text into one or two cohesive paragraphs. Output only the paragraph(s), plain text.",
    "suggest_next_sentence": "Suggest a single natural next sentence that continues the draft. Use only the context before the cursor; do not repeat it verbatim. Output only that sentence.",
    "insert_paragraph": "Write one short paragraph (2–4 sentences) that fits after the cursor context as a new operational report paragraph. Do not repeat the context. Output only the new paragraph.",
    "fill_placeholder": "Replace the selected or bracketed placeholder with prose for the CURRENT section only. Use evidence for concrete facts; otherwise a short TBD phrase. Do NOT output document titles, section headings, outlines, bullet lists of other sections, or square brackets.",
}


from src.section_definitions import SECTION_DEFINITION_SEED


def _section_display_title(report_type: str, section_key: str) -> str | None:
    rt = (report_type or "").lower().strip()
    sk = (section_key or "").strip()
    if not sk:
        return None
    for row_rt, row_sk, title, *_ in SECTION_DEFINITION_SEED:
        if row_rt == rt and row_sk == sk:
            return title
    return None


SECTION_FILL_HINTS: dict[str, str] = {
    "executive_summary": (
        "Write 2-4 complete sentences summarizing mission purpose, key risks, and mitigations "
        "using evidence. Plain prose only."
    ),
    "findings": (
        "Write 2-5 complete sentences describing operational findings supported by evidence. "
        "Plain prose only."
    ),
    "recommendations": (
        "Write 2-4 complete sentences with actionable recommendations tied to the findings. "
        "Plain prose only."
    ),
}


def build_fill_placeholder_prompt(
    selection: str,
    evidence: str,
    *,
    report_type: str,
    section_key: str | None,
) -> str:
    """Narrow prompt: section + selection + evidence only (no full-document skeleton)."""
    instruction = ACTION_INSTRUCTIONS["fill_placeholder"]
    grounding = build_grounding_preamble_for_action("fill_placeholder")
    section_title = _section_display_title(report_type, section_key or "") if section_key else None
    hint = SECTION_FILL_HINTS.get(section_key or "", "")

    parts = [instruction, "", grounding, "", "---", ""]
    if section_title:
        parts.extend(
            [
                "Example (format only — use your mission evidence, not this text):",
                "The crew identified elevated weather and communications risk during ingress. "
                "Mitigations included adjusted routing and redundant check-ins documented in crew logs.",
                "",
                f"Target section: {section_title}",
                f"Replace ONLY the placeholder text below with new body copy for this section.",
                hint or "Plain prose only for this section.",
                "",
                "Placeholder to replace:",
                selection.strip() or "[To be filled from mission data]",
                "",
                "---",
                "",
            ]
        )
    if evidence.strip():
        parts.extend(
            [
                "Evidence excerpts (use for concrete facts; cite nothing in output):",
                evidence.strip(),
                "",
                "---",
                "",
            ]
        )
    parts.append(
        "Respond with replacement prose only—2-4 sentences. "
        "No document title, no section headings, no outlines, no square brackets."
    )
    return "\n".join(parts)


def build_inline_assist_prompt(
    action: str,
    selection: str,
    before_cursor: str,
    after_cursor: str,
    evidence: str,
    *,
    report_type: str = "",
    section_key: str | None = None,
) -> str:
    if action == "fill_placeholder" and section_key and selection.strip():
        return build_fill_placeholder_prompt(
            selection, evidence, report_type=report_type, section_key=section_key
        )

    instruction = ACTION_INSTRUCTIONS.get(action, ACTION_INSTRUCTIONS["rewrite"])
    grounding = build_grounding_preamble_for_action(action)
    parts = [instruction, "", grounding, "", "---", ""]
    section_title = _section_display_title(report_type, section_key or "") if section_key else None
    if section_title and action == "fill_placeholder":
        parts.extend(
            [
                f"Current section: {section_title} (key: {section_key}).",
                "Write ONLY the body text that belongs in this section—never repeat this heading or other sections.",
                "",
                "---",
                "",
            ]
        )
    if evidence.strip():
        parts.extend(
            [
                "Evidence excerpts (may be empty; use only if relevant):",
                evidence.strip(),
                "",
                "---",
                "",
            ]
        )
    if selection.strip():
        parts.extend(["Selected text:", selection.strip(), "", "---", ""])
    if before_cursor.strip() or after_cursor.strip():
        parts.extend(
            [
                "Text before cursor:",
                (before_cursor or "")[-4000:],
                "",
                "Text after cursor:",
                (after_cursor or "")[:1500],
                "",
            ]
        )
    parts.append("Respond with the replacement or new text only. No quotes, no markdown code fences, no labels.")
    return "\n".join(parts)
