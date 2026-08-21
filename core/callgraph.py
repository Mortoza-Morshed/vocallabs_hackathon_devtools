"""
core/callgraph.py

Builds a static call-graph for a C++ repository using tree-sitter-cpp.
Extracts function definitions, call expressions, and returns up to 2-hop callers & callees.
Pure static analysis — 0 LLM calls.
"""

import os
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Tuple
from tree_sitter import Language, Parser, Node
import tree_sitter_cpp

CPP_LANG = Language(tree_sitter_cpp.language())

def get_cpp_parser() -> Parser:
    return Parser(CPP_LANG)


@dataclass
class FunctionNode:
    name: str
    qualified_name: str
    file_path: str
    start_line: int
    end_line: int
    signature: str
    source_code: str
    callers: Set[str] = field(default_factory=set)
    callees: Set[str] = field(default_factory=set)

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "qualified_name": self.qualified_name,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "signature": self.signature,
            "source_code": self.source_code,
            "callers": sorted(list(self.callers)),
            "callees": sorted(list(self.callees)),
        }


class CallGraph:
    def __init__(self, repo_path: str):
        self.repo_path = os.path.abspath(repo_path)
        self.nodes: Dict[str, FunctionNode] = {}  # name or qualified_name -> FunctionNode
        self.name_map: Dict[str, Set[str]] = {}   # unqualified_name -> Set of keys in self.nodes
        self._build_callgraph()

    def _extract_called_function_name(self, call_node: Node) -> Optional[str]:
        """Extracts called function/method name from a call_expression node."""
        func_expr = call_node.child_by_field_name("function")
        if not func_expr:
            return None

        if func_expr.type == "identifier":
            return func_expr.text.decode('utf-8', errors='ignore')
        elif func_expr.type == "field_expression":
            # obj.method() or ptr->method()
            field_node = func_expr.child_by_field_name("field")
            if field_node:
                return field_node.text.decode('utf-8', errors='ignore')
        elif func_expr.type == "scoped_identifier":
            # namespace::func() or Class::func()
            return func_expr.text.decode('utf-8', errors='ignore')
        elif func_expr.type == "template_function":
            name_child = func_expr.child_by_field_name("name")
            if name_child:
                return name_child.text.decode('utf-8', errors='ignore')
        else:
            # fallback to first identifier
            for child in func_expr.children:
                if child.type in ("identifier", "field_identifier"):
                    return child.text.decode('utf-8', errors='ignore')
        
        return func_expr.text.decode('utf-8', errors='ignore').split('(')[0].strip()

    def _scan_file(self, rel_path: str, full_path: str):
        try:
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception:
            return

        parser = get_cpp_parser()
        source_bytes = content.encode('utf-8')
        tree = parser.parse(source_bytes)

        file_functions: List[Tuple[Node, str, str, str]] = []

        def traverse_defs(node: Node, scope_stack: List[str]):
            if node.type in ("class_specifier", "struct_specifier", "namespace_definition"):
                name_node = node.child_by_field_name("name")
                new_scope = scope_stack.copy()
                if name_node:
                    new_scope.append(name_node.text.decode('utf-8', errors='ignore'))
                body = node.child_by_field_name("body")
                children_to_visit = body.children if body else node.children
                for child in children_to_visit:
                    traverse_defs(child, new_scope)
                return

            if node.type in ("function_definition", "template_declaration"):
                func_node = node
                if node.type == "template_declaration":
                    for child in node.children:
                        if child.type == "function_definition":
                            func_node = child
                            break
                if func_node.type == "function_definition":
                    from core.diff_parser import extract_function_info
                    unqualified, qualified, sig = extract_function_info(func_node, source_bytes, scope_stack)
                    file_functions.append((func_node, unqualified, qualified, sig))
                    return

            for child in node.children:
                traverse_defs(child, scope_stack)

        traverse_defs(tree.root_node, [])

        # Store definitions in graph
        for func_node, unqualified, qualified, sig in file_functions:
            start_line = func_node.start_point[0] + 1
            end_line = func_node.end_point[0] + 1
            source_code = func_node.text.decode('utf-8', errors='ignore')

            node_obj = FunctionNode(
                name=unqualified,
                qualified_name=qualified,
                file_path=rel_path,
                start_line=start_line,
                end_line=end_line,
                signature=sig,
                source_code=source_code
            )

            key = qualified
            self.nodes[key] = node_obj
            self.name_map.setdefault(unqualified, set()).add(key)
            self.name_map.setdefault(qualified, set()).add(key)

            # Find calls inside func_node
            def traverse_calls(curr: Node):
                if curr.type == "call_expression":
                    called_name = self._extract_called_function_name(curr)
                    if called_name:
                        unqual_called = called_name.split("::")[-1]
                        node_obj.callees.add(unqual_called)

                for child in curr.children:
                    traverse_calls(child)

            body = func_node.child_by_field_name("body")
            if body:
                traverse_calls(body)

    def _build_callgraph(self):
        cpp_extensions = ('.cpp', '.hpp', '.cc', '.cxx', '.h', '.c', '.hh', '.h++')
        for root, _, files in os.walk(self.repo_path):
            for file in files:
                if file.lower().endswith(cpp_extensions):
                    full_path = os.path.join(root, file)
                    rel_path = os.path.relpath(full_path, self.repo_path)
                    self._scan_file(rel_path, full_path)

        # Invert callees to populate callers
        for key, node in list(self.nodes.items()):
            for callee_name in node.callees:
                matching_keys = self.name_map.get(callee_name, set())
                for target_key in matching_keys:
                    if target_key in self.nodes:
                        self.nodes[target_key].callers.add(node.name)
                        self.nodes[target_key].callers.add(node.qualified_name)

    def get_n_hop_subgraph(self, function_name: str, max_hops: int = 2) -> Dict:
        """
        Given a target function name or qualified name, returns callers and callees up to 2 hops deep.
        """
        matching_keys = self.name_map.get(function_name, set())
        if not matching_keys:
            # try fuzzy match
            matching_keys = {k for k, v in self.nodes.items() if v.name == function_name or v.qualified_name == function_name}

        if not matching_keys:
            return {
                "target_function": function_name,
                "found": False,
                "nodes": {},
                "1_hop_callers": [],
                "1_hop_callees": [],
                "2_hop_callers": [],
                "2_hop_callees": [],
            }

        visited_nodes: Dict[str, FunctionNode] = {}
        hop_1_callers: Set[str] = set()
        hop_1_callees: Set[str] = set()
        hop_2_callers: Set[str] = set()
        hop_2_callees: Set[str] = set()

        for key in matching_keys:
            target_node = self.nodes[key]
            visited_nodes[key] = target_node

            # Hop 1 Callers
            for caller_name in target_node.callers:
                for ckey in self.name_map.get(caller_name, set()):
                    if ckey in self.nodes:
                        c_node = self.nodes[ckey]
                        visited_nodes[ckey] = c_node
                        hop_1_callers.add(ckey)

            # Hop 1 Callees
            for callee_name in target_node.callees:
                for ckey in self.name_map.get(callee_name, set()):
                    if ckey in self.nodes:
                        c_node = self.nodes[ckey]
                        visited_nodes[ckey] = c_node
                        hop_1_callees.add(ckey)

        if max_hops >= 2:
            # Hop 2 Callers (callers of 1-hop callers)
            for ckey in list(hop_1_callers):
                c_node = visited_nodes[ckey]
                for c2_name in c_node.callers:
                    for c2key in self.name_map.get(c2_name, set()):
                        if c2key in self.nodes and c2key not in matching_keys and c2key not in hop_1_callers:
                            visited_nodes[c2key] = self.nodes[c2key]
                            hop_2_callers.add(c2key)

            # Hop 2 Callees (callees of 1-hop callees)
            for ckey in list(hop_1_callees):
                c_node = visited_nodes[ckey]
                for c2_name in c_node.callees:
                    for c2key in self.name_map.get(c2_name, set()):
                        if c2key in self.nodes and c2key not in matching_keys and c2key not in hop_1_callees:
                            visited_nodes[c2key] = self.nodes[c2key]
                            hop_2_callees.add(c2key)

        return {
            "target_function": function_name,
            "found": True,
            "target_nodes": [self.nodes[k].to_dict() for k in matching_keys],
            "1_hop_callers": [visited_nodes[k].to_dict() for k in hop_1_callers],
            "1_hop_callees": [visited_nodes[k].to_dict() for k in hop_1_callees],
            "2_hop_callers": [visited_nodes[k].to_dict() for k in hop_2_callers],
            "2_hop_callees": [visited_nodes[k].to_dict() for k in hop_2_callees],
            "all_nodes": {k: node.to_dict() for k, node in visited_nodes.items()}
        }


