"""
LangGraph StateGraph wiring for the Automaton Auditor.

Full production topology:
  START → [repo_investigator ‖ doc_analyst ‖ vision_inspector]
        → evidence_aggregator
        → [prosecutor ‖ defense ‖ techlead]
        → chief_justice
        → END
"""

import json
from pathlib import Path

from dotenv import load_dotenv
from langgraph.graph import END, START, StateGraph

load_dotenv()

from src.nodes.detectives import doc_analyst_node, repo_investigator_node, vision_inspector_node
from src.nodes.judges import defense_node, prosecutor_node, techlead_node
from src.nodes.justice import chief_justice_node, evidence_aggregator_node, render_markdown_report
from src.state import AgentState


def build_graph(parallel: bool = True):
    """
    Build and compile the auditor StateGraph.

    Args:
        parallel: If True (default), full parallel fan-out for both
                  detectives and judges. If False, linear single-detective
                  single-judge topology for testing.
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

    if parallel:
        # --- Detective fan-out: all 3 run in parallel from START ---
        builder.add_edge(START, "repo_investigator")
        builder.add_edge(START, "doc_analyst")
        builder.add_edge(START, "vision_inspector")

        # --- Detective fan-in: all 3 must complete before aggregator ---
        builder.add_edge("repo_investigator", "evidence_aggregator")
        builder.add_edge("doc_analyst", "evidence_aggregator")
        builder.add_edge("vision_inspector", "evidence_aggregator")

        # --- Judge fan-out: all 3 run in parallel ---
        builder.add_edge("evidence_aggregator", "prosecutor")
        builder.add_edge("evidence_aggregator", "defense")
        builder.add_edge("evidence_aggregator", "techlead")

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

    builder.add_edge("chief_justice", END)

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
