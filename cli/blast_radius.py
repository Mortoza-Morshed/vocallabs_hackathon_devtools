"""
cli/blast_radius.py

CLI entry point for Blast Radius: C++ PR Semantic Risk Analyzer.
Usage:
  blast-radius analyze <repo-path> <pr-diff-file> [options]
"""

import sys
import os
import json
import argparse
from typing import List, Dict, Any

from dotenv import load_dotenv
load_dotenv()
os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.diff_parser import parse_diff
from core.callgraph import CallGraph
from core.context_slicer import build_context_bundle
from core.risk_model import run_risk_model
from core.crosscheck_model import run_crosscheck_model
from core.confidence import compute_confidence_scores
from core.degrade import execute_with_degrade_protection, DEGRADED_LABEL
from observability.cost_latency_log import log_model_call, print_summary_table


def format_human_report(
    repo_path: str,
    diff_file: str,
    pipeline_res: Dict[str, Any],
    log_records: List[Dict[str, Any]]
) -> str:
    lines = []
    lines.append("=" * 80)
    lines.append(f"{'BLAST RADIUS: C++ PR SEMANTIC RISK ANALYZER':^80}")
    lines.append("=" * 80)
    lines.append(f"Target Repo : {os.path.abspath(repo_path)}")
    lines.append(f"PR Diff File: {os.path.abspath(diff_file)}")

    is_degraded = pipeline_res.get("is_degraded", False)
    degraded_reason = pipeline_res.get("degraded_reason", "")

    if is_degraded:
        lines.append("")
        lines.append("!" * 80)
        lines.append(f" [!] {DEGRADED_LABEL}")
        if degraded_reason:
            lines.append(f"     Reason: {degraded_reason}")
        lines.append("!" * 80)

    changed_funcs = pipeline_res.get("changed_functions", [])
    lines.append("\n" + "-" * 80)
    lines.append(f"1. CHANGED C++ FUNCTIONS DETECTED ({len(changed_funcs)})")
    lines.append("-" * 80)
    if changed_funcs:
        for cf in changed_funcs:
            name = cf.get("qualified_name") or cf.get("name")
            fpath = cf.get("file_path", "")
            s_line = cf.get("start_line", 0)
            e_line = cf.get("end_line", 0)
            lines.append(f"  • {name:<35} | {fpath}:{s_line}-{e_line}")
    else:
        lines.append("  (No modified C++ functions detected in diff)")

    risks = pipeline_res.get("risks", [])
    lines.append("\n" + "-" * 80)
    lines.append(f"2. DOWNSTREAM SEMANTIC RISKS & CONTRACT VIOLATIONS ({len(risks)})")
    lines.append("-" * 80)

    if not risks:
        lines.append("  [✓] No downstream behavioral contract breakages detected.")
    else:
        for idx, r in enumerate(risks, 1):
            sev = str(r.get("severity", "medium")).upper()
            score = r.get("confidence_score", 0)
            status = r.get("status", "UNKNOWN")
            aff_fn = r.get("affected_function", "unknown")
            desc = r.get("description", "")
            reason = r.get("reasoning", "")
            cc_status = r.get("crosscheck_status", "unverified")
            cc_note = r.get("crosscheck_note", "")

            sev_badge = f"[{sev} SEVERITY]"
            lines.append(f"\nRisk #{idx}: {sev_badge} {desc}")
            lines.append(f"  • Affected Component : `{aff_fn}`")
            lines.append(f"  • Confidence Score   : {score}/100 -> STATUS: {status}")
            lines.append(f"  • Crosscheck Audit   : {cc_status.upper()}")
            if cc_note:
                lines.append(f"    Audit Note         : {cc_note}")
            lines.append(f"  • Technical Reasoning:\n    {reason}")
            lines.append("  " + "-" * 76)

    return "\n".join(lines)


