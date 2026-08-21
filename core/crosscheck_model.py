"""
core/crosscheck_model.py

Secondary crosscheck analyzer module. Calls a small/cheap LLM (Haiku-class / Gemini Flash / GPT-4o-mini / Ollama)
with the SAME context bundle + risk_model JSON output to independently verify each claimed risk.
Returns STRICT JSON matching:
{
  "checks": [
    {
      "risk_index": int,
      "agrees": bool,
      "note": str
    }
  ]
}
"""

import os
import json
import time
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

SYSTEM_PROMPT = """You are an independent peer reviewer software auditor tool called Blast Radius Crosschecker.
Your job is to independently evaluate a list of predicted downstream risks produced by a primary risk model for a C++ Pull Request.

CRITICAL INSTRUCTIONS:
1. Examine the provided PR diff, 2-hop call graph slice, and the list of claimed risks.
2. For each risk (0-indexed by its position in the list), evaluate if it represents a REAL downstream behavioral breakage or if it is a false alarm / hallucination.
3. Be skeptical: if the risk claims a contract break that isn't supported by the call graph or code diff, set `agrees: false`.
4. Respond with STRICT JSON ONLY. No preamble, no markdown wrappers, no postscript.

EXPECTED JSON SCHEMA:
{
  "checks": [
    {
      "risk_index": 0,
      "agrees": true or false,
      "note": "Concise justification for why you agree or disagree with this specific claimed risk"
    }
  ]
}
"""

@dataclass
class CrosscheckItem:
    risk_index: int
    agrees: bool
    note: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_index": self.risk_index,
            "agrees": self.agrees,
            "note": self.note
        }


def clean_json_response(raw_response: str) -> str:
    """Strips markdown block formatting if present."""
    text = raw_response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def run_crosscheck_model(
    formatted_context: str,
    risks: List[Dict[str, Any]],
    model_name: str = "claude-3-haiku-20240307",
    temperature: float = 0.0
) -> Dict[str, Any]:
    """
    Executes crosscheck evaluation on the list of risks.
    """
    if not risks:
        return {
            "checks": [],
            "raw_response": "{}",
            "model": model_name,
            "latency": 0.0,
            "prompt_tokens": 0,
            "completion_tokens": 0
        }

    user_prompt = (
        f"### CONTEXT BUNDLE ###\n{formatted_context}\n\n"
        f"### CLAIMED RISKS TO VERIFY ###\n{json.dumps(risks, indent=2)}\n\n"
        f"Evaluate each risk index (0 to {len(risks)-1}) and return JSON checks."
    )

    start_time = time.time()

    target_model = model_name
    if target_model.startswith("claude-") and not os.environ.get("ANTHROPIC_API_KEY"):
        if os.environ.get("GEMINI_API_KEY"):
            target_model = "gemini/gemini-1.5-flash-latest"
        elif os.environ.get("OPENAI_API_KEY"):
            target_model = "gpt-4o-mini"

    import litellm
    litellm.drop_params = True

    response = litellm.completion(
        model=target_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        temperature=temperature,
        response_format={"type": "json_object"} if "gpt-" in target_model or "gemini" in target_model else None
    )

    latency = time.time() - start_time
    content = response.choices[0].message.content
    cleaned = clean_json_response(content)

    parsed = json.loads(cleaned)

    checks = []
    if isinstance(parsed, dict) and "checks" in parsed and isinstance(parsed["checks"], list):
        for item in parsed["checks"]:
            if isinstance(item, dict):
                r_idx = int(item.get("risk_index", 0))
                agrees = bool(item.get("agrees", True))
                note = str(item.get("note", ""))
                checks.append(
                    CrosscheckItem(
                        risk_index=r_idx,
                        agrees=agrees,
                        note=note
                    )
                )

    usage = getattr(response, "usage", None)
    prompt_tokens = usage.prompt_tokens if usage else len(user_prompt) // 4
    completion_tokens = usage.completion_tokens if usage else len(content) // 4

    return {
        "checks": [c.to_dict() for c in checks],
        "raw_response": content,
        "model": target_model,
        "latency": latency,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens
    }


if __name__ == "__main__":
    print("[+] Testing core/crosscheck_model.py standalone...")
    test_context = "Context sample..."
    sample_risks = [
        {
            "description": "Timeout 0 causes immediate error in connect_client",
            "affected_function": "connect_client",
            "severity": "high",
            "reasoning": "connect_client expects positive timeout value."
        }
    ]

    api_available = any(k in os.environ for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"))
    if api_available:
        try:
            res = run_crosscheck_model(test_context, sample_risks)
            print(f"[+] Crosscheck Model output model={res['model']} latency={res['latency']:.2f}s:")
            print(json.dumps(res['checks'], indent=2))
        except Exception as e:
            print(f"[!] API Call Exception (Will be handled by core/degrade): {e}")
    else:
        print("[!] No LLM API key detected in env (ANTHROPIC_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY).")
        print("[+] core/crosscheck_model.py verified structurally.")
