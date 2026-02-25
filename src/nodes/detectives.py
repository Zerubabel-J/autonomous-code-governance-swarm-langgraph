"""
Detective layer — forensic evidence collection nodes.

Each node returns a dict that LangGraph merges into AgentState via reducers.

RISK-2 MITIGATION: All evidence keys follow the pattern:
  "repo_investigator_{criterion_id}"
  "doc_analyst_{criterion_id}"

RISK-3 MITIGATION: Evidence.content is never populated with raw file content.
Only structured metadata (rationale, location, confidence) is captured.

RISK-5 MITIGATION: Every node always returns at least one Evidence object
per criterion it owns — even on total failure. Never returns empty dict.
"""

from pathlib import Path

from src.state import AgentState, Evidence
from src.tools.repo_tools import (
    check_graph_orchestration,
    check_safe_tool_engineering,
    check_state_management_rigor,
    check_structured_output_enforcement,
    clone_repo_sandboxed,
    extract_git_history,
)

_DETECTIVE = "repo_investigator"


# ---------------------------------------------------------------------------
# RepoInvestigator Node
# ---------------------------------------------------------------------------


def repo_investigator_node(state: AgentState) -> dict:
    """
    Clones the target repo and runs all 5 repo-targeted forensic protocols.
    Returns evidence for all 5 criteria in a single pass to avoid re-cloning.
    """
    repo_url = state["repo_url"]
    tmpdir = None

    try:
        tmpdir, repo_path = clone_repo_sandboxed(repo_url)
        evidences = _collect_all_evidence(repo_path, repo_url)
    except RuntimeError as exc:
        evidences = _all_failure_evidence(str(exc))
    finally:
        if tmpdir:
            tmpdir.cleanup()

    return {"evidences": evidences}


def _collect_all_evidence(repo_path: Path, repo_url: str) -> dict:
    return {
        f"{_DETECTIVE}_git_forensic_analysis": [
            _evidence_git_forensics(repo_path)
        ],
        f"{_DETECTIVE}_state_management_rigor": [
            _evidence_state_management(repo_path)
        ],
        f"{_DETECTIVE}_graph_orchestration": [
            _evidence_graph_orchestration(repo_path)
        ],
        f"{_DETECTIVE}_safe_tool_engineering": [
            _evidence_safe_tools(repo_path)
        ],
        f"{_DETECTIVE}_structured_output_enforcement": [
            _evidence_structured_output(repo_path)
        ],
    }


def _all_failure_evidence(error: str) -> dict:
    """RISK-5: Clone failed — return found=False for every owned criterion."""
    rationale = f"Repository clone failed: {error[:200]}"
    criteria = [
        "git_forensic_analysis",
        "state_management_rigor",
        "graph_orchestration",
        "safe_tool_engineering",
        "structured_output_enforcement",
    ]
    return {
        f"{_DETECTIVE}_{cid}": [
            Evidence(
                goal=f"Forensic check: {cid}",
                found=False,
                location="N/A",
                rationale=rationale,
                confidence=1.0,
            )
        ]
        for cid in criteria
    }


# ---------------------------------------------------------------------------
# Per-criterion evidence builders
# ---------------------------------------------------------------------------


def _evidence_git_forensics(repo_path: Path) -> Evidence:
    result = extract_git_history(repo_path)

    if result["error"]:
        return Evidence(
            goal="Verify iterative commit history showing progression",
            found=False,
            location="N/A",
            rationale=f"git log failed: {result['error']}",
            confidence=1.0,
        )

    total = result["total_count"]
    has_progression = result["has_progression"]
    is_bulk = result["is_bulk_upload"]
    commits_preview = "; ".join(result["commits"][:5])

    if is_bulk:
        rationale = f"Bulk upload detected: only {total} commit(s). Commits: [{commits_preview}]"
        confidence = 0.95
    elif not has_progression:
        rationale = f"{total} commits found but progression pattern unclear. Commits: [{commits_preview}]"
        confidence = 0.7
    else:
        rationale = f"{total} commits with clear progression. Sample: [{commits_preview}]"
        confidence = 1.0

    return Evidence(
        goal="Verify iterative commit history showing progression",
        found=total > 0,
        location=".git/log",
        rationale=rationale,
        confidence=confidence,
    )


