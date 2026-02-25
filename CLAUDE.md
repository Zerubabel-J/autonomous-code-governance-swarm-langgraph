# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A hierarchical multi-agent LangGraph swarm for autonomous forensic auditing and governance of AI-generated code repositories. It implements a "Digital Courtroom" pattern: Detective agents collect evidence, Judge agents deliberate with distinct personas (Prosecutor, Defense, Tech Lead), and a Chief Justice synthesizes a final audit verdict.

**Input:** GitHub repo URL + PDF report
**Output:** Structured Markdown Audit Report scored against a rubric

## Package Manager & Environment

This project uses **`uv`** exclusively. Do not use pip or poetry.

```bash
uv sync                    # Install dependencies
uv run python -m src.graph # Run the swarm
uv add <package>           # Add a dependency
```

API keys go in `.env` (never hardcoded). Required variables are listed in `.env.example`. LangSmith tracing must be enabled: `LANGCHAIN_TRACING_V2=true`.

## Planned Source Structure

```
src/
  state.py              # Pydantic/TypedDict state: Evidence, JudicialOpinion, AgentState
  graph.py              # LangGraph StateGraph wiring (fan-out detectives → fan-in → fan-out judges → Chief Justice)
  tools/
    repo_tools.py       # Sandboxed git clone (tempfile), git log, AST analysis
    doc_tools.py        # PDF ingestion (Docling), chunked RAG-lite querying
  nodes/
    detectives.py       # RepoInvestigator, DocAnalyst, VisionInspector
    judges.py           # Prosecutor, Defense, TechLead (parallel, .with_structured_output())
    justice.py          # ChiefJusticeNode with deterministic conflict resolution rules
rubric.json             # Machine-readable rubric loaded at runtime by agents
audit/
  report_onself_generated/
  report_onpeer_generated/
  report_bypeer_received/
reports/
  interim_report.pdf
  final_report.pdf
```

## Architecture: Three-Layer Swarm

**Layer 1 – Detective Layer (Evidence Collection, run in parallel):**
- `RepoInvestigator`: Clones repo into `tempfile.TemporaryDirectory()`, runs `git log`, parses AST (not regex) to verify StateGraph wiring, Pydantic models, reducers
- `DocAnalyst`: Ingests PDF via Docling, cross-references file paths from report against repo evidence
- `VisionInspector`: Extracts images from PDF, classifies diagrams with multimodal LLM

**Layer 2 – Judicial Layer (Dialectical Bench, run in parallel):**
- Three distinct judge personas analyze the same evidence independently per rubric criterion
- All return `JudicialOpinion` via `.with_structured_output()` bound to the Pydantic schema
- Persona philosophies: Prosecutor ("Trust No One"), Defense ("Reward Effort"), Tech Lead ("Does it actually work?")

**Layer 3 – Chief Justice (Synthesis):**
- Deterministic Python rules (not just an LLM prompt) resolve conflicts:
  - *Rule of Security*: confirmed security flaws cap score at 3
  - *Rule of Evidence*: Detective facts override Judge opinions
  - *Rule of Functionality*: Tech Lead's architectural verdict carries highest weight for architecture criterion
  - Score variance > 2 triggers mandatory dissent summary and re-evaluation

**Graph flow:**
`START → [RepoInvestigator ‖ DocAnalyst ‖ VisionInspector] → EvidenceAggregator → [Prosecutor ‖ Defense ‖ TechLead] → ChiefJustice → END`

## State Schema (Core Types)

State uses `TypedDict` with Annotated reducers to prevent parallel-write overwrites:
- `evidences: Annotated[Dict[str, List[Evidence]], operator.ior]`
- `opinions: Annotated[List[JudicialOpinion], operator.add]`

`Evidence` and `JudicialOpinion` are Pydantic `BaseModel` classes. Do not use plain dicts for nested state.

## Critical Constraints

- **No `os.system()`** for git operations — use `subprocess.run()` with error handling inside `tempfile.TemporaryDirectory()`
- **No regex for AST analysis** — use Python's `ast` module or tree-sitter
- **No freeform LLM output for judges** — always use `.with_structured_output(JudicialOpinion)`
- **`rubric.json` is the "Constitution"** — agents must load it at runtime; hardcoding rubric criteria in prompts is an anti-pattern
- Judge persona system prompts must be distinct (< 50% shared text) to avoid "Persona Collusion"

## Rubric Dimensions

The 10 rubric criteria the swarm evaluates (defined in `rubric.json`):
1. Git Forensic Analysis
2. State Management Rigor
3. Graph Orchestration Architecture
4. Safe Tool Engineering
5. Structured Output Enforcement
6. Judicial Nuance and Dialectics
7. Chief Justice Synthesis Engine
8. Theoretical Depth (PDF)
9. Report Accuracy / Cross-Reference (PDF)
10. Architectural Diagram Analysis (PDF images)
