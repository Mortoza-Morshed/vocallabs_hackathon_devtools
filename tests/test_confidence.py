"""
tests/test_confidence.py

Unit tests for core/confidence.py scoring and human review rules.
Fast, deterministic, zero-network.
"""

import sys
import os
import unittest

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.confidence import compute_confidence_scores

class TestConfidence(unittest.TestCase):

    def test_agreement_scores_high_confidence(self):
        """When risk and crosscheck model agree, score should be >= 80."""
        risks = [
            {
                "description": "Critical breaking contract in `parse_header`",
                "affected_function": "parse_header",
                "severity": "high",
                "reasoning": "Removed null check directly in call graph"
            }
        ]
        checks = [
            {
                "risk_index": 0,
                "agrees": True,
                "note": "Agreed, caller passes null."
            }
        ]

        scored = compute_confidence_scores(risks, checks, confidence_threshold=50)
        self.assertEqual(len(scored), 1)
        self.assertGreaterEqual(scored[0].confidence_score, 80)
        self.assertFalse(scored[0].needs_human_review)
        self.assertEqual(scored[0].crosscheck_status, "agreed")
        self.assertEqual(scored[0].status, "CONFIRMED RISK")

    def test_disagreement_penalizes_and_flags_human_review(self):
        """When crosscheck model disagrees, score drops below threshold and flags review."""
        risks = [
            {
                "description": "Ambiguous stylistic difference",
                "affected_function": "compute_opt",
                "severity": "low",
                "reasoning": "Might possibly change internal order"
            }
        ]
        checks = [
            {
                "risk_index": 0,
                "agrees": False,
                "note": "Disagreed, semantic contracts are preserved."
            }
        ]

        scored = compute_confidence_scores(risks, checks, confidence_threshold=50)
        self.assertEqual(len(scored), 1)
        self.assertLess(scored[0].confidence_score, 50)
        self.assertTrue(scored[0].needs_human_review)
        self.assertEqual(scored[0].crosscheck_status, "disagreed")
        self.assertEqual(scored[0].status, "NEEDS HUMAN REVIEW")

if __name__ == "__main__":
    unittest.main()
