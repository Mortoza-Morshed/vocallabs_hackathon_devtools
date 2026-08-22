# Blast Radius: C++ PR Semantic Risk Analyzer

Blast Radius is a developer tool that analyzes C++ pull requests before merge to predict downstream behavioral regressions. Unlike traditional linters or style formatters that only verify syntax, Blast Radius performs semantic risk analysis: it extracts exact modified function definitions, constructs a static 2-hop call graph using Tree-sitter C++, bundles a token-bounded context slice, and executes a dual-LLM pipeline (Primary Risk Predictor + Independent Crosscheck Auditor) with confidence scoring, automatic degraded mode fallback, and detailed observability logging.

---

## What We Built and How It Works

### The Problem

In C++, code can compile cleanly without warnings while breaking downstream behavioral contracts. Common examples include:

- Modifying a default argument in a header, silently altering caller behavior.
- Returning a reference to a local variable (dangling reference / lifetime bug).
- Changing an integer return type from 64-bit to 32-bit (silent integer truncation).
- Removing an input pointer null-check that callers rely on.
- Changing an exception type from std::invalid_argument to std::runtime_error.
- In-place mutation of caller buffer arguments.
- Introducing unsynchronized static state into previously stateless, multi-threaded routines.
- Off-by-one boundary conditions in buffer loops.

Traditional static analysis tools and formatters cannot identify these contract violations because the modified code is syntactically valid.

### The Pipeline Architecture

Blast Radius processes pull requests through an 8-stage pipeline:

```
                  +------------------------+
                  |  C++ PR Unified Diff   |
                  +-----------+------------+
                              |
                              v
                  +------------------------+
                  |   core/diff_parser     |  (Tree-sitter C++ AST Line Mapper)
                  +-----------+------------+
                              |
                              v
                  +------------------------+
                  |    core/callgraph      |  (Pure static 2-hop call graph)
                  +-----------+------------+
                              |
                              v
                  +------------------------+
                  |  core/context_slicer   |  (Token budget aggregator, e.g. 8000 tokens)
                  +-----------+------------+
                              |
           +------------------+------------------+
           |                                     |
           v                                     v
 +-------------------+                 +-------------------+
 |  core/risk_model  |                 |   core/degrade    | (Fallback on API failure)
 | (Sonnet / Gemini) |                 +-------------------+
 +---------+---------+
           | (Strict JSON Risks)
           v
 +-----------------------+
 | core/crosscheck_model | (Independent Haiku / Flash audit)
 +---------+-------------+
           | (Strict JSON Checks)
           v
 +-----------------------+
 |    core/confidence    | (Scores 0-100 & Human Review Flags)
 +---------+-------------+
           |
           v
 +-----------------------+
 |  cli / web-ui / bot   | (Terminal report, Streamlit UI, GitHub PR comment)
 +-----------------------+
```

1. **Diff Parsing (`core/diff_parser.py`)**: Uses Tree-sitter C++ grammar to parse unified diff hunks and map modified line ranges to the smallest enclosing C++ function or method AST node.
2. **Static Call-Graph Generation (`core/callgraph.py`)**: Analyzes the repository C++ files to extract 1-hop and 2-hop callers and callees for each changed function (100% static, zero LLM overhead).
3. **Context Slicing & Budgeting (`core/context_slicer.py`)**: Aggregates the diff, modified function bodies, and 2-hop call-graph slices into a compact context bundle bounded by a strict token limit (default: 8000 tokens via tiktoken).
4. **Primary Risk Model (`core/risk_model.py`)**: Passes the context bundle to a high-capability LLM (Claude 3.5 Sonnet / Gemini 2.5 Flash / GPT-4o / Nemotron via LiteLLM) to identify downstream behavioral regressions and contract violations in strict JSON.
5. **Independent Crosscheck Model (`core/crosscheck_model.py`)**: A secondary auditor LLM (Claude 3 Haiku / Gemini 2.5 Flash / GPT-4o-mini) independently audits each proposed risk to check if it is a genuine regression or a false alarm.
6. **Confidence Scoring Engine (`core/confidence.py`)**: Combines risk predictions with crosscheck audit outcomes. If the models disagree or find ambiguities, the confidence score (0-100 scale) drops below the threshold (default: 50) and the risk is marked as "NEEDS HUMAN REVIEW".
7. **Degraded Mode Resilience (`core/degrade.py`)**: Wraps LLM execution. On API timeouts, HTTP 429 rate limits, or missing API keys, the system falls back to static call-graph analysis without crashing.
8. **Observability Logger (`observability/cost_latency_log.py`)**: Records input/output tokens, execution latency, and calculated USD costs per LLM invocation to `observability/logs.jsonl` and renders a formatted summary table.