def _evidence_state_management(repo_path: Path) -> Evidence:
    result = check_state_management_rigor(repo_path)

    if not result["found"]:
        return Evidence(
            goal="Verify Pydantic/TypedDict AgentState with operator.add/ior reducers",
            found=False,
            location="N/A",
            rationale="No src/state.py or src/graph.py found in repository",
            confidence=1.0,
        )

    if result["parse_error"]:
        return Evidence(
            goal="Verify Pydantic/TypedDict AgentState with operator.add/ior reducers",
            found=True,
            location=result["location"],
            rationale=f"File exists but failed AST parse: {result['parse_error']}",
            confidence=0.2,
        )

    has_typed = result["has_basemodel"] or result["has_typeddict"]
    has_reducers = result["has_reducers"]

    if has_typed and has_reducers:
        rationale = (
            f"BaseModel={result['has_basemodel']}, TypedDict={result['has_typeddict']}, "
            f"reducers(operator.add/ior)=True. Full compliance."
        )
        confidence = 1.0
    elif has_typed:
        rationale = (
            f"Typed state found (BaseModel={result['has_basemodel']}, "
            f"TypedDict={result['has_typeddict']}) but operator.add/ior reducers absent."
        )
        confidence = 0.7
    else:
        rationale = "No Pydantic BaseModel or TypedDict found. Plain dicts likely used."
        confidence = 0.9

    return Evidence(
        goal="Verify Pydantic/TypedDict AgentState with operator.add/ior reducers",
        found=True,
        location=result["location"],
        rationale=rationale,
        confidence=confidence,
    )


def _evidence_graph_orchestration(repo_path: Path) -> Evidence:
    result = check_graph_orchestration(repo_path)

    if not result["found"]:
        return Evidence(
            goal="Verify parallel fan-out/fan-in StateGraph architecture",
            found=False,
            location="N/A",
            rationale="src/graph.py not found",
            confidence=1.0,
        )

    if result["parse_error"]:
        return Evidence(
            goal="Verify parallel fan-out/fan-in StateGraph architecture",
            found=True,
            location=result["location"],
            rationale=f"src/graph.py exists but failed AST parse: {result['parse_error']}",
            confidence=0.2,
        )

    has_sg = result["has_stategraph"]
    has_fan_out = result["has_fan_out"]
    has_agg = result["has_aggregator"]
    edge_count = result["edge_count"]

    if has_sg and has_fan_out and has_agg:
        rationale = f"StateGraph with fan-out architecture detected. {edge_count} edge calls. EvidenceAggregator present."
        confidence = 1.0
    elif has_sg and not has_fan_out:
        rationale = f"StateGraph found but only {edge_count} edge calls — likely linear pipeline, not parallel fan-out."
        confidence = 0.9
    elif has_sg:
        rationale = f"StateGraph found with {edge_count} edges but no EvidenceAggregator node detected."
        confidence = 0.8
    else:
        rationale = "No StateGraph instantiation found in src/graph.py."
        confidence = 0.95

    return Evidence(
        goal="Verify parallel fan-out/fan-in StateGraph architecture",
        found=has_sg,
        location=result["location"],
        rationale=rationale,
        confidence=confidence,
    )


def _evidence_safe_tools(repo_path: Path) -> Evidence:
    result = check_safe_tool_engineering(repo_path)

    if not result["found"]:
        return Evidence(
            goal="Verify sandboxed git cloning with subprocess.run and tempfile",
            found=False,
            location="N/A",
            rationale="src/tools/ directory not found",
            confidence=1.0,
        )

    if result["has_os_system"]:
        rationale = (
            "SECURITY VIOLATION: os.system() call detected in src/tools/. "
            "This is a shell injection risk. subprocess.run() with sandboxed "
            "tempfile.TemporaryDirectory() is required."
        )
        confidence = 1.0
    elif result["uses_tempfile"] and result["uses_subprocess"]:
        rationale = "Sandboxed cloning confirmed: tempfile.TemporaryDirectory() and subprocess.run() present."
        confidence = 1.0
    elif result["uses_subprocess"]:
        rationale = "subprocess.run() found but tempfile sandboxing not detected."
        confidence = 0.8
    else:
        rationale = "Neither subprocess.run() nor tempfile detected in src/tools/."
        confidence = 0.9

    return Evidence(
        goal="Verify sandboxed git cloning with subprocess.run and tempfile",
        found=True,
        location=result["location"],
        rationale=rationale,
        confidence=confidence,
    )


def _evidence_structured_output(repo_path: Path) -> Evidence:
    result = check_structured_output_enforcement(repo_path)

    if not result["found"]:
        return Evidence(
            goal="Verify .with_structured_output(JudicialOpinion) in judge nodes",
            found=False,
            location="N/A",
            rationale="src/nodes/judges.py not found",
            confidence=1.0,
        )

    has_so = result["has_structured_output"]
    has_ji = result["has_judicial_opinion_binding"]

    if has_so and has_ji:
        rationale = "with_structured_output() bound to JudicialOpinion confirmed in judges.py."
        confidence = 1.0
    elif has_so:
        rationale = "with_structured_output() found but JudicialOpinion binding not confirmed."
        confidence = 0.7
    else:
        rationale = "No with_structured_output() or bind_tools() detected. Freeform LLM output risk."
        confidence = 0.9

    return Evidence(
        goal="Verify .with_structured_output(JudicialOpinion) in judge nodes",
        found=True,
        location=result["location"],
        rationale=rationale,
        confidence=confidence,
    )
