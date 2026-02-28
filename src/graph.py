"""
LangGraph StateGraph wiring for the Automaton Auditor.

Full production topology:
  START → [repo_investigator ‖ vision_inspector]
        → doc_analyst          (needs repo evidence for cross-reference)
        → evidence_aggregator
        --conditional--> [prosecutor ‖ defense ‖ techlead]
        → chief_justice
        --conditional--> END
"""

import json
from pathlib import Path

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

load_dotenv()

from src.nodes.detectives import doc_analyst_node, repo_investigator_node, vision_inspector_node
from src.nodes.judges import defense_node, prosecutor_node, techlead_node
from src.nodes.justice import (
    _REQUIRED_EVIDENCE_KEYS,
    chief_justice_node,
    evidence_aggregator_node,
    render_markdown_report,
)
from src.state import AgentState

# ---------------------------------------------------------------------------
# Conditional routing functions
# ---------------------------------------------------------------------------

_JUDGE_NODES = ["prosecutor", "defense", "techlead"]


def _route_after_aggregator(state: AgentState) -> str:
    """
    Conditional routing after EvidenceAggregator.

    Rule: if required repo evidence is complete → dispatch to full judicial panel.
    Fallback: chief_justice renders a forensic-failure report without judge opinions.
    """
    evidences = state.get("evidences", {})
    missing = [k for k in _REQUIRED_EVIDENCE_KEYS if k not in evidences]
    if missing:
        return "forensic_failure"
    return "judicial_panel"


def _route_after_chief_justice(state: AgentState) -> str:
    """
    Conditional routing after ChiefJustice synthesis.

    Reserved for future re-evaluation passes (e.g., extreme variance triggers
    a second evidence-collection round). Currently always routes to END.
    """
    return "done"


def _forensic_failure_node(state: AgentState) -> dict:
    """
    Terminal node reached when required evidence is missing.
    Passes state unchanged — chief_justice will render a partial report.
    """
    return {}


def build_graph(parallel: bool = True):
    """
    Build and compile the auditor StateGraph.

    Args:
        parallel: If True (default), production topology with RI ‖ VI parallel
                  and DocAnalyst sequenced after RepoInvestigator (needs repo
                  evidence for cross-reference). If False, fully linear topology
                  for testing.
    """
    builder = StateGraph(AgentState)

    # --- Nodes ---
    builder.add_node("repo_investigator", repo_investigator_node)
    builder.add_node("doc_analyst", doc_analyst_node)
    builder.add_node("vision_inspector", vision_inspector_node)
    builder.add_node("evidence_aggregator", evidence_aggregator_node)
    builder.add_node("prosecutor", prosecutor_node)
    builder.add_node("defense", defense_node)
    builder.add_node("techlead", techlead_node)
    builder.add_node("chief_justice", chief_justice_node)
    builder.add_node("forensic_failure", _forensic_failure_node)

    if parallel:
        # --- RI and VI run in parallel from START ---
        # DocAnalyst (DA) runs AFTER RepoInvestigator so it can cross-reference
        # PDF-mentioned file paths against verified repo evidence.
        # All three detectives fan-in to EA via a list edge (LangGraph waits for all).
        builder.add_edge(START, "repo_investigator")
        builder.add_edge(START, "vision_inspector")

        # RI → DA (sequential, DA needs RI evidence for cross-reference)
        builder.add_edge("repo_investigator", "doc_analyst")

        # Fan-in: EA only fires once when BOTH DA and VI have completed
        builder.add_edge(["doc_analyst", "vision_inspector"], "evidence_aggregator")

        # --- Conditional routing: full panel OR forensic_failure ---
        # "judicial_panel" routes to all 3 judges in parallel (fan-out)
        builder.add_conditional_edges(
            "evidence_aggregator",
            _route_after_aggregator,
            {"judicial_panel": "prosecutor", "forensic_failure": "forensic_failure"},
        )
        builder.add_edge("evidence_aggregator", "defense")
        builder.add_edge("evidence_aggregator", "techlead")
        builder.add_edge("forensic_failure", "chief_justice")

        # --- Judge fan-in: chief_justice waits for all 3 ---
        builder.add_edge("prosecutor", "chief_justice")
        builder.add_edge("defense", "chief_justice")
        builder.add_edge("techlead", "chief_justice")
    else:
        # Linear topology — for testing without parallel overhead
        builder.add_edge(START, "repo_investigator")
        builder.add_edge("repo_investigator", "doc_analyst")
        builder.add_edge("doc_analyst", "vision_inspector")
        builder.add_edge("vision_inspector", "evidence_aggregator")
        builder.add_edge("evidence_aggregator", "prosecutor")
        builder.add_edge("prosecutor", "chief_justice")

    # --- Conditional exit: reserved for future re-evaluation pass ---
    builder.add_conditional_edges(
        "chief_justice",
        _route_after_chief_justice,
        {"done": END},
    )

    return builder.compile()


def run_audit(
    repo_url: str,
    pdf_path: str = "",
    output_path: str | None = None,
    parallel: bool = True,
) -> str:
    """
    Run the full audit pipeline against a repository.

    Args:
        repo_url:    GitHub repository URL to audit.
        pdf_path:    Path to PDF report (optional, used by DocAnalyst + VisionInspector).
        output_path: If provided, write the Markdown report to this file.
        parallel:    Enable parallel fan-out for detectives and judges (default True).

    Returns:
        Rendered Markdown audit report as a string.
    """
    rubric = json.loads((Path(__file__).parent.parent / "rubric.json").read_text())

    initial_state: AgentState = {
        "repo_url": repo_url,
        "pdf_path": pdf_path,
        "rubric_dimensions": rubric["dimensions"],
        "evidences": {},
        "opinions": [],
        "final_report": None,
    }

    graph = build_graph(parallel=parallel)
    final_state = graph.invoke(initial_state)

    report = final_state["final_report"]
    if report is None:
        return "# Audit Failed\n\nChiefJustice produced no report. Check LangSmith trace."

    markdown = render_markdown_report(report)

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(markdown, encoding="utf-8")
        print(f"Report written to: {output_path}")

    return markdown
