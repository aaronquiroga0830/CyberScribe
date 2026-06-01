"""Unit tests for timeline gap parsing, chunk filter, and validation."""
from __future__ import annotations

import unittest
from datetime import datetime

from langchain_core.documents import Document

from src.grounded_update.gap_spec import (
    SlotKind,
    augment_standard_prompt,
    classify_gap_spec,
)
from src.grounded_update.pipeline_gap_hints import build_structured_edit_gap_hints
from src.grounded_update.timeline_gap import (
    filter_chunks_for_timeline_gap,
    try_parse_timeline_neighbors,
    validate_timeline_suggestion,
)


class TestTimelineNeighbors(unittest.TestCase):
    def test_detects_ordered_gap(self):
        before = "Intro\n- 2025-01-15 09:00: Briefing\n"
        after = "- 2025-01-15 14:00: Wheels up\n"
        got = try_parse_timeline_neighbors(before, after)
        self.assertIsNotNone(got)
        prev_line, next_line, prev_dt, next_dt = got  # type: ignore[misc]
        self.assertIn("09:00", prev_line)
        self.assertIn("14:00", next_line)
        self.assertLess(prev_dt, next_dt)

    def test_rejects_out_of_order_neighbors(self):
        before = "- 2025-01-15 16:00: Late\n"
        after = "- 2025-01-15 10:00: Early\n"
        self.assertIsNone(try_parse_timeline_neighbors(before, after))

    def test_missing_neighbor(self):
        self.assertIsNone(try_parse_timeline_neighbors("no bullets", "- 2025-01-01 10:00: x"))


class TestFilterChunks(unittest.TestCase):
    def test_keeps_chunk_with_time_in_window(self):
        low = datetime(2025, 1, 15, 9, 0)
        high = datetime(2025, 1, 15, 14, 0)
        docs = [
            Document(page_content="Nothing here."),
            Document(
                page_content="At 2025-01-15 11:30 the crew calibrated sensors.",
                metadata={"source": "/x/a.txt"},
            ),
        ]
        out = filter_chunks_for_timeline_gap(docs, low, high, max_chunks=8)
        self.assertEqual(len(out), 1)
        self.assertIn("11:30", out[0].page_content)

    def test_fallback_when_no_inner_timestamp(self):
        low = datetime(2025, 1, 15, 9, 0)
        high = datetime(2025, 1, 15, 10, 0)
        docs = [Document(page_content="No dates in this chunk.")]
        out = filter_chunks_for_timeline_gap(docs, low, high)
        self.assertEqual(len(out), 1)


class TestValidateSuggestion(unittest.TestCase):
    def test_accepts_valid_line(self):
        prev = datetime(2025, 1, 15, 9, 0)
        nxt = datetime(2025, 1, 15, 14, 0)
        raw = "- 2025-01-15 10:30: Test event\n"
        line, warns = validate_timeline_suggestion(raw, prev, nxt)
        self.assertEqual(line, "- 2025-01-15 10:30: Test event")
        self.assertEqual(warns, [])

    def test_rejects_out_of_range(self):
        prev = datetime(2025, 1, 15, 9, 0)
        nxt = datetime(2025, 1, 15, 10, 0)
        raw = "- 2025-01-15 11:00: Too late\n"
        line, warns = validate_timeline_suggestion(raw, prev, nxt)
        self.assertIsNone(line)
        self.assertTrue(any("not strictly between" in w for w in warns))

    def test_rejects_bad_format(self):
        prev = datetime(2025, 1, 15, 9, 0)
        nxt = datetime(2025, 1, 15, 14, 0)
        line, warns = validate_timeline_suggestion("just prose", prev, nxt)
        self.assertIsNone(line)
        self.assertTrue(warns)


class TestGapSpecClassify(unittest.TestCase):
    def test_timeline_row_when_neighbors_parse(self):
        gap = classify_gap_spec(
            report_type="timeline",
            action="suggest_next_sentence",
            selection="",
            before_cursor="- 2025-01-10 08:00: A\n",
            after_cursor="- 2025-01-10 12:00: B\n",
            current_draft_html=None,
        )
        self.assertIsNotNone(gap)
        assert gap is not None
        self.assertEqual(gap.slot_kind, SlotKind.TIMELINE_ROW)

    def test_bracket_placeholder_hint(self):
        gap = classify_gap_spec(
            report_type="rmp",
            action="insert_paragraph",
            selection="",
            before_cursor="Risk [TBD] for ",
            after_cursor=" sector.",
            current_draft_html="<p data-section-key=\"x\">y</p>",
        )
        self.assertIsNotNone(gap)
        assert gap is not None
        self.assertEqual(gap.slot_kind, SlotKind.BRACKET_PLACEHOLDER)

    def test_section_empty_near_to_be_filled(self):
        gap = classify_gap_spec(
            report_type="rmp",
            action="fill_placeholder",
            selection="",
            before_cursor="",
            after_cursor="[To be filled from mission data]",
            current_draft_html=None,
        )
        self.assertIsNotNone(gap)
        assert gap is not None
        self.assertEqual(gap.slot_kind, SlotKind.SECTION_EMPTY)


class TestAugmentPrompt(unittest.TestCase):
    def test_timeline_unchanged(self):
        base = "ORIG"
        gap = classify_gap_spec(
            report_type="timeline",
            action="suggest_next_sentence",
            selection="",
            before_cursor="- 2025-01-10 08:00: A\n",
            after_cursor="- 2025-01-10 12:00: B\n",
            current_draft_html=None,
        )
        assert gap is not None
        self.assertEqual(augment_standard_prompt(base, gap), base)

    def test_bracket_appends(self):
        from src.grounded_update.gap_spec import GapSpec

        g = GapSpec(SlotKind.BRACKET_PLACEHOLDER, {}, "")
        out = augment_standard_prompt("X", g)
        self.assertIn("Slot focus", out)
        self.assertTrue(out.startswith("X"))


class TestPipelineGapHints(unittest.TestCase):
    def test_empty_html(self):
        self.assertEqual(build_structured_edit_gap_hints(""), "")

    def test_detects_placeholders(self):
        html = "<p>[To be filled]</p><p>[risk]</p>"
        h = build_structured_edit_gap_hints(html)
        self.assertIn("Gap guidance", h)


if __name__ == "__main__":
    unittest.main()
