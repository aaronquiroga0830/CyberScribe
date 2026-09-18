"""Tests for inline-assist evidence attribution."""
from __future__ import annotations

import unittest


class _Doc:
    def __init__(self, source: str, content: str):
        self.metadata = {"source": source}
        self.page_content = content


class TestEvidenceAttribution(unittest.TestCase):
    def test_filters_to_supporting_files_only(self):
        from src.grounded_update.evidence_attribution import filter_supporting_docs

        suggestion = (
            "The mission partner's network presented elevated risks due to open RDP access and SNMP exposure. "
            "Recommendations included restricting RDP access and implementing a password policy compliant with NIST standards."
        )
        docs = [
            _Doc("crew_log_1.txt", "2025-01-15 09:00 - Operator A: Routine comms check."),
            _Doc(
                "findings.txt",
                "Open RDP from internet on gateway. SNMP community string public. "
                "Password policy does not meet NIST standards. Critical patches pending on SRV-01.",
            ),
            _Doc("crew_log_2.txt", "2025-01-15 11:00 - Operator B: Lunch break."),
        ]
        kept = filter_supporting_docs(suggestion, docs)
        names = [d.metadata["source"] for d in kept]
        self.assertIn("findings.txt", names)
        self.assertNotIn("crew_log_2.txt", names)


if __name__ == "__main__":
    unittest.main()
