"""Shared grounded-update policy for inline assist and pipeline structured edits."""

from src.grounded_update.policy import (
    ACTION_OUTPUT_LIMITS,
    STRUCTURED_EDIT_GROUNDING_PREFIX,
    build_grounding_preamble_for_action,
)
from src.grounded_update.retrieval import gather_inline_assist_documents
from src.grounded_update.draft_dedupe import analyze_suggestion_against_draft
from src.grounded_update.gap_spec import (
    GapSpec,
    SlotKind,
    augment_standard_prompt,
    classify_gap_spec,
)
from src.grounded_update.pipeline_gap_hints import build_structured_edit_gap_hints
from src.grounded_update.timeline_gap import (
    build_timeline_gap_prompt,
    filter_chunks_for_timeline_gap,
    load_all_timeline_docs,
    mid_time_line,
    try_parse_timeline_neighbors,
    validate_timeline_suggestion,
)

__all__ = [
    "ACTION_OUTPUT_LIMITS",
    "STRUCTURED_EDIT_GROUNDING_PREFIX",
    "GapSpec",
    "SlotKind",
    "augment_standard_prompt",
    "build_structured_edit_gap_hints",
    "build_grounding_preamble_for_action",
    "build_timeline_gap_prompt",
    "classify_gap_spec",
    "filter_chunks_for_timeline_gap",
    "gather_inline_assist_documents",
    "load_all_timeline_docs",
    "mid_time_line",
    "try_parse_timeline_neighbors",
    "validate_timeline_suggestion",
    "analyze_suggestion_against_draft",
]