if __name__ == "__main__":
    print("[+] Testing core/callgraph.py standalone...")
    import tempfile, shutil

    temp_dir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(temp_dir, "src"), exist_ok=True)
        with open(os.path.join(temp_dir, "src", "math.cpp"), "w") as f:
            f.write("""
int helper(int x) { return x * 2; }
int callee_func(int v) { return helper(v) + 1; }
int target_func(int a, int b) { return callee_func(a) + b; }
int caller_func(int z) { return target_func(z, 5); }
int top_caller() { return caller_func(10); }
""")

        cg = CallGraph(temp_dir)
        slice_result = cg.get_n_hop_subgraph("target_func", max_hops=2)

        print(f"[+] Call graph slice for 'target_func':")
        print(f"    Target found: {slice_result['found']}")
        print(f"    1-hop callers: {[c['name'] for c in slice_result['1_hop_callers']]}")
        print(f"    1-hop callees: {[c['name'] for c in slice_result['1_hop_callees']]}")
        print(f"    2-hop callers: {[c['name'] for c in slice_result['2_hop_callers']]}")
        print(f"    2-hop callees: {[c['name'] for c in slice_result['2_hop_callees']]}")

        assert slice_result['found'] == True
        assert any(c['name'] == 'caller_func' for c in slice_result['1_hop_callers'])
        assert any(c['name'] == 'callee_func' for c in slice_result['1_hop_callees'])
        assert any(c['name'] == 'top_caller' for c in slice_result['2_hop_callers'])
        assert any(c['name'] == 'helper' for c in slice_result['2_hop_callees'])
        print("[+] core/callgraph.py tests completed successfully!")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
