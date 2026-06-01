"""
Shared grounding and output-shape rules for inline assist and structured pipeline edits.
"""

from __future__ import annotations

# Prepended to every inline assist prompt (after action instruction, before evidence).
INLINE_GROUNDING_RULES = """
Grounding rules (mandatory):
- Use ONLY facts supported by the evidence excerpts below and/or already stated in the draft context (selected text, text before/after cursor). If something is not supported, omit it or use a short "TBD" / "Not stated in source material" form rather than inventing operational detail.
- Do not copy separator lines, markdown fences, or bracket placeholders like [---] into your output.
- Do not restate or paraphrase large passages that already appear verbatim in the draft context unless the task explicitly rewrites that passage.
- Prefer the smallest change that satisfies the instruction (one word, one sentence, one paragraph, etc. per output limits).
""".strip()

# Prefix for structured JSON edit prompts (pipeline). JSON-only constraint stays in the template.
STRUCTURED_EDIT_GROUNDING_PREFIX = """
Grounding rules for all proposed edits (mandatory):
- Use ONLY the source material block below and the current document HTML. Do not invent mission facts, times, operators, or file contents not supported by the source.
- Prefer minimal edits: update or replace existing blocks before appending redundant paragraphs.
- Each edit's evidence field should name source files that support the change when applicable.
- Avoid proposing new_html that substantially duplicates another block in the current document unless fixing an error.
""".strip()

# Action-specific output caps (instruction lines appended to prompt).
ACTION_OUTPUT_LIMITS: dict[str, str] = {
    "rewrite": "Output limit: roughly the same length as the selection unless shortening/expand action implies otherwise.",
    "shorten": "Output limit: strictly shorter than the selection.",
    "expand": "Output limit: at most double the selection length; stay concise.",
    "formalize": "Output limit: comparable length to the selection.",
    "operationalize": "Output limit: comparable length to the selection.",
    "to_bullets": "Output limit: bullets only, no more than 12 bullet lines.",
    "to_paragraph": "Output limit: at most two short paragraphs.",
    "suggest_next_sentence": "Output limit: ONE sentence only (one period unless abbreviations). No bullet lists. Match list/timeline line format if the cursor sits in a bullet list (leading '- ' or numbered line).",
    "insert_paragraph": "Output limit: one paragraph, 2-4 sentences only. No section headers unless the draft already uses them at that position.",
    "fill_placeholder": "Output limit: only the phrase or sentences needed to replace the placeholder—no brackets, no preamble, typically under 8 sentences.",
}


def build_grounding_preamble_for_action(action: str) -> str:
    limits = ACTION_OUTPUT_LIMITS.get(action, ACTION_OUTPUT_LIMITS["rewrite"])
    return f"{INLINE_GROUNDING_RULES}\n\nOutput shape:\n{limits}"
