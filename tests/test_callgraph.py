"""
tests/test_callgraph.py

Unit tests for core/callgraph.py pure static 2-hop graph generator.
Fast, deterministic, zero-network.
"""

import sys
import os
import unittest
import tempfile
import shutil

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.callgraph import CallGraph

class TestCallGraph(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.src_dir = os.path.join(self.test_dir, "src")
        os.makedirs(self.src_dir, exist_ok=True)

        # File 1: Base leaf functions
        with open(os.path.join(self.src_dir, "leaf.cpp"), "w", encoding="utf-8") as f:
            f.write("""
int leaf_compute(int x) {
    return x + 42;
}
""")

        # File 2: 1-hop callers and callees
        with open(os.path.join(self.src_dir, "middle.cpp"), "w", encoding="utf-8") as f:
            f.write("""
int leaf_compute(int x);

int middle_step(int a) {
    return leaf_compute(a) * 2;
}
""")

        # File 3: 2-hop caller
        with open(os.path.join(self.src_dir, "top.cpp"), "w", encoding="utf-8") as f:
            f.write("""
int middle_step(int a);

void top_entry() {
    int res = middle_step(10);
}
""")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_callgraph_1_hop_and_2_hop_traversal(self):
        cg = CallGraph(self.test_dir)
        subgraph = cg.get_n_hop_subgraph("leaf_compute", max_hops=2)

        self.assertEqual(subgraph["target_function"], "leaf_compute")
        
        # 1-hop caller should be middle_step
        caller_names_1 = [c["name"] for c in subgraph["1_hop_callers"]]
        self.assertIn("middle_step", caller_names_1)
        
        # 2-hop caller should be top_entry
        caller_names_2 = [c["name"] for c in subgraph["2_hop_callers"]]
        self.assertIn("top_entry", caller_names_2)

    def test_callgraph_callees_traversal(self):
        cg = CallGraph(self.test_dir)
        subgraph = cg.get_n_hop_subgraph("top_entry", max_hops=2)

        callee_names_1 = [c["name"] for c in subgraph["1_hop_callees"]]
        self.assertIn("middle_step", callee_names_1)

        callee_names_2 = [c["name"] for c in subgraph["2_hop_callees"]]
        self.assertIn("leaf_compute", callee_names_2)

if __name__ == "__main__":
    unittest.main()