---

## Team Members and Roles

The project was collaboratively developed across 3 team members with evenly distributed responsibilities:

### 1. [Saptaparno Chakraborty] - AST Parsing, Call Graph and Context Pipeline

- Built the Tree-sitter C++ AST integration to map unified diff lines to enclosing function and method definitions (`core/diff_parser.py`).
- Implemented the static 2-hop caller/callee call-graph extraction engine with zero external runtime dependencies (`core/callgraph.py`).
- Developed the token-bounded context slicer using tiktoken to prevent context window overflow (`core/context_slicer.py`).
- Authored unit test suites for diff parsing and call-graph traversal (`tests/test_diff_parser.py`, `tests/test_callgraph.py`).

### 2. [Saptarshi Banerjee] - Dual-LLM Architecture, Confidence and Degraded Mode

- Designed the dual-LLM prompt pipeline: Primary Risk Predictor and Independent Adversarial Auditor (`core/risk_model.py`, `core/crosscheck_model.py`).
- Implemented the calibrated confidence scoring algorithm with disagreement penalties and "NEEDS HUMAN REVIEW" flags (`core/confidence.py`).
- Built the zero-crash Degraded Mode fallback handler for missing API keys, HTTP 429 rate limits, and network timeouts (`core/degrade.py`).
- Implemented simulated failure test cases for timeout and rate-limit handling (`tests/test_degrade_simulated.py`, `tests/test_confidence.py`).

### 3. [Mortoza Mohammad Morshed] - Web UI, CLI, Observability and Evaluation Benchmark

- Developed the interactive Streamlit Web Dashboard with GitHub PR URL fetching, head-commit shallow cloning, and clone caching (`ui/app.py`).
- Built the CLI command-line interface with formatted terminal tables and raw JSON output modes (`cli/blast_radius.py`).
- Created the observability logger tracking input/output tokens, model latency, and USD costs (`observability/cost_latency_log.py`).
- Constructed the 10-scenario evaluation benchmark suite and offline test harness measuring Precision, Recall, and F1 score (`eval/eval_harness.py`).
- Configured GitHub Actions CI workflow for automated PR analysis and commenting (`.github/workflows/blast-radius.yml`).

---

## Key Features

- **Semantic Contract Violation Detection**: Identifies subtle C++ behavioral bugs (lifetime issues, integer truncation, exception mismatches, race conditions, buffer off-by-one errors) that pass compilation.
- **Tree-sitter Native AST Parsing**: Robust C++ function boundary detection from unified diff line numbers.
- **Pure Static 2-Hop Call Graph**: Fast in-memory extraction of caller and callee context slices with zero LLM API overhead.
- **Dual-LLM Cross-Auditing**: Primary risk model paired with an independent crosscheck model to minimize false positives.
- **Calibrated Confidence Scoring**: Generates a 0-100 score for each risk and flags low-confidence predictions as "NEEDS HUMAN REVIEW".
- **Zero-Crash Degraded Mode**: Gracefully falls back to static call-graph analysis when API keys are absent, rate-limited (HTTP 429), or timed out.
- **Full Observability Tracking**: Real-time logging of token counts, model latencies, and USD cost per run.
- **Multi-Interface Access**: Run via CLI (`cli/blast_radius.py`), interactive Web UI (`streamlit run ui/app.py`), or GitHub Actions PR workflow.
- **Benchmark Evaluation Suite**: Includes 10 real-world C++ scenario test cases with ground-truth labels and evaluation harness.

---

## Technical Decisions

1. **Tree-sitter over Clang LibTooling / Regex**:
   - _Decision_: Use Tree-sitter C++ grammar instead of Clang LibTooling or regular expressions.
   - _Rationale_: Clang LibTooling requires full compilation databases (`compile_commands.json`), matching header search paths, and compiler flags, which are often unavailable when analyzing raw PR diffs. Regular expressions are brittle on nested C++ templates and namespaces. Tree-sitter provides error-tolerant, fast, and syntax-accurate AST parsing on standalone files.

2. **Dual-LLM Pipeline vs Single-Prompt LLM**:
   - _Decision_: Separate risk prediction and risk verification into two distinct LLM calls (Primary Risk Model + Adversarial Crosscheck Model).
   - _Rationale_: Single-prompt LLMs exhibit confirmation bias and hallucinate downstream impacts. The secondary crosscheck model is specifically prompted to find reasons why a flagged risk might be a false alarm, establishing balanced confidence calibration.

