"""
core/diff_parser.py

Parses unified diff files and maps modified line numbers to C++ function/method definitions
using tree-sitter-cpp.
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Set, Tuple
from tree_sitter import Language, Parser, Node
import tree_sitter_cpp

# Initialize C++ Tree-Sitter Parser
CPP_LANG = Language(tree_sitter_cpp.language())

def get_cpp_parser() -> Parser:
    return Parser(CPP_LANG)


@dataclass
class ChangedFunction:
    name: str
    qualified_name: str
    file_path: str
    start_line: int  # 1-indexed
    end_line: int    # 1-indexed
    signature: str
    changed_lines: List[int] = field(default_factory=list)
    diff_hunk: str = ""

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "qualified_name": self.qualified_name,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "signature": self.signature,
            "changed_lines": self.changed_lines,
            "diff_hunk": self.diff_hunk,
        }


@dataclass
class DiffHunk:
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    header: str
    lines: List[Tuple[str, str]]  # (op, line_content) where op is '+', '-', ' '


@dataclass
class FileDiff:
    old_path: Optional[str]
    new_path: Optional[str]
    hunks: List[DiffHunk] = field(default_factory=list)

    @property
    def added_and_modified_lines(self) -> List[int]:
        """Returns list of line numbers (in new file) that were added or modified."""
        result = []
        for hunk in self.hunks:
            curr_new = hunk.new_start
            for op, content in hunk.lines:
                if op == '+':
                    result.append(curr_new)
                    curr_new += 1
                elif op == ' ':
                    curr_new += 1
                elif op == '-':
                    result.append(max(1, curr_new))
        return sorted(list(set(result)))


def parse_unified_diff(diff_text: str) -> List[FileDiff]:
    """Parses a unified diff string into FileDiff structures."""
    files: List[FileDiff] = []
    current_file: Optional[FileDiff] = None
    current_hunk: Optional[DiffHunk] = None

    diff_file_re = re.compile(r"^diff --git a/(.*) b/(.*)")
    hunk_header_re = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)")

    lines = diff_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        
        file_match = diff_file_re.match(line)
        if file_match:
            if current_file:
                files.append(current_file)
            current_file = FileDiff(old_path=file_match.group(1), new_path=file_match.group(2))
            current_hunk = None
            i += 1
            continue

        if line.startswith("--- a/"):
            if not current_file:
                current_file = FileDiff(old_path=line[6:], new_path=None)
            else:
                current_file.old_path = line[6:]
            i += 1
            continue
        elif line.startswith("+++ b/"):
            if not current_file:
                current_file = FileDiff(old_path=None, new_path=line[6:])
            else:
                current_file.new_path = line[6:]
            i += 1
            continue

        hunk_match = hunk_header_re.match(line)
        if hunk_match and current_file:
            old_start = int(hunk_match.group(1))
            old_lines = int(hunk_match.group(2)) if hunk_match.group(2) is not None else 1
            new_start = int(hunk_match.group(3))
            new_lines = int(hunk_match.group(4)) if hunk_match.group(4) is not None else 1
            header = hunk_match.group(5).strip()

            current_hunk = DiffHunk(
                old_start=old_start,
                old_lines=old_lines,
                new_start=new_start,
                new_lines=new_lines,
                header=header,
                lines=[]
            )
            current_file.hunks.append(current_hunk)
            i += 1
            continue

        if current_hunk is not None:
            if line.startswith('+'):
                current_hunk.lines.append(('+', line[1:]))
            elif line.startswith('-'):
                current_hunk.lines.append(('-', line[1:]))
            elif line.startswith(' '):
                current_hunk.lines.append((' ', line[1:]))
            elif line.startswith('\\ No newline at end of file'):
                pass

        i += 1

    if current_file and current_file not in files:
        files.append(current_file)

    return files


def extract_function_info(node: Node, source_bytes: bytes, scope_stack: List[str]) -> Tuple[str, str, str]:
    """
    Extracts (unqualified_name, qualified_name, signature) from a C++ function_definition node.
    """
    declarator = node.child_by_field_name("declarator")
    raw_sig = node.text.decode('utf-8', errors='ignore').split('{')[0].strip()

    name = "unknown"
    if declarator:
        curr = declarator
        while curr:
            if curr.type in ("function_declarator", "pointer_declarator", "reference_declarator", "array_declarator"):
                curr = curr.child_by_field_name("declarator")
            elif curr.type == "qualified_identifier":
                name = curr.text.decode('utf-8', errors='ignore')
                break
            elif curr.type in ("identifier", "field_identifier", "destructor_name"):
                name = curr.text.decode('utf-8', errors='ignore')
                break
            else:
                found = False
                for child in curr.children:
                    if child.type in ("identifier", "field_identifier", "qualified_identifier"):
                        name = child.text.decode('utf-8', errors='ignore')
                        found = True
                        break
                if not found and curr.named_children:
                    curr = curr.named_children[0]
                else:
                    break

    unqualified_name = name.split("::")[-1] if "::" in name else name
    
    if "::" in name:
        qualified_name = name
    elif scope_stack:
        qualified_name = "::".join(scope_stack + [unqualified_name])
    else:
        qualified_name = unqualified_name

    return unqualified_name, qualified_name, raw_sig


def find_cpp_functions(file_content: str) -> List[Dict]:
    """
    Parses C++ source code with tree-sitter and returns details for all functions/methods found.
    """
    parser = get_cpp_parser()
    source_bytes = file_content.encode('utf-8')
    tree = parser.parse(source_bytes)

    functions = []

    def traverse(node: Node, scope_stack: List[str]):
        if node.type in ("class_specifier", "struct_specifier", "namespace_definition"):
            name_node = node.child_by_field_name("name")
            new_scope = scope_stack.copy()
            if name_node:
                new_scope.append(name_node.text.decode('utf-8', errors='ignore'))
            
            body = node.child_by_field_name("body")
            children_to_visit = body.children if body else node.children
            for child in children_to_visit:
                traverse(child, new_scope)
            return

        if node.type in ("function_definition", "template_declaration"):
            func_node = node
            if node.type == "template_declaration":
                for child in node.children:
                    if child.type == "function_definition":
                        func_node = child
                        break
            
            if func_node.type == "function_definition":
                unqualified, qualified, sig = extract_function_info(func_node, source_bytes, scope_stack)
                start_line = func_node.start_point[0] + 1
                end_line = func_node.end_point[0] + 1
                
                functions.append({
                    "name": unqualified,
                    "qualified_name": qualified,
                    "start_line": start_line,
                    "end_line": end_line,
                    "signature": sig,
                    "node": func_node,
                    "source": func_node.text.decode('utf-8', errors='ignore')
                })
                return

        for child in node.children:
            traverse(child, scope_stack)

    traverse(tree.root_node, [])
    return functions


def parse_diff(diff_text: str, repo_path: str) -> List[ChangedFunction]:
    """
    Given a unified diff text and local repo path, extracts all changed C++ functions/methods.
    """
    file_diffs = parse_unified_diff(diff_text)
    changed_functions: List[ChangedFunction] = []

    cpp_extensions = ('.cpp', '.hpp', '.cc', '.cxx', '.h', '.c', '.hh', '.h++')

    for file_diff in file_diffs:
        rel_path = file_diff.new_path or file_diff.old_path
        if not rel_path:
            continue

        if not rel_path.lower().endswith(cpp_extensions):
            continue

        full_path = os.path.join(repo_path, rel_path)
        if not os.path.isfile(full_path):
            continue

        try:
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception:
            continue

        parsed_funcs = find_cpp_functions(content)
        changed_lines = file_diff.added_and_modified_lines

        hunk_texts = []
        for hunk in file_diff.hunks:
            hunk_texts.append(f"@@ -{hunk.old_start},{hunk.old_lines} +{hunk.new_start},{hunk.new_lines} @@")
            for op, line_str in hunk.lines:
                hunk_texts.append(f"{op}{line_str}")
        full_file_hunk = "\n".join(hunk_texts)

        for func in parsed_funcs:
            overlapping_lines = [l for l in changed_lines if func["start_line"] <= l <= func["end_line"]]
            if overlapping_lines:
                changed_functions.append(
                    ChangedFunction(
                        name=func["name"],
                        qualified_name=func["qualified_name"],
                        file_path=rel_path,
                        start_line=func["start_line"],
                        end_line=func["end_line"],
                        signature=func["signature"],
                        changed_lines=overlapping_lines,
                        diff_hunk=full_file_hunk
                    )
                )

    return changed_functions


if __name__ == "__main__":
    print("[+] Testing core/diff_parser.py standalone...")
    sample_diff = """diff --git a/src/math_utils.cpp b/src/math_utils.cpp
index 1234567..89abcdef 100644
--- a/src/math_utils.cpp
+++ b/src/math_utils.cpp
@@ -5,6 +5,7 @@ int add(int a, int b) {
 }
 
 double divide(double a, double b) {
+    if (b == 0) return 0.0;
     return a / b;
 }
"""

    os.makedirs("scratch_test/src", exist_ok=True)
    sample_cpp = """#include <iostream>

int add(int a, int b) {
    return a + b;
}

double divide(double a, double b) {
    if (b == 0) return 0.0;
    return a / b;
}
"""
    with open("scratch_test/src/math_utils.cpp", "w", encoding="utf-8") as f:
        f.write(sample_cpp)

    results = parse_diff(sample_diff, "scratch_test")
    print(f"[+] Found {len(results)} changed functions:")
    for fn in results:
        print(f"  - {fn.qualified_name} ({fn.file_path}:{fn.start_line}-{fn.end_line})")
        print(f"    Changed lines: {fn.changed_lines}")
        print(f"    Signature: {fn.signature}")

    import shutil
    shutil.rmtree("scratch_test", ignore_errors=True)
    print("[+] core/diff_parser.py tests completed successfully!")
