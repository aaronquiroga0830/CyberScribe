"""Unit tests for RMP findings list continuation assist."""
from __future__ import annotations

import unittest

from src.grounded_update.findings_gap import (
    build_findings_retrieval_query,
    try_parse_finding_continuation,
    validate_finding_suggestion,
)
from src.grounded_update.gap_spec import SlotKind, classify_gap_spec


class TestFindingContinuation(unittest.TestCase):
    def test_detects_append_after_finding_3(self):
        before = (
            "Findings\n"
            "Finding 1: Firewall allows RDP (Risk: High).\n"
            "Finding 2: Patch backlog on SRV-01 (Risk: High).\n"
            "Finding 3: Weak password policy with no complexity or expiry (Risk: Medium).\n"
        )
        cont = try_parse_finding_continuation(before, "\nRecommendations\n")
        self.assertIsNotNone(cont)
        assert cont is not None
        self.assertEqual(cont.next_num, 4)
        self.assertEqual(cont.target_risk.lower(), "medium")

    def test_rejects_when_next_finding_already_present(self):
        before = "Finding 1: A (Risk: Low).\n"
        after = "Finding 2: B (Risk: Low).\n"
        self.assertIsNone(try_parse_finding_continuation(before, after))

    def test_classify_gap_spec_finding_row(self):
        before = (
            "Findings\n"
            "Finding 1: A (Risk: High).\n"
            "Finding 2: B (Risk: High).\n"
            "Finding 3: C (Risk: Medium).\n"
        )
        gap = classify_gap_spec(
            report_type="rmp",
            action="suggest_next_sentence",
            selection="",
            before_cursor=before,
            after_cursor="",
            current_draft_html=None,
        )
        self.assertIsNotNone(gap)
        assert gap is not None
        self.assertEqual(gap.slot_kind, SlotKind.FINDING_ROW)
        self.assertEqual(gap.constraints["next_num"], 4)
        self.assertEqual(gap.constraints["target_risk"], "Medium")


class TestValidateFinding(unittest.TestCase):
    def test_accepts_valid_finding_4_medium(self):
        existing = (
            "Finding 1: A (Risk: High).",
            "Finding 2: B (Risk: High).",
            "Finding 3: C (Risk: Medium).",
        )
        raw = "Finding 4: SNMP v2c enabled with public community string (Risk: Medium)."
        line, warns = validate_finding_suggestion(
            raw,
            next_num=4,
            target_risk="Medium",
            existing_findings=existing,
        )
        self.assertEqual(line, raw)
        self.assertEqual(warns, [])

    def test_rejects_wrong_risk_level(self):
        raw = "Finding 4: Something new (Risk: High)."
        line, warns = validate_finding_suggestion(
            raw,
            next_num=4,
            target_risk="Medium",
            existing_findings=("Finding 3: C (Risk: Medium).",),
        )
        self.assertIsNone(line)
        self.assertTrue(any("expected" in w.lower() for w in warns))


class TestRetrievalQuery(unittest.TestCase):
    def test_query_includes_num_and_risk(self):
        q = build_findings_retrieval_query(4, "Medium")
        self.assertIn("Finding 4", q)
        self.assertIn("Medium", q)


if __name__ == "__main__":
    unittest.main()