3. **Static 2-Hop Call Graph Slicing**:
   - _Decision_: Limit static caller and callee extraction to 2 hops and enforce a token budget (default 8000 tokens).
   - _Rationale_: Real-world C++ codebases can have massive call trees. A 2-hop radius captures immediate callers (who rely on the modified function contract) and immediate callees (whose contracts the modified function relies on) while fitting within reasonable token and cost constraints.

4. **Guaranteed Degraded Mode for CI/CD**:
   - _Decision_: Wrap all LLM interactions in a resilient fallback layer that catches all API exceptions and returns static call-graph slices.
   - _Rationale_: In automated CI/CD pipelines, PR checks must never crash due to third-party API outages, rate limits (e.g. Gemini 429 free tier), or missing environment variables.

5. **Multi-Provider Fallback Hierarchy**:
   - _Decision_: Automatically resolve and switch model providers based on configured environment variables (Anthropic -> Gemini -> NVIDIA NIM -> OpenAI).
   - _Rationale_: Simplifies evaluation and local testing across developer machines with different available API provider subscriptions.

---

## Challenges and Solutions

1. **Challenge: Mapping Unified Diff Line Numbers to Nested C++ Scopes**:
   - _Problem_: Git diff hunks provide line intervals, but C++ functions contain nested namespaces, templates, classes, and lambdas.
   - _Solution_: Built a recursive AST traversal in `core/diff_parser.py` that queries Tree-sitter node bounds to identify the exact smallest enclosing `function_definition` node containing the modified lines.

2. **Challenge: Mitigating LLM Hallucinations and False Positives**:
   - _Problem_: LLMs tend to over-report benign refactors as high-risk bugs when reading isolated code snippets.
   - _Solution_: Introduced the independent crosscheck auditor (`core/crosscheck_model.py`) and a scoring formula (`core/confidence.py`) that applies severe penalties whenever the auditor disagrees, dropping the confidence score below 50 and requiring human review.

3. **Challenge: API Rate Limits and Quota Exhaustion in Free Tiers**:
   - _Problem_: Free tier API keys frequently trigger HTTP 429 quota exhaustion during multi-call workflows.
   - _Solution_: Developed `core/degrade.py` with automatic exception interception, verified via simulated unit tests (`tests/test_degrade_simulated.py`), ensuring static output is always returned.

4. **Challenge: Remote Cost Map Handshake Latencies in LiteLLM**:
   - _Problem_: LiteLLM attempted remote network calls to fetch model cost mappings during CLI runs, introducing intermittent network delays.
   - _Solution_: Set `LITELLM_LOCAL_MODEL_COST_MAP=True` and implemented direct Google Generative AI integration with fallback handling.

---

## Setup and Installation

### 1. Prerequisites

- Python 3.10+ (tested on Python 3.11, 3.12, 3.13)
- C/C++ compiler for Tree-sitter native grammar compilation:
  - Linux (Arch btw): `sudo pacman -S base-devel python`
  - Linux (Debian/Ubuntu): `sudo apt-get update && sudo apt-get install -y build-essential gcc g++ python3-dev`
  - macOS: `xcode-select --install`
  - Windows: Visual Studio Build Tools (with C++ Desktop development) or MinGW GCC.

### 2. Installation

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Verify Tree-sitter Grammar

Verify that Tree-sitter C++ loads successfully into memory:

```bash
python -c "import tree_sitter_cpp, tree_sitter; lang = tree_sitter.Language(tree_sitter_cpp.language()); parser = tree_sitter.Parser(lang); print('Tree-sitter C++ grammar loaded successfully!')"
```

### 4. API Configuration (Optional)

Blast Radius automatically selects available keys. If no key is set, it operates in Degraded Mode (static analysis only).

```bash
# Google Gemini
export GEMINI_API_KEY="..."

# Anthropic Claude
export ANTHROPIC_API_KEY="..."

# Nvidia NIM / Nemotron
export NVIDIA_API_KEY="..."

# OpenAI
export OPENAI_API_KEY="..."

# GitHub Token (optional, for higher rate limits in Web UI)
export GITHUB_TOKEN="..."
```

---

## Usage Guide

### 1. CLI Analysis

Analyze a repository against a unified PR diff file:

```bash
python cli/blast_radius.py analyze <repo-path> <pr-diff-file>
```

Optional CLI flags:

