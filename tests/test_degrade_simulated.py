"""
tests/test_degrade_simulated.py

Proves that simulated API timeouts and HTTP 429 rate limits force Blast Radius into
DEGRADED MODE (static analysis only, semantic risk not assessed) without crashing.
"""

import sys
import os
import unittest
from unittest.mock import patch

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.diff_parser import parse_diff
from core.callgraph import CallGraph
from core.degrade import execute_with_degrade_protection

class TestDegradedMode(unittest.TestCase):

    def setUp(self):
        self.repo_dir = os.path.abspath("smoke_test/repo")
        self.diff_path = os.path.abspath("smoke_test/pr.diff")
        with open(self.diff_path, "r", encoding="utf-8") as f:
            self.diff_text = f.read()

        self.changed_funcs = parse_diff(self.diff_text, self.repo_dir)
        cg = CallGraph(self.repo_dir)
        self.cg_slices = [cg.get_n_hop_subgraph(cf.name, max_hops=2) for cf in self.changed_funcs]

    def test_simulated_api_timeout_triggers_degraded_mode(self):
        """Simulates an API Timeout and confirms graceful degraded mode fallback."""
        def failing_llm_pipeline():
            import litellm
            raise litellm.Timeout(message="Simulated API timeout after 60s", model="gemini-2.5-flash", llm_provider="gemini")

        result = execute_with_degrade_protection(
            failing_llm_pipeline,
            self.changed_funcs,
            self.cg_slices
        )

        self.assertTrue(result.is_degraded)
        self.assertIn("DEGRADED MODE", result.degraded_reason)
        self.assertEqual(len(result.risks), 1)
        self.assertEqual(result.risks[0]["affected_function"], "compute_velocity")
        self.assertEqual(result.risks[0]["confidence_score"], 0)
        self.assertIn("update_entity_speed", result.risks[0]["reasoning"])
        print("\n[+] Verified Degraded Mode on Simulated Timeout:")
        print(f"    Reason: {result.degraded_reason}")
        print(f"    Fallback Slice Risk: {result.risks[0]['description']}")

    def test_simulated_http_429_rate_limit_triggers_degraded_mode(self):
        """Simulates an HTTP 429 RateLimit and confirms graceful degraded mode fallback."""
        def failing_llm_pipeline():
            import litellm
            raise litellm.RateLimitError(
                message="ResourceExhausted: 429 Quota exceeded for free tier requests",
                llm_provider="gemini",
                model="gemini-2.5-flash"
            )

        result = execute_with_degrade_protection(
            failing_llm_pipeline,
            self.changed_funcs,
            self.cg_slices
        )

        self.assertTrue(result.is_degraded)
        self.assertIn("DEGRADED MODE", result.degraded_reason)
        self.assertEqual(len(result.risks), 1)
        self.assertEqual(result.risks[0]["confidence_score"], 0)
        print("\n[+] Verified Degraded Mode on Simulated HTTP 429 RateLimit:")
        print(f"    Reason: {result.degraded_reason}")
        print(f"    Fallback Slice Risk: {result.risks[0]['description']}")

if __name__ == "__main__":
    unittest.main()
