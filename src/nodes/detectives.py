"""
Detective layer — forensic evidence collection nodes.

Each node returns a dict that LangGraph merges into AgentState via reducers.

RISK-2 MITIGATION: All evidence keys follow the pattern:
  "repo_investigator_{criterion_id}"
  "doc_analyst_{criterion_id}"
  "vision_inspector_{criterion_id}"

RISK-3 MITIGATION: Evidence.content is never populated with raw file content.
Only structured metadata (rationale, location, confidence) is captured.

RISK-5 MITIGATION: Every node always returns at least one Evidence object
per criterion it owns — even on total failure. Never returns empty dict.

Detectives:
  RepoInvestigator  — clones repo, runs AST-based forensic checks (5 criteria)
  DocAnalyst        — ingests PDF, checks theoretical depth + report accuracy (2 criteria)
  VisionInspector   — extracts PDF images, classifies diagrams (1 criterion)
"""

import base64
from pathlib import Path

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from src.state import AgentState, Evidence
from src.tools.doc_tools import (
    check_theoretical_depth,
    cross_reference_paths,
    extract_pdf_images,
    extract_pdf_text,
    find_mentioned_paths,
)
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
    has_cond = result.get("has_conditional_edges", False)
    edge_count = result["edge_count"]

    if has_sg and has_fan_out and has_agg and has_cond:
        rationale = (
            f"StateGraph with full parallel fan-out/fan-in. {edge_count} edge calls. "
            f"EvidenceAggregator present. Conditional edges (add_conditional_edges) confirmed — "
            f"error routing and re-evaluation logic implemented."
        )
        confidence = 1.0
    elif has_sg and has_fan_out and has_agg:
        rationale = (
            f"StateGraph with fan-out architecture detected. {edge_count} edge calls. "
            f"EvidenceAggregator present. No conditional edges detected."
        )
        confidence = 0.9
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
        goal="Verify parallel fan-out/fan-in StateGraph architecture with conditional error routing",
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

    has_err = result.get("has_error_handling", False)
    has_auth = result.get("has_auth_error_handling", False)

    if result["has_os_system"]:
        rationale = (
            "SECURITY VIOLATION: os.system() call detected in src/tools/. "
            "This is a shell injection risk. subprocess.run() with sandboxed "
            "tempfile.TemporaryDirectory() is required."
        )
        confidence = 1.0
    elif result["uses_tempfile"] and result["uses_subprocess"]:
        rationale = (
            "Sandboxed cloning confirmed: tempfile.TemporaryDirectory() and subprocess.run() present. "
            f"Return-code error handling: {has_err}. "
            f"Authentication error handling (stderr captured, RuntimeError raised): {has_auth}. "
            "No raw os.system() calls. Repo path is never the live working directory."
        )
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
    has_retry = result.get("has_retry_logic", False)

    if has_so and has_ji:
        rationale = (
            "with_structured_output() bound to JudicialOpinion confirmed in judges.py. "
            f"Retry logic (for attempt in range(2) pattern): {has_retry}. "
            "Fallback opinion returned on persistent failure — graph never crashes."
        )
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


# ===========================================================================
# DocAnalyst Node — PDF text forensic analysis
# ===========================================================================

_DOC_DETECTIVE = "doc_analyst"

# Criteria owned by DocAnalyst
_DOC_CRITERIA = ["theoretical_depth", "report_accuracy"]


