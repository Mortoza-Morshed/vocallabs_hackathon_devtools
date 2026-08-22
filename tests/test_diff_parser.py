"""
tests/test_diff_parser.py

Unit tests for core/diff_parser.py using tree-sitter C++ AST parsing.
Fast, deterministic, zero-network.
"""

import sys
import os
import unittest
import tempfile
import shutil

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.diff_parser import parse_diff, ChangedFunction

class TestDiffParser(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.src_dir = os.path.join(self.test_dir, "src")
        os.makedirs(self.src_dir, exist_ok=True)

        self.cpp_file = os.path.join(self.src_dir, "sample.cpp")
        with open(self.cpp_file, "w", encoding="utf-8") as f:
            f.write("""#include <iostream>

int calculate_area(int width, int height) {
    if (width <= 0 || height <= 0) {
        return 0;
    }
    return width * height;
}

void print_report() {
    int a = calculate_area(5, 10);
    std::cout << a << std::endl;
}
""")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_parse_diff_identifies_modified_function(self):
        diff_text = """--- a/src/sample.cpp
+++ b/src/sample.cpp
@@ -4,3 +4,3 @@
-    if (width <= 0 || height <= 0) {
+    if (width < 0 || height < 0) {
         return 0;
"""
        changed = parse_diff(diff_text, self.test_dir)
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0].name, "calculate_area")
        self.assertIn("src/sample.cpp", changed[0].file_path.replace("\\", "/"))
        self.assertEqual(changed[0].start_line, 3)
        self.assertEqual(changed[0].end_line, 8)

    def test_parse_diff_with_no_cpp_changes(self):
        diff_text = """--- a/README.md
+++ b/README.md
@@ -1,2 +1,2 @@
-# Old Title
+# New Title
"""
        changed = parse_diff(diff_text, self.test_dir)
        self.assertEqual(len(changed), 0)

if __name__ == "__main__":
    unittest.main()
