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
    "fill_placeholder": "The user cursor is near bracket-style placeholders like [To be filled from mission data]. Propose concrete placeholder replacement text using context and evidence; if unknown, use concise TBD-style wording. Output only the phrase or short paragraph to insert, not brackets.",
}


def build_inline_assist_prompt(
    action: str,
    selection: str,
    before_cursor: str,
    after_cursor: str,
    evidence: str,
) -> str:
    instruction = ACTION_INSTRUCTIONS.get(action, ACTION_INSTRUCTIONS["rewrite"])
    grounding = build_grounding_preamble_for_action(action)
    parts = [instruction, "", grounding, "", "---", ""]
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