- `--token-budget <int>`: Maximum token budget for context bundle (default: 8000).
- `--confidence-threshold <int>`: Threshold for confirmed risk vs human review (default: 50).
- `--risk-model <str>`: Primary model identifier (default: claude-3-5-sonnet-20241022).
- `--crosscheck-model <str>`: Auditor model identifier (default: claude-3-haiku-20240307).
- `--json`: Output raw JSON instead of the formatted terminal report.
- `--log-file <path>`: Path for observability JSONL records (default: observability/logs.jsonl).

### 2. Streamlit Web UI

Launch the interactive browser dashboard:

```bash
streamlit run ui/app.py
```

Paste any public GitHub PR URL (e.g. `https://github.com/owner/repo/pull/123`). The Web UI fetches the PR diff, clones the head commit into `.blast_radius/ui_clones/` (cached per PR), and displays interactive risk cards, confidence meters, and call-graph slices.

### 3. Standalone Component Execution

Each component module can be run directly as a smoke test:

```bash
python -m core.diff_parser
python -m core.callgraph
python -m core.context_slicer
python -m core.risk_model
python -m core.crosscheck_model
python -m core.confidence
python -m core.degrade
python -m observability.cost_latency_log
```

---

## Verification and Evaluation

### 1. Built-in CLI Smoke Test Output

Tested on `smoke_test/repo` and `smoke_test/pr.diff` (which changes a velocity guard from `<= 0.0` to `< -10.0`):

```text
$ python cli/blast_radius.py analyze smoke_test/repo smoke_test/pr.diff

================================================================================
                  BLAST RADIUS: C++ PR SEMANTIC RISK ANALYZER
================================================================================
Target Repo : smoke_test/repo
PR Diff File: smoke_test/pr.diff

--------------------------------------------------------------------------------
1. CHANGED C++ FUNCTIONS DETECTED (1)
--------------------------------------------------------------------------------
  * compute_velocity                    | src/math_utils.cpp:3-8

--------------------------------------------------------------------------------
2. DOWNSTREAM SEMANTIC RISKS & CONTRACT VIOLATIONS (1)
--------------------------------------------------------------------------------

Risk #1: [HIGH SEVERITY] `compute_velocity` can now return negative values, violating `update_entity_speed`'s explicit contract for non-negative return.
  * Affected Component : `update_entity_speed`
  * Confidence Score   : 95/100 -> STATUS: CONFIRMED RISK
  * Crosscheck Audit   : AGREED
    Audit Note         : The PR changes the guard condition in `compute_velocity` from `multiplier <= 0.0` to `multiplier < -10.0`. This means for a `multiplier` in the range `[-10.0, 0.0]`, `compute_velocity` will now calculate `base * multiplier` instead of returning `0.0`.
  * Technical Reasoning:
    The PR changes the `compute_velocity` function's guard clause from `if (multiplier <= 0.0)` to `if (multiplier < -10.0)`. Previously, `compute_velocity` guaranteed a return of `0.0` for any non-positive `multiplier`. The caller `update_entity_speed` explicitly relies on `compute_velocity` returning non-negative values.
  ----------------------------------------------------------------------------

================================================================================
                        MODEL CALL OBSERVABILITY SUMMARY
================================================================================
Role               | Model                        | Tokens (In/Out) | Latency   | Cost ($)
-------------------------------------------------------------------------------------------
risk_model         | gemini/gemini-2.5-flash      | 722/303         |   15.98s | $ 0.00290
crosscheck_model   | gemini/gemini-2.5-flash      | 898/207         |    8.95s | $ 0.00259
-------------------------------------------------------------------------------------------
TOTAL              | 2 calls                      | 2130            |   24.93s | $ 0.00549
================================================================================
```

### 2. Evaluation Benchmark Suite (10 Cases)

Run the benchmark across 10 labeled C++ scenarios:

```bash
python eval/eval_harness.py
```

```text
[+] Running Evaluation Harness across 10 benchmark cases...

TEST CASE                        | GROUND TRUTH    | PREDICTED       | RESULT
--------------------------------------------------------------------------------
case1_default_param_change       | BREAKAGE        | RISKS (1)       | TP [PASS]
case2_return_by_ref_lifetime     | BREAKAGE        | RISKS (1)       | TP [PASS]
case3_removed_null_check         | BREAKAGE        | RISKS (1)       | TP [PASS]
case4_changed_exception_type     | BREAKAGE        | RISKS (1)       | TP [PASS]
case5_mutating_argument          | BREAKAGE        | RISKS (1)       | TP [PASS]
case6_safe_internal_refactor     | SAFE            | SAFE            | TN [PASS]
case7_thread_safety_static_state | BREAKAGE        | RISKS (1)       | TP [PASS]
case8_buffer_off_by_one          | BREAKAGE        | RISKS (1)       | TP [PASS]
case9_safe_doc_and_comment       | SAFE            | SAFE            | TN [PASS]
case10_integer_truncation        | BREAKAGE        | RISKS (1)       | TP [PASS]
--------------------------------------------------------------------------------
Summary: TP=8, TN=2, FP=0, FN=0
Precision: 1.0000 | Recall: 1.0000 | F1 Score: 1.0000
```

