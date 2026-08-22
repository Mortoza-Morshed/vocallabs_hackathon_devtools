"""
core/risk_model.py

Primary semantic risk analyzer module. Calls a high-capability LLM (Sonnet-class / Gemini Pro / GPT-4o)
with the context bundle and system prompt focusing strictly on behavioral contract violations.
Returns STRICT JSON matching:
{
  "risks": [
    {
      "description": str,
      "affected_function": str,
      "severity": "low" | "medium" | "high",
      "reasoning": str
    }
  ]
}
"""

import os
import sys
import json
import time
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
load_dotenv()

SYSTEM_PROMPT = """You are a senior C++ static analysis & semantic risk analyzer tool called Blast Radius.
Your role is to analyze a C++ Pull Request diff along with its surrounding 2-hop call graph slice to identify POTENTIAL DOWNSTREAM BEHAVIORAL BREAKAGES before merge.

CRITICAL INSTRUCTIONS:
1. Focus EXCLUSIVELY on behavioral contracts and semantic risk. Look for:
   - Changed default argument values or function signatures.
   - Changed return value semantics (e.g. returning nullptr, different error codes, changed ranges).
   - Altered exception handling, error propagation, or unhandled failure states.
   - Violated preconditions, postconditions, or implicit invariant breaks.
   - Changed side effects (e.g. global state mutations, locking behavior, resource allocation/deallocation).
   - Downstream callers in the 2-hop callgraph slice that rely on the old behavior.
2. DO NOT flag code style, syntax issues, formatting, naming conventions, or missing comments.
3. You must respond with STRICT JSON ONLY. No preamble, no markdown wrappers, no postscript.

EXPECTED JSON SCHEMA:
{
  "risks": [
    {
      "description": "Short concise summary of what downstream behavior is likely to break",
      "affected_function": "Name of caller or downstream function affected",
      "severity": "low" | "medium" | "high",
      "reasoning": "Technical explanation of how the PR diff breaks the behavioral contract expected by affected_function"
    }
  ]
}

If no semantic risk or contract violation is found, return:
{
  "risks": []
}
"""

@dataclass
class RiskItem:
    description: str
    affected_function: str
    severity: str  # low, medium, high
    reasoning: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "description": self.description,
            "affected_function": self.affected_function,
            "severity": self.severity,
            "reasoning": self.reasoning,
        }


def clean_json_response(raw_response: str) -> str:
    """Strips markdown block formatting if present."""
    text = raw_response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return text.strip()


