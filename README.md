# 💥 Blast Radius: C++ PR Semantic Risk Analyzer

**Blast Radius** is a developer tool that analyzes C++ GitHub pull requests before merge to predict downstream behavioral breakages. Unlike linters or style bots, Blast Radius is a **semantic risk analyzer**: it extracts exact modified function definitions, constructs a static 2-hop call graph using Tree-Sitter C++, slices a token-bounded context bundle, and employs a dual-LLM architecture (Primary Risk Model + Independent Crosscheck Auditor) with confidence scoring, automatic degraded mode fallback, and full observability logging.

---

## 🏗️ Architecture & Modules

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
                    |    core/callgraph      |  (Pure static 2-hop callgraph slice)
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
   |  core/risk_model  |                 | core/degrade      | (Fallback on API failure)
   | (Sonnet / GPT-4o) |                 +-------------------+
   +---------+---------+
             | (Strict JSON Risks)
             v
   +-----------------------+
   |  core/crosscheck_model| (Independent Haiku / Flash / Ollama audit)
   +---------+-------------+
             | (Strict JSON Checks)
             v
   +-----------------------+
   |   core/confidence     | (Scores 0-100 & Human Review Flags)
   +---------+-------------+
             |
             v
   +-----------------------+
   |  cli / github-action  |  (Human-readable terminal report & PR comment)
   +-----------------------+
```

---

## 🚀 Running Each Component Standalone

Every module in Blast Radius is independently testable and runnable:

### 1. Diff Parser (`core/diff_parser.py`)
Parses C++ unified diffs and maps changed lines to enclosing C++ function/method definitions using tree-sitter.
```bash
python -m core.diff_parser
```

### 2. Static Call-Graph Generator (`core/callgraph.py`)
Scans the target C++ repository and returns up to 2-hop callers and callees with source code slices. Pure static analysis — zero LLM calls.
```bash
python -m core.callgraph
```

### 3. Context Slicer (`core/context_slicer.py`)
Packs PR diffs and 2-hop call graph slices into a token-bounded context bundle (configurable, default 8000 tokens).
```bash
python -m core.context_slicer
```

### 4. Risk Model (`core/risk_model.py`)
Invokes a high-capability LLM (Sonnet-class / Gemini Pro / GPT-4o) with strict JSON schema enforcing focus on behavioral contracts.
```bash
python -m core.risk_model
```

### 5. Crosscheck Model (`core/crosscheck_model.py`)
Invokes a secondary lightweight LLM (Haiku-class / Gemini Flash / Ollama) to independently audit claimed risks.
```bash
python -m core.crosscheck_model
```

### 6. Confidence Scoring (`core/confidence.py`)
Combines risk predictions with crosscheck agreement notes. Disagreements lower confidence score. Risks below threshold (default: 50) get flagged as "NEEDS HUMAN REVIEW".
```bash
python -m core.confidence
```

### 7. Degraded Mode (`core/degrade.py`)
Protects against LLM API rate limits, timeouts, network disconnects, or missing keys. Cleanly falls back to callgraph-only static analysis labeled `"DEGRADED MODE"`.
```bash
python -m core.degrade
```

### 8. Observability Logger (`observability/cost_latency_log.py`)
Tracks token usage, estimated USD costs, and latencies per model call into a local `.jsonl` log file and renders a terminal summary table.
```bash
python -m observability.cost_latency_log
```

### 9. Evaluation Harness (`eval/eval_harness.py`)
Benchmarking harness computing Precision, Recall, and F1 score across test case datasets.
```bash
python -m eval.eval_harness
```

### 10. Command Line Interface (`cli/blast_radius.py`)
Runs the full pipeline end-to-end and renders a formatted terminal report:
```bash
python cli/blast_radius.py analyze <repo-path> <pr-diff-file> --token-budget 8000 --confidence-threshold 50
```

---

## 🔑 Environment Setup & API Configuration

Configure API keys in your environment (Blast Radius automatically selects available keys):

```bash
# Nvidia / Nemotron 3.5
export NVIDIA_API_KEY="nvapi-..."
# or
export NEMOTRON_API_KEY="nvapi-..."

# Anthropic Claude
export ANTHROPIC_API_KEY="sk-ant-..."

# Google Gemini
export GEMINI_API_KEY="AIzaSy..."

# OpenAI
export OPENAI_API_KEY="sk-..."
```

---

## 🪵 Failure Log

*This section tracks real edge cases, model hallucinations, tree-sitter C++ parsing failures, and API degradation events observed during live runs.*

### Failure Log Entries

| Timestamp | Component | Scenario / Diff | Expected Outcome | Actual Outcome | Root Cause & Resolution |
|-----------|-----------|-----------------|------------------|----------------|--------------------------|
| *Placeholder* | *N/A* | *No failures logged yet* | *N/A* | *N/A* | *Template ready for hackathon live recording* |
