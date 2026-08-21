"""
core/degrade.py

Graceful degraded mode fallback handler for Blast Radius.
Wraps all LLM execution calls. On network failure, timeout, rate-limiting, missing API keys,
or invalid responses, it falls back to callgraph-only static analysis and labels the report
with "DEGRADED MODE: static analysis only, semantic risk not assessed".
"""

import sys
import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Callable, Optional

DEGRADED_LABEL = "DEGRADED MODE: static analysis only, semantic risk not assessed"

logger = logging.getLogger("blast_radius.degrade")


@dataclass
class PipelineResult:
    is_degraded: bool
    degraded_reason: Optional[str]
    changed_functions: List[Dict[str, Any]]
    callgraph_slices: List[Dict[str, Any]]
    risks: List[Dict[str, Any]]
    token_count: int
    cost_usd: float
    latency_seconds: float
    model_info: Dict[str, str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_degraded": self.is_degraded,
            "degraded_label": DEGRADED_LABEL if self.is_degraded else None,
            "degraded_reason": self.degraded_reason,
            "changed_functions": self.changed_functions,
            "callgraph_slices": self.callgraph_slices,
            "risks": self.risks,
            "token_count": self.token_count,
            "cost_usd": self.cost_usd,
            "latency_seconds": self.latency_seconds,
            "model_info": self.model_info,
        }


def execute_with_degrade_protection(
    pipeline_fn: Callable[[], Dict[str, Any]],
    changed_functions: List[Any],
    callgraph_slices: List[Dict[str, Any]]
) -> PipelineResult:
    """
    Executes the LLM pipeline function. If an exception occurs, cleanly catches it
    and returns a degraded pipeline result with static callgraph information intact.
    """
    cf_dicts = [cf.to_dict() if hasattr(cf, "to_dict") else cf for cf in changed_functions]

    try:
        res = pipeline_fn()
        return PipelineResult(
            is_degraded=res.get("is_degraded", False),
            degraded_reason=res.get("degraded_reason"),
            changed_functions=cf_dicts,
            callgraph_slices=callgraph_slices,
            risks=res.get("risks", []),
            token_count=res.get("token_count", 0),
            cost_usd=res.get("cost_usd", 0.0),
            latency_seconds=res.get("latency_seconds", 0.0),
            model_info=res.get("model_info", {})
        )
    except Exception as e:
        error_msg = str(e)
        logger.warning(f"[!] Pipeline failure triggering DEGRADED MODE: {error_msg}")

        # Static callgraph fallback summary
        static_risks = []
        for cf in cf_dicts:
            func_name = cf.get("name", "unknown")
            # Find callgraph slice for this function
            matching_slice = next((s for s in callgraph_slices if s.get("target_function") == func_name), None)
            callers_1hop = [c["name"] for c in matching_slice.get("1_hop_callers", [])] if matching_slice else []
            callees_1hop = [c["name"] for c in matching_slice.get("1_hop_callees", [])] if matching_slice else []

            static_risks.append({
                "description": f"Static analysis slice for `{func_name}` (Callers: {len(callers_1hop)}, Callees: {len(callees_1hop)})",
                "affected_function": func_name,
                "severity": "medium",
                "reasoning": f"Downstream impact unassessed due to degraded mode. Direct callers: {', '.join(callers_1hop) if callers_1hop else 'none'}",
                "confidence_score": 0,
                "crosscheck_status": "unverified",
                "crosscheck_note": "LLM analysis failed or unconfigured.",
                "needs_human_review": True,
                "status": "DEGRADED MODE"
            })

        return PipelineResult(
            is_degraded=True,
            degraded_reason=f"{DEGRADED_LABEL} ({error_msg})",
            changed_functions=cf_dicts,
            callgraph_slices=callgraph_slices,
            risks=static_risks,
            token_count=0,
            cost_usd=0.0,
            latency_seconds=0.0,
            model_info={"risk_model": "none (degraded)", "crosscheck_model": "none (degraded)"}
        )


if __name__ == "__main__":
    print("[+] Testing core/degrade.py standalone...")

    dummy_cf = [{"name": "foo", "file_path": "foo.cpp", "start_line": 1, "end_line": 5}]
    dummy_cg = [{"target_function": "foo", "found": True, "1_hop_callers": [{"name": "bar"}]}]

    def failing_pipeline():
        raise RuntimeError("API Rate Limit Exceeded (429)")

    result = execute_with_degrade_protection(failing_pipeline, dummy_cf, dummy_cg)

    print(f"[+] Is Degraded: {result.is_degraded}")
    print(f"[+] Degraded Reason: {result.degraded_reason}")
    print(f"[+] Risks count: {len(result.risks)}")
    print(f"[+] Risk 0 status: {result.risks[0]['status']}")

    assert result.is_degraded == True
    assert DEGRADED_LABEL in result.degraded_reason
    assert result.risks[0]['status'] == "DEGRADED MODE"

    print("[+] core/degrade.py tests completed successfully!")
