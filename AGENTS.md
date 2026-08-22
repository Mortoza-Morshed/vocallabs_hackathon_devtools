# AGENTS.md

Blast Radius: C++ PR semantic risk analyzer (pure Python, hackathon project). Tree-sitter C++ parsing + dual-LLM pipeline.

## Setup

- Install deps: `pip install -r requirements.txt`
- Requires recent py-tree-sitter (>=0.22): code calls `Parser(Language(...))`.
- Python 3.11 (CI version).
- LLM keys via env or `.env`: `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, `NVIDIA_API_KEY` / `NEMOTRON_API_KEY` / `NVIDIA_NIM_API_KEY`. Missing keys are not an error — the pipeline returns callgraph-only output labeled **DEGRADED MODE**.

## Commands (run from repo root)

- Full pipeline: `python cli/blast_radius.py analyze <repo-path> <pr-diff-file> [--json] [--token-budget 8000] [--confidence-threshold 50]` (or `python blast-radius.py ...`). Must run from repo root — modules import as `core.*` / `observability.*`.
- Web UI: `streamlit run ui/app.py` (from repo root) — analyzes a GitHub PR URL end-to-end; clones PR head into `.blast_radius/ui_clones/<owner>-<repo>-<pr>/` (gitignored, cached across runs).
- Offline eval benchmark: `python -m eval.eval_harness` — mocks the LLM when no API keys are set, so it works offline; asserts F1 > 0.
- **De facto test suite:** every module has a `__main__` smoke-test block. Run the ones you touched: `python -m core.diff_parser`, `python -m core.callgraph`, `python -m core.context_slicer`, `python -m core.risk_model`, `python -m core.crosscheck_model`, `python -m core.confidence`, `python -m core.degrade`, `python -m observability.cost_latency_log`. There is no pytest/lint/typecheck config.
- Smoke tests write/delete `scratch_test/` (gitignored).

## Architecture

Pipeline order: `core/diff_parser.py` (maps diff lines → enclosing C++ functions via tree-sitter) → `core/callgraph.py` (static 2-hop callers/callees, zero LLM) → `core/context_slicer.py` (token-budgeted bundle) → `core/risk_model.py` (primary LLM, strict JSON) → `core/crosscheck_model.py` (independent audit LLM) → `core/confidence.py` (score 0–100; below threshold ⇒ "NEEDS HUMAN REVIEW"). `core/degrade.py` wraps all LLM execution and falls back to static-only analysis on any API failure. Every LLM call is logged to `observability/logs.jsonl` via `observability/cost_latency_log.py`.

## Gotchas

- **Model fallback** (`core/risk_model.py`, `core/crosscheck_model.py`): a `claude-*` request without `ANTHROPIC_API_KEY` switches provider automatically — NVIDIA NIM (`openai/meta/llama-3.3-70b-instruct`) → `gemini/gemini-2.5-flash` → `gpt-4o` (crosscheck: `gpt-4o-mini`). A warning is printed to stderr; check the `model` field in output to see what actually ran.
- LLM responses must be strict JSON; markdown fences are stripped by `clean_json_response`. Schema violations are coerced (bad severity → medium), not rejected.
- New eval cases go in `eval/test_cases/<case_name>/` with `pr.diff`, `repo/src/*.cpp`, and `ground_truth.json` (`has_regression`, `expected_risks`).
- CI (`.github/workflows/blast-radius.yml`) dogfoods this tool on every PR of this repo: generates `pr.diff` against the base branch, analyzes `./`, posts/updates a PR comment. Analyzer failure does not fail CI (`|| true`).
- `*.jsonl`, `.env`, and `scratch*/` are gitignored — never commit logs or keys.