def run_analyze(args):
    if not os.path.exists(args.repo_path):
        print(f"[!] Error: Repository path '{args.repo_path}' does not exist.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.diff_file):
        print(f"[!] Error: PR diff file '{args.diff_file}' does not exist.", file=sys.stderr)
        sys.exit(1)

    with open(args.diff_file, "r", encoding="utf-8", errors="ignore") as f:
        diff_text = f.read()

    changed_funcs = parse_diff(diff_text, args.repo_path)
    cg = CallGraph(args.repo_path)

    cg_slices = []
    for cf in changed_funcs:
        slice_res = cg.get_n_hop_subgraph(cf.name, max_hops=2)
        cg_slices.append(slice_res)

    bundle = build_context_bundle(changed_funcs, cg_slices, diff_text, token_budget=args.token_budget)

    log_records = []

    def llm_execution_pipeline():
        # Check API Keys
        api_available = any(k in os.environ for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "NVIDIA_API_KEY", "NEMOTRON_API_KEY", "NVIDIA_NIM_API_KEY"))
        if not api_available:
            raise RuntimeError("No LLM API key configured (set ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY, NVIDIA_API_KEY, NEMOTRON_API_KEY, or NVIDIA_NIM_API_KEY)")

        r_out = run_risk_model(bundle.formatted_context, model_name=args.risk_model)
        r_log = log_model_call(
            model_name=r_out["model"],
            role="risk_model",
            prompt_tokens=r_out["prompt_tokens"],
            completion_tokens=r_out["completion_tokens"],
            latency_seconds=r_out["latency"],
            log_file=args.log_file
        )
        log_records.append(r_log)

        c_out = run_crosscheck_model(bundle.formatted_context, r_out["risks"], model_name=args.crosscheck_model)
        c_log = log_model_call(
            model_name=c_out["model"],
            role="crosscheck_model",
            prompt_tokens=c_out["prompt_tokens"],
            completion_tokens=c_out["completion_tokens"],
            latency_seconds=c_out["latency"],
            log_file=args.log_file
        )
        log_records.append(c_log)

        evaluated = compute_confidence_scores(r_out["risks"], c_out["checks"], confidence_threshold=args.confidence_threshold)

        total_cost = r_log["cost_usd"] + c_log["cost_usd"]
        total_lat = r_log["latency_seconds"] + c_log["latency_seconds"]

        return {
            "is_degraded": False,
            "risks": [e.to_dict() for e in evaluated],
            "token_count": bundle.total_tokens,
            "cost_usd": total_cost,
            "latency_seconds": total_lat,
            "model_info": {"risk_model": r_out["model"], "crosscheck_model": c_out["model"]}
        }

    pipeline_result = execute_with_degrade_protection(llm_execution_pipeline, changed_funcs, cg_slices)

    if args.json:
        out_dict = pipeline_result.to_dict()
        out_dict["log_records"] = log_records
        print(json.dumps(out_dict, indent=2))
    else:
        report_str = format_human_report(args.repo_path, args.diff_file, pipeline_result.to_dict(), log_records)
        print(report_str)
        print_summary_table(log_records)


def main():
    parser = argparse.ArgumentParser(prog="blast-radius", description="Blast Radius: C++ PR Semantic Risk Analyzer")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    analyze_parser = subparsers.add_parser("analyze", help="Analyze a C++ PR diff against a repository")
    analyze_parser.add_argument("repo_path", help="Path to local target git repo clone")
    analyze_parser.add_argument("diff_file", help="Path to PR diff file (unified diff format)")
    analyze_parser.add_argument("--token-budget", type=int, default=8000, help="Max token budget for context bundle (default: 8000)")
    analyze_parser.add_argument("--confidence-threshold", type=int, default=50, help="Confidence threshold below which risks flag for human review (default: 50)")
    analyze_parser.add_argument("--risk-model", default="claude-3-5-sonnet-20241022", help="Primary risk model (default: claude-3-5-sonnet-20241022)")
    analyze_parser.add_argument("--crosscheck-model", default="claude-3-haiku-20240307", help="Secondary crosscheck model (default: claude-3-haiku-20240307)")
    analyze_parser.add_argument("--json", action="store_true", help="Output raw JSON format")
    analyze_parser.add_argument("--log-file", default="observability/logs.jsonl", help="Path to JSONL observability log file")

    args = parser.parse_args()

    if args.command == "analyze":
        run_analyze(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
