"""
observability/cost_latency_log.py

Observability module for Blast Radius.
Logs token usage, estimated USD cost, and latency for every LLM model call to a local JSONL file.
Prints a clean terminal summary table at the end of each run.
"""

import os
import json
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

MODEL_PRICING = {
    # model_name: (input_per_1k, output_per_1k)
    "claude-3-5-sonnet": (0.003, 0.015),
    "claude-3-5-sonnet-20241022": (0.003, 0.015),
    "claude-3-haiku": (0.00025, 0.00125),
    "claude-3-haiku-20240307": (0.00025, 0.00125),
    "gpt-4o": (0.0025, 0.010),
    "gpt-4o-mini": (0.00015, 0.0006),
    "gemini-1.5-pro": (0.00125, 0.005),
    "gemini-1.5-flash": (0.000075, 0.0003),
    "gemini/gemini-1.5-pro-latest": (0.00125, 0.005),
    "gemini/gemini-1.5-flash-latest": (0.000075, 0.0003),
    "nemotron": (0.001, 0.003),
    "nemotron-4-340b-instruct": (0.001, 0.003),
    "nvidia": (0.001, 0.003),
}

DEFAULT_LOG_FILE = "observability/logs.jsonl"


def calculate_cost(model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculates estimated USD cost for a model call."""
    key = model_name.lower()
    rates = None
    for k, v in MODEL_PRICING.items():
        if k in key:
            rates = v
            break
    if not rates:
        # Default fallback rates ($1.50/1M input, $6.00/1M output)
        rates = (0.0015, 0.006)

    input_cost = (prompt_tokens / 1000.0) * rates[0]
    output_cost = (completion_tokens / 1000.0) * rates[1]
    return input_cost + output_cost


def log_model_call(
    model_name: str,
    role: str,
    prompt_tokens: int,
    completion_tokens: int,
    latency_seconds: float,
    log_file: str = DEFAULT_LOG_FILE
) -> Dict[str, Any]:
    """
    Appends a structured model invocation log to local JSONL file and returns the log record.
    """
    cost_usd = calculate_cost(model_name, prompt_tokens, completion_tokens)
    timestamp = datetime.now(timezone.utc).isoformat()

    record = {
        "timestamp": timestamp,
        "model": model_name,
        "role": role,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "latency_seconds": round(latency_seconds, 3),
        "cost_usd": round(cost_usd, 6)
    }

    os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    return record


def print_summary_table(records: List[Dict[str, Any]]):
    """
    Prints a clean formatted summary table of model invocations.
    """
    if not records:
        print("\n[+] Observability Summary: No LLM calls made (0 tokens, $0.00).")
        return

    print("\n" + "="*80)
    print(f"{'MODEL CALL OBSERVABILITY SUMMARY':^80}")
    print("="*80)
    header = f"{'Role':<18} | {'Model':<28} | {'Tokens (In/Out)':<15} | {'Latency':<9} | {'Cost ($)':<9}"
    print(header)
    print("-" * len(header))

    total_tokens = 0
    total_latency = 0.0
    total_cost = 0.0

    for r in records:
        role = r.get("role", "unknown")[:18]
        model = r.get("model", "unknown")[:28]
        in_tok = r.get("prompt_tokens", 0)
        out_tok = r.get("completion_tokens", 0)
        lat = r.get("latency_seconds", 0.0)
        cost = r.get("cost_usd", 0.0)

        total_tokens += (in_tok + out_tok)
        total_latency += lat
        total_cost += cost

        tok_str = f"{in_tok}/{out_tok}"
        print(f"{role:<18} | {model:<28} | {tok_str:<15} | {lat:>7.2f}s | ${cost:>8.5f}")

    print("-" * len(header))
    summary_line = f"{'TOTAL':<18} | {len(records)} calls{'':<21} | {total_tokens:<15} | {total_latency:>7.2f}s | ${total_cost:>8.5f}"
    print(summary_line)
    print("="*80 + "\n")


if __name__ == "__main__":
    print("[+] Testing observability/cost_latency_log.py standalone...")
    test_log = "observability/test_logs.jsonl"
    if os.path.exists(test_log):
        os.remove(test_log)

    r1 = log_model_call("claude-3-5-sonnet", "risk_model", 1200, 350, 1.45, log_file=test_log)
    r2 = log_model_call("claude-3-haiku", "crosscheck_model", 1550, 180, 0.62, log_file=test_log)

    print_summary_table([r1, r2])

    if os.path.exists(test_log):
        os.remove(test_log)

    print("[+] observability/cost_latency_log.py tests completed successfully!")
