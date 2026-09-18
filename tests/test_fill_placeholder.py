"""Tests for fill_placeholder outline detection."""
from __future__ import annotations

import unittest

from src.grounded_update.fill_placeholder import (
    looks_like_outline_suggestion,
    synthesize_fill_from_evidence,
)


class TestFillPlaceholderValidation(unittest.TestCase):
    def test_rejects_document_outline(self):
        bad = "Findings\n\nTBD-style wording\n\nRecommendations\n\n[To be filled from mission data]"
        reasons = looks_like_outline_suggestion(
            bad, report_type="rmp", section_key="executive_summary"
        )
        self.assertTrue(any("Findings" in r for r in reasons))
        self.assertTrue(any("placeholder" in r for r in reasons))

    def test_allows_findings_word_in_prose(self):
        good = (
            "Initial network scan of the mission partner subnet identified exposed services. "
            "The crew documented key findings from crew logs and recommended restricting open RDP access."
        )
        self.assertEqual(
            looks_like_outline_suggestion(good, report_type="rmp", section_key="executive_summary"),
            [],
        )

    def test_accepts_prose_paragraph(self):
        good = (
            "The crew identified elevated weather and communications risks during the sortie. "
            "Mitigations included adjusted routing and redundant check-ins per crew logs."
        )
        self.assertEqual(
            looks_like_outline_suggestion(good, report_type="rmp", section_key="executive_summary"),
            [],
        )


    def test_synthesize_executive_summary_from_logs(self):
        evidence = (
            "2025-01-15 09:00 - Operator A: Initial network scan of mission partner subnet.\n"
            "2025-01-15 10:30 - Operator A: Reviewed firewall rules on gateway. Found open RDP."
        )
        out, used = synthesize_fill_from_evidence(
            evidence, report_type="rmp", section_key="executive_summary"
        )
        self.assertIsNotNone(out)
        assert out is not None
        self.assertNotRegex(out, r"\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}")
        self.assertNotIn("Findings", out)
        self.assertIsInstance(used, list)


if __name__ == "__main__":
    unittest.main()