### 3. Unit Test Suite

Execute the deterministic test suite:

```bash
python -m unittest discover -s tests -v
```

```text
test_callgraph_1_hop_and_2_hop_traversal (test_callgraph.TestCallGraph.test_callgraph_1_hop_and_2_hop_traversal) ... ok
test_callgraph_callees_traversal (test_callgraph.TestCallGraph.test_callgraph_callees_traversal) ... ok
test_agreement_scores_high_confidence (test_confidence.TestConfidence.test_agreement_scores_high_confidence) ... ok
test_disagreement_penalizes_and_flags_human_review (test_confidence.TestConfidence.test_disagreement_penalizes_and_flags_human_review) ... ok
test_simulated_api_timeout_triggers_degraded_mode (test_degrade_simulated.TestDegradedMode.test_simulated_api_timeout_triggers_degraded_mode) ... ok
test_simulated_http_429_rate_limit_triggers_degraded_mode (test_degrade_simulated.TestDegradedMode.test_simulated_http_429_rate_limit_triggers_degraded_mode) ... ok
test_parse_diff_identifies_modified_function (test_diff_parser.TestDiffParser.test_parse_diff_identifies_modified_function) ... ok
test_parse_diff_with_no_cpp_changes (test_diff_parser.TestDiffParser.test_parse_diff_with_no_cpp_changes) ... ok

----------------------------------------------------------------------
Ran 8 tests in 12.688s

OK
```

### 4. Degraded Mode Verification

Simulated network timeouts and HTTP 429 rate limits:

```bash
python tests/test_degrade_simulated.py
```

```text
[!] Pipeline failure triggering DEGRADED MODE: litellm.Timeout: Simulated API timeout after 60s
.[!] Pipeline failure triggering DEGRADED MODE: litellm.RateLimitError: ResourceExhausted: 429 Quota exceeded for free tier requests
.
----------------------------------------------------------------------
Ran 2 tests in 8.671s

OK

[+] Verified Degraded Mode on Simulated Timeout:
    Reason: DEGRADED MODE: static analysis only, semantic risk not assessed (litellm.Timeout: Simulated API timeout after 60s)
    Fallback Slice Risk: Static analysis slice for `compute_velocity` (Callers: 1, Callees: 0)

[+] Verified Degraded Mode on Simulated HTTP 429 RateLimit:
    Reason: DEGRADED MODE: static analysis only, semantic risk not assessed (litellm.RateLimitError: ResourceExhausted: 429 Quota exceeded for free tier requests)
    Fallback Slice Risk: Static analysis slice for `compute_velocity` (Callers: 1, Callees: 0)
```

---

## Failure Log and Edge Cases

The following real edge cases and failure modes were observed and resolved during development:

| Timestamp        | Component         | Scenario / Diff                                       | Expected Outcome                    | Actual Outcome                                                                     | Root Cause & Resolution                                                                                                                            |
| :--------------- | :---------------- | :---------------------------------------------------- | :---------------------------------- | :--------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2026-08-21 16:41 | `core/risk_model` | Remote cost map lookup hang                           | Instant LLM API completion          | LiteLLM hung attempting remote SSL handshake to raw.githubusercontent.com          | Configured `LITELLM_LOCAL_MODEL_COST_MAP=True` and added direct Google Generative AI integration.                                                  |
| 2026-08-21 17:31 | `core/degrade`    | Gemini API free tier 429 quota exhaustion (5 req/min) | Rate limit handled without crashing | `execute_with_degrade_protection` caught 429 and produced static call-graph report | Expected behavior verified; added rate-limit backoff handling and documented degraded mode proof.                                                  |
| 2026-08-21 17:27 | `core/crosscheck` | Google GenAI SDK model prefix format                  | GenerativeModel initialization      | `400 * GenerateContentRequest.model: unexpected model name format`                 | Model strings in direct SDK require `models/gemini-2.5-flash` format; added auto-prefixing in `core/risk_model.py` and `core/crosscheck_model.py`. |
