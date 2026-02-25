# Automaton Auditor

A hierarchical multi-agent LangGraph swarm for autonomous forensic auditing and governance of AI-generated code repositories.

## Architecture

The system implements a "Digital Courtroom" pattern across three layers:

```
START
  │
  ▼
repo_investigator          ← Detective: clones repo, runs 5 AST forensic checks
  │
  ▼
evidence_aggregator        ← Validates all 5 evidence keys are present (hard-blocks on gaps)
  │
  ├──▶ prosecutor          ← Judge: adversarial, penalises every gap
  ├──▶ defense             ← Judge: forgiving, rewards intent (Phase 3)
  └──▶ techlead            ← Judge: pragmatic, evaluates artifact quality (Phase 3)
          │
          ▼
    chief_justice          ← Deterministic rules (security cap, fact supremacy,
          │                   functionality weight, dissent requirement) → AuditReport
          ▼
         END
```

**Five rubric criteria evaluated per audit:**

| Criterion | Forensic Tool | Detective Output |
|-----------|---------------|-----------------|
| Git Forensic Analysis | `extract_git_history` | commit count, bulk upload detection |
| State Management Rigor | `check_state_management_rigor` | Pydantic BaseModel, TypedDict, reducers |
| Graph Orchestration | `check_graph_orchestration` | StateGraph, fan-out, aggregator |
| Safe Tool Engineering | `check_safe_tool_engineering` | tempfile, subprocess, os.system AST |
| Structured Output Enforcement | `check_structured_output_enforcement` | with_structured_output binding |

## Project Structure

```
src/
  state.py              # Pydantic schemas: Evidence, JudicialOpinion, AuditReport, AgentState
  rules.py              # 4 deterministic ChiefJustice rules (pure Python, no LLM)
  graph.py              # LangGraph StateGraph wiring (linear + parallel topologies)
  tools/
    repo_tools.py       # Sandboxed git clone + 5 AST-based forensic checkers
  nodes/
    detectives.py       # RepoInvestigator node
    judges.py           # Prosecutor / Defense / TechLead judge nodes
    justice.py          # EvidenceAggregator + ChiefJustice + Markdown renderer
tests/
  test_state.py         # 13 tests — schema validation, immutability, reducer behavior
  test_rules.py         # 19 tests — all 4 deterministic rules
  test_detectives.py    # 16 tests — AST forensic tools
  test_judges.py        # 12 tests — sanitizer, rubric loading, mock LLM behavior
  test_graph.py         # 14 tests — topology, aggregator, end-to-end synthetic pipeline
rubric.json             # The Constitution — 10 audit dimensions loaded at runtime
audit/
  report_onself_generated/audit.md   # Self-audit report
```

## Setup

```bash
# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env and set OPENAI_API_KEY (or GOOGLE_API_KEY)
```

## Run an Audit

```bash
python -c "
from src.graph import run_audit
md = run_audit(
    repo_url='https://github.com/owner/repo',
    output_path='audit/report.md'
)
print(md[:500])
"
```

## Run Tests

```bash
uv run pytest tests/ -v
```

74 tests, all passing. Tests use mocked LLM and sandboxed fixtures — no API key required.

## Key Design Decisions

- **Evidence immutability** — `Evidence` is `frozen=True` (Pydantic). No node can mutate collected evidence.
- **Parallel-safe state** — `evidences` uses `operator.ior` reducer; `opinions` uses `operator.add`. Parallel fan-out is safe.
- **Deterministic scoring** — ChiefJustice applies 4 Python rules before any LLM call. Scores are never LLM-generated.
- **Prompt injection defence** — `_sanitize_for_judge()` strips `Evidence.content`. Judges only receive structured metadata.
- **Security rule ground truth** — Security cap is triggered only by forensic evidence rationale (AST tool output), never by LLM opinion text.
- **Persona divergence** — Prosecutor / Defense / TechLead system prompts share <40% vocabulary overlap (enforced by test).
