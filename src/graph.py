"""
LangGraph StateGraph wiring for the Automaton Auditor.

Phase 1 topology (linear PoC — proves the pipeline):
  START → repo_investigator → evidence_aggregator → prosecutor → chief_justice → END

Phase 3 topology (full parallel — uncomment when Defense/TechLead are ready):
  START → [repo_investigator ‖ doc_analyst ‖ vision_inspector]
        → evidence_aggregator
        → [prosecutor ‖ defense ‖ techlead]
        → chief_justice
        → END
"""

import json
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from src.nodes.detectives import repo_investigator_node
from src.nodes.judges import defense_node, prosecutor_node, techlead_node
from src.nodes.justice import chief_justice_node, evidence_aggregator_node, render_markdown_report
from src.state import AgentState


def build_graph(parallel: bool = False):
    """
    Build and compile the auditor StateGraph.

    Args:
        parallel: If True, detectives and judges run in parallel fan-out.
                  If False (default), linear Phase 1 topology is used.
    """
    builder = StateGraph(AgentState)

    # --- Nodes ---
    builder.add_node("repo_investigator", repo_investigator_node)
    builder.add_node("evidence_aggregator", evidence_aggregator_node)
    builder.add_node("prosecutor", prosecutor_node)
    builder.add_node("chief_justice", chief_justice_node)

    if parallel:
        # Phase 3: parallel fan-out for judges
        builder.add_node("defense", defense_node)
        builder.add_node("techlead", techlead_node)

    # --- Edges ---
    builder.add_edge(START, "repo_investigator")
    builder.add_edge("repo_investigator", "evidence_aggregator")

    if parallel:
        # Fan-out: all three judges receive the same aggregated evidence
        builder.add_edge("evidence_aggregator", "prosecutor")
        builder.add_edge("evidence_aggregator", "defense")
        builder.add_edge("evidence_aggregator", "techlead")
        # Fan-in: chief_justice waits for all three
        builder.add_edge("prosecutor", "chief_justice")
        builder.add_edge("defense", "chief_justice")
        builder.add_edge("techlead", "chief_justice")
    else:
        # Phase 1: linear — single prosecutor
        builder.add_edge("evidence_aggregator", "prosecutor")
        builder.add_edge("prosecutor", "chief_justice")

    builder.add_edge("chief_justice", END)

    return builder.compile()


def run_audit(repo_url: str, pdf_path: str = "", output_path: str | None = None, parallel: bool = False) -> str:
    """
    Run the full audit pipeline against a repository.

    Args:
        repo_url:    GitHub repository URL to audit.
        pdf_path:    Path to PDF report (optional, used by DocAnalyst in Phase 4).
        output_path: If provided, write the Markdown report to this file.
        parallel:    Enable parallel judge fan-out (Phase 3+).

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