def run_risk_model(
    formatted_context: str,
    model_name: str = "claude-3-5-sonnet-20241022",
    temperature: float = 0.0
) -> Dict[str, Any]:
    """
    Executes the risk model prompt using litellm / direct API client.
    Returns dictionary with parsed JSON risks, latency, prompt_tokens, and completion_tokens.
    """
    user_prompt = f"Analyze the following C++ PR diff and call graph context for semantic risks:\n\n{formatted_context}"
    
    start_time = time.time()
    
    nv_key = os.environ.get("NVIDIA_NIM_API_KEY") or os.environ.get("NVIDIA_API_KEY") or os.environ.get("NEMOTRON_API_KEY")

    # Select default available provider model if generic name requested
    target_model = model_name
    kwargs = {}

    if target_model.startswith("claude-") and not os.environ.get("ANTHROPIC_API_KEY"):
        if os.environ.get("GEMINI_API_KEY"):
            target_model = "gemini/gemini-2.5-flash"
        elif nv_key:
            target_model = "openai/meta/llama-3.3-70b-instruct"
            kwargs["api_base"] = "https://integrate.api.nvidia.com/v1"
            kwargs["api_key"] = nv_key
        elif os.environ.get("OPENAI_API_KEY"):
            target_model = "gpt-4o"
    elif nv_key and not os.environ.get("ANTHROPIC_API_KEY") and not target_model.startswith("gemini"):
        kwargs["api_base"] = "https://integrate.api.nvidia.com/v1"
        kwargs["api_key"] = nv_key

    if target_model != model_name:
        print(f"[!] Requested model '{model_name}' unavailable (missing provider key); fell back to '{target_model}'", file=sys.stderr)

    if target_model.startswith("gemini") and os.environ.get("GEMINI_API_KEY"):
        import google.generativeai as genai
        genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
        clean_model = target_model.replace("gemini/", "")
        if not clean_model.startswith("models/"):
            clean_model = f"models/{clean_model}"
        g_model = genai.GenerativeModel(model_name=clean_model, system_instruction=SYSTEM_PROMPT)
        res = g_model.generate_content(user_prompt)
        content = res.text
        latency = time.time() - start_time
        meta = getattr(res, "usage_metadata", None)
        prompt_tokens = getattr(meta, "prompt_token_count", len(user_prompt) // 4) if meta else len(user_prompt) // 4
        completion_tokens = getattr(meta, "candidates_token_count", len(content) // 4) if meta else len(content) // 4
    else:
        import litellm
        litellm.drop_params = True
        litellm.telemetry = False
        litellm.suppress_debug_info = True
        os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
        kwargs["request_timeout"] = 60

        response = litellm.completion(
            model=target_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=temperature,
            **kwargs
        )
        latency = time.time() - start_time
        content = response.choices[0].message.content
        usage = getattr(response, "usage", None)
        prompt_tokens = usage.prompt_tokens if usage else len(formatted_context) // 4
        completion_tokens = usage.completion_tokens if usage else len(content) // 4

    cleaned = clean_json_response(content)
    parsed = json.loads(cleaned)

    # Validate schema
    risks = []
    if isinstance(parsed, dict) and "risks" in parsed and isinstance(parsed["risks"], list):
        for item in parsed["risks"]:
            if isinstance(item, dict):
                sev = str(item.get("severity", "medium")).lower()
                if sev not in ("low", "medium", "high"):
                    sev = "medium"
                risks.append(
                    RiskItem(
                        description=str(item.get("description", "Potential contract break")),
                        affected_function=str(item.get("affected_function", "unknown")),
                        severity=sev,
                        reasoning=str(item.get("reasoning", ""))
                    )
                )

    return {
        "risks": [r.to_dict() for r in risks],
        "raw_response": content,
        "model": target_model,
        "latency": latency,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens
    }


if __name__ == "__main__":
    print("[+] Testing core/risk_model.py standalone...")
    test_context = """### UNIFIED PR DIFF ###
```diff
diff --git a/src/server.cpp b/src/server.cpp
--- a/src/server.cpp
+++ b/src/server.cpp
@@ -10,3 +10,3 @@
-int get_timeout_ms() { return 5000; }
+int get_timeout_ms() { return 0; } // 0 now means non-blocking / immediate timeout!
```

### 1-HOP CALLGRAPH SLICE ###
#### Node: `connect_client` (src/network.cpp:45-50)
```cpp
void connect_client() {
    int timeout = get_timeout_ms();
    // expects positive timeout, 0 causes immediate WSAETIMEDOUT error
    socket_wait(timeout);
}
```
"""
    # Check if API key is present for live run test
    api_available = any(k in os.environ for k in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "NVIDIA_API_KEY", "NEMOTRON_API_KEY", "NVIDIA_NIM_API_KEY"))
    if api_available:
        try:
            res = run_risk_model(test_context)
            print(f"[+] Risk Model output model={res['model']} latency={res['latency']:.2f}s:")
            print(json.dumps(res['risks'], indent=2))
        except Exception as e:
            print(f"[!] API Call Exception (Will be handled by core/degrade): {e}")
    else:
        print("[!] No LLM API key detected in env (ANTHROPIC_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY / NVIDIA_API_KEY / NEMOTRON_API_KEY / NVIDIA_NIM_API_KEY).")
        print("[+] core/risk_model.py verified structurally.")
