"""
core/context_slicer.py

Packs diff parser output and 2-hop callgraph slices into a trimmed context bundle
capped at a configurable token budget (default: 8000 tokens).
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

try:
    import tiktoken
    _TOKENIZER = tiktoken.get_encoding("cl100k_base")
    def count_tokens(text: str) -> int:
        return len(_TOKENIZER.encode(text))
except Exception:
    def count_tokens(text: str) -> int:
        # Fallback estimation ~ 4 chars per token
        return max(1, len(text) // 4)


@dataclass
class ContextBundle:
    formatted_context: str
    total_tokens: int
    token_budget: int
    truncated: bool
    changed_functions: List[str]
    callgraph_summary: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "formatted_context": self.formatted_context,
            "total_tokens": self.total_tokens,
            "token_budget": self.token_budget,
            "truncated": self.truncated,
            "changed_functions": self.changed_functions,
            "callgraph_summary": self.callgraph_summary,
        }


def build_context_bundle(
    changed_functions: List[Any],
    callgraph_slices: List[Dict[str, Any]],
    raw_diff: str,
    token_budget: int = 8000
) -> ContextBundle:
    """
    Assembles PR diff and 2-hop call-graph slices into a string context under token_budget.
    """
    sections = []
    
    # Priority 1: PR Diff
    diff_section = f"### UNIFIED PR DIFF ###\n```diff\n{raw_diff.strip()}\n```\n"
    current_tokens = count_tokens(diff_section)

    # Priority 2: Changed Functions Details
    cf_text_blocks = ["### CHANGED FUNCTIONS ###"]
    func_names = []
    for cf in changed_functions:
        name = cf.qualified_name if hasattr(cf, "qualified_name") else cf.get("qualified_name", cf.get("name", "unknown"))
        func_names.append(name)
        file_path = cf.file_path if hasattr(cf, "file_path") else cf.get("file_path", "")
        start_line = cf.start_line if hasattr(cf, "start_line") else cf.get("start_line", 0)
        end_line = cf.end_line if hasattr(cf, "end_line") else cf.get("end_line", 0)
        sig = cf.signature if hasattr(cf, "signature") else cf.get("signature", "")
        
        block = f"- Function: `{name}` in `{file_path}` (lines {start_line}-{end_line})\n  Signature: `{sig}`"
        cf_text_blocks.append(block)
    
    cf_section = "\n".join(cf_text_blocks) + "\n\n"
    
    if current_tokens + count_tokens(cf_section) <= token_budget:
        sections.append(cf_section)
        current_tokens += count_tokens(cf_section)

    sections.append(diff_section)

    # Priority 3: 1-Hop Callers & Callees
    hop1_blocks = ["### 1-HOP CALLGRAPH SLICE (Direct Callers & Callees) ###"]
    hop2_blocks = ["### 2-HOP CALLGRAPH SLICE (Indirect Callers & Callees) ###"]
    
    summary = {"1_hop_nodes": 0, "2_hop_nodes": 0}
    seen_nodes = set()

    for cg_slice in callgraph_slices:
        if not cg_slice.get("found"):
            continue

        # 1-hop
        for node in cg_slice.get("1_hop_callers", []) + cg_slice.get("1_hop_callees", []):
            node_key = f"{node['file_path']}:{node['name']}"
            if node_key not in seen_nodes:
                seen_nodes.add(node_key)
                summary["1_hop_nodes"] += 1
                hop1_blocks.append(
                    f"#### Node: `{node['qualified_name']}` ({node['file_path']}:{node['start_line']}-{node['end_line']})\n"
                    f"```cpp\n{node['source_code'].strip()}\n```\n"
                )

        # 2-hop
        for node in cg_slice.get("2_hop_callers", []) + cg_slice.get("2_hop_callees", []):
            node_key = f"{node['file_path']}:{node['name']}"
            if node_key not in seen_nodes:
                seen_nodes.add(node_key)
                summary["2_hop_nodes"] += 1
                hop2_blocks.append(
                    f"#### Node: `{node['qualified_name']}` ({node['file_path']}:{node['start_line']}-{node['end_line']})\n"
                    f"```cpp\n{node['source_code'].strip()}\n```\n"
                )

    truncated = False

    # Add 1-hop blocks within budget
    for block in hop1_blocks:
        b_tokens = count_tokens(block + "\n")
        if current_tokens + b_tokens <= token_budget:
            sections.append(block + "\n")
            current_tokens += b_tokens
        else:
            truncated = True
            sections.append("\n[... Truncated 1-hop callgraph nodes due to token budget limit ...]\n")
            break

    # Add 2-hop blocks within budget if not truncated
    if not truncated:
        for block in hop2_blocks:
            b_tokens = count_tokens(block + "\n")
            if current_tokens + b_tokens <= token_budget:
                sections.append(block + "\n")
                current_tokens += b_tokens
            else:
                truncated = True
                sections.append("\n[... Truncated 2-hop callgraph nodes due to token budget limit ...]\n")
                break

    full_context = "\n".join(sections)
    final_token_count = count_tokens(full_context)

    return ContextBundle(
        formatted_context=full_context,
        total_tokens=final_token_count,
        token_budget=token_budget,
        truncated=truncated,
        changed_functions=func_names,
        callgraph_summary=summary
    )


if __name__ == "__main__":
    print("[+] Testing core/context_slicer.py standalone...")
    from core.diff_parser import ChangedFunction

    cf = ChangedFunction(
        name="divide",
        qualified_name="divide",
        file_path="src/math.cpp",
        start_line=10,
        end_line=15,
        signature="double divide(double a, double b)",
        changed_lines=[12],
        diff_hunk="@@ -10,5 +10,6 @@\n+ if (b == 0) return 0.0;"
    )

    cg_slice = {
        "found": True,
        "1_hop_callers": [{
            "name": "calculate_ratio",
            "qualified_name": "calculate_ratio",
            "file_path": "src/stats.cpp",
            "start_line": 20,
            "end_line": 25,
            "signature": "double calculate_ratio(double x, double y)",
            "source_code": "double calculate_ratio(double x, double y) { return divide(x, y); }"
        }],
        "1_hop_callees": [],
        "2_hop_callers": [],
        "2_hop_callees": []
    }

    bundle = build_context_bundle([cf], [cg_slice], "diff --git a/src/math.cpp b/src/math.cpp\n...", token_budget=500)
    print(f"[+] Bundle total tokens: {bundle.total_tokens} / {bundle.token_budget}")
    print(f"[+] Truncated: {bundle.truncated}")
    print(f"[+] Formatted Context Preview:\n{bundle.formatted_context[:250]}...")
    assert bundle.total_tokens <= 500
    print("[+] core/context_slicer.py tests completed successfully!")