def doc_analyst_node(state: AgentState) -> dict:
    """
    Extracts text from the PDF report and produces evidence for:
      - theoretical_depth: checks for key theoretical terms with substantive context
      - report_accuracy: extracts file paths from PDF and cross-references with repo evidence

    If no PDF is provided, returns found=False for both criteria.
    """
    pdf_path = state.get("pdf_path", "")
    repo_evidences = state.get("evidences", {})

    if not pdf_path or not Path(pdf_path).exists():
        return {"evidences": _doc_failure_evidence("No PDF provided or file not found")}

    # Extract text
    text_result = extract_pdf_text(pdf_path)
    if text_result["error"]:
        return {"evidences": _doc_failure_evidence(f"PDF extraction failed: {text_result['error']}")}

    text = text_result["text"]
    page_count = text_result["page_count"]

    evidences = {}

    # --- Theoretical Depth ---
    depth = check_theoretical_depth(text)
    found_terms = depth["terms_found"]
    missing_terms = depth["terms_missing"]
    substantive = depth["substantive_count"]

    if depth["has_depth"]:
        rationale = (
            f"{len(found_terms)} theoretical terms found with substantive explanation "
            f"({substantive} in context). Terms: {', '.join(found_terms)}. "
            f"PDF has {page_count} pages."
        )
        confidence = 1.0
    elif found_terms:
        rationale = (
            f"{len(found_terms)} terms found but only {substantive} with substantive context. "
            f"Found: {', '.join(found_terms)}. Missing: {', '.join(missing_terms)}. "
            f"May be keyword dropping without deep explanation."
        )
        confidence = 0.6
    else:
        rationale = f"No theoretical terms found in {page_count}-page PDF. Missing: {', '.join(missing_terms)}."
        confidence = 0.9

    evidences[f"{_DOC_DETECTIVE}_theoretical_depth"] = [
        Evidence(
            goal="Verify theoretical terms appear with substantive architectural explanation",
            found=bool(found_terms),
            location=f"PDF report ({page_count} pages)",
            rationale=rationale,
            confidence=confidence,
        )
    ]

    # --- Report Accuracy (Cross-Reference) ---
    mentioned = find_mentioned_paths(text)
    xref = cross_reference_paths(mentioned, repo_evidences)

    if not mentioned:
        rationale = "PDF report mentions no source file paths. Cannot cross-reference."
        confidence = 0.8
    elif xref["hallucinated"]:
        rationale = (
            f"{len(xref['verified'])}/{len(mentioned)} paths verified. "
            f"Hallucinated paths: {', '.join(xref['hallucinated'])}. "
            f"Accuracy ratio: {xref['accuracy_ratio']:.0%}."
        )
        confidence = 0.9
    else:
        rationale = (
            f"All {len(mentioned)} mentioned paths verified against repo evidence. "
            f"Paths: {', '.join(xref['verified'])}. Accuracy: 100%."
        )
        confidence = 1.0

    evidences[f"{_DOC_DETECTIVE}_report_accuracy"] = [
        Evidence(
            goal="Cross-reference file paths in PDF against repo evidence",
            found=bool(mentioned),
            location=f"PDF report ({len(mentioned)} paths extracted)",
            rationale=rationale,
            confidence=confidence,
        )
    ]

    return {"evidences": evidences}


def _doc_failure_evidence(error: str) -> dict:
    """RISK-5: PDF unavailable — return found=False for all doc criteria."""
    return {
        f"{_DOC_DETECTIVE}_{cid}": [
            Evidence(
                goal=f"PDF analysis: {cid}",
                found=False,
                location="N/A",
                rationale=error[:300],
                confidence=1.0,
            )
        ]
        for cid in _DOC_CRITERIA
    }


# ===========================================================================
# VisionInspector Node — PDF image forensic analysis
# ===========================================================================

_VISION_DETECTIVE = "vision_inspector"
_VISION_MODEL = "gpt-4o-mini"


def vision_inspector_node(state: AgentState) -> dict:
    """
    Extracts images from the PDF report and classifies them using a
    multimodal LLM. Produces evidence for:
      - swarm_visual: whether diagrams accurately show parallel fan-out/fan-in

    If no PDF or no images, returns found=False.
    """
    pdf_path = state.get("pdf_path", "")

    if not pdf_path or not Path(pdf_path).exists():
        return {"evidences": _vision_failure_evidence("No PDF provided or file not found")}

    img_result = extract_pdf_images(pdf_path)

    if img_result["error"]:
        return {"evidences": _vision_failure_evidence(f"Image extraction failed: {img_result['error']}")}

    if img_result["count"] == 0:
        return {"evidences": _vision_failure_evidence("No diagrams found in PDF (0 images > 5KB)")}

    # Classify the first image using multimodal LLM
    classification = _classify_diagram(img_result["images"][0])

    rationale = (
        f"{img_result['count']} diagram(s) found in PDF. "
        f"Classification of primary diagram: {classification}"
    )

    evidences = {
        f"{_VISION_DETECTIVE}_swarm_visual": [
            Evidence(
                goal="Verify architecture diagram shows parallel fan-out/fan-in topology",
                found=True,
                location=f"PDF report ({img_result['count']} images)",
                rationale=rationale,
                confidence=0.8,
            )
        ]
    }

    return {"evidences": evidences}


def _classify_diagram(image_b64: str) -> str:
    """Use multimodal LLM to classify an architecture diagram."""
    try:
        llm = ChatOpenAI(model=_VISION_MODEL, temperature=0.0, max_tokens=200)
        message = HumanMessage(
            content=[
                {"type": "text", "text": (
                    "Classify this diagram in exactly one sentence. "
                    "Is it: (a) a LangGraph StateGraph showing parallel fan-out/fan-in, "
                    "(b) a sequence diagram, (c) a generic flowchart, or (d) not an architecture diagram? "
                    "Does it show parallel branches for detectives and judges?"
                )},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            ]
        )
        response = llm.invoke([message])
        return response.content.strip()[:300]
    except Exception as exc:
        return f"[Classification unavailable: {str(exc)[:150]}]"


def _vision_failure_evidence(error: str) -> dict:
    """RISK-5: Image extraction failed — return found=False."""
    return {
        f"{_VISION_DETECTIVE}_swarm_visual": [
            Evidence(
                goal="Verify architecture diagram in PDF",
                found=False,
                location="N/A",
                rationale=error[:300],
                confidence=1.0,
            )
        ]
    }
