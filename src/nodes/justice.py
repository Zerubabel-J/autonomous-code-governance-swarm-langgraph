"""
Chief Justice synthesis engine and EvidenceAggregator node.

RISK-1 MITIGATION: ChiefJustice applies deterministic Python rules FIRST.
No LLM call is made for scoring. LLM is used only for narrative remediation text.

RISK-5 MITIGATION: EvidenceAggregator hard-blocks if expected evidence keys
are missing. Judges never run on incomplete evidence silently.

Node responsibilities:
  evidence_aggregator_node — validate evidence completeness, block on gaps
  chief_justice_node       — apply rules, score criteria, generate Markdown report
"""

import json
from pathlib import Path

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from src.rules import (
    apply_evidence_rule,
    apply_security_rule,
    check_dissent,
    compute_final_score,
)
from src.state import AgentState, AuditReport, CriterionResult, JudicialOpinion

# ---------------------------------------------------------------------------
# Rubric — loaded once, used for dimension names
# ---------------------------------------------------------------------------

_RUBRIC_PATH = Path(__file__).parent.parent.parent / "rubric.json"
_RUBRIC: dict = json.loads(_RUBRIC_PATH.read_text(encoding="utf-8"))
_DIMENSION_NAMES: dict[str, str] = {
    d["id"]: d["name"] for d in _RUBRIC["dimensions"]
}

_MODEL = "deepseek-r1:8b"

# All known criteria from rubric.json
_ALL_CRITERIA = [d["id"] for d in _RUBRIC["dimensions"]]

# Repo-targeted criteria — RepoInvestigator must always produce these
_REPO_CRITERIA = [
    "git_forensic_analysis",
    "state_management_rigor",
    "graph_orchestration",
    "safe_tool_engineering",
    "structured_output_enforcement",
]

# PDF criteria — optional, only present when a PDF is provided
_PDF_CRITERIA = ["theoretical_depth", "report_accuracy"]
_IMAGE_CRITERIA = ["swarm_visual"]

# Minimum required evidence — repo detective must always produce these
_REQUIRED_EVIDENCE_KEYS = [
    f"repo_investigator_{cid}" for cid in _REPO_CRITERIA
]


# ---------------------------------------------------------------------------
# EvidenceAggregator Node
# ---------------------------------------------------------------------------


def evidence_aggregator_node(state: AgentState) -> dict:
    """
    RISK-5: Validate that every expected evidence key is present.
    Raises ValueError if any detective returned nothing — prevents silent
    partial-evidence audits reaching the judicial layer.
    """
    present = set(state.get("evidences", {}).keys())
    missing = [k for k in _REQUIRED_EVIDENCE_KEYS if k not in present]

    if missing:
        raise ValueError(
            f"EvidenceAggregator: missing evidence keys {missing}. "
            "A detective node returned no evidence. "
            "All detectives must return at least Evidence(found=False) per criterion."
        )

    return {}


# ---------------------------------------------------------------------------
# Chief Justice Node
# ---------------------------------------------------------------------------


def chief_justice_node(state: AgentState) -> dict:
    """
    RISK-1: Deterministic rules execute before any LLM call.
    Scoring is fully deterministic. LLM is used only to generate
    remediation text after scores are locked.
    """
    all_opinions = state.get("opinions", [])
    evidences = state.get("evidences", {})

    criterion_results = []

    # Discover all criteria that have both evidence and opinions
    evaluated_criteria = _discover_evaluated_criteria(all_opinions, evidences)

    for criterion_id in evaluated_criteria:
        opinions = [o for o in all_opinions if o.criterion_id == criterion_id]
        result = _adjudicate_criterion(criterion_id, opinions, evidences)
        criterion_results.append(result)

    overall = (
        sum(r.final_score for r in criterion_results) / len(criterion_results)
        if criterion_results else 1.0
    )

    report = AuditReport(
        repo_url=state["repo_url"],
        executive_summary=_build_executive_summary(criterion_results, overall),
        overall_score=round(overall, 2),
        criteria=criterion_results,
        remediation_plan=_build_remediation_plan(criterion_results),
    )

    return {"final_report": report}


def _discover_evaluated_criteria(
    opinions: list[JudicialOpinion],
    evidences: dict,
) -> list[str]:
    """Find all criteria that have at least one opinion."""
    criteria_with_opinions = {o.criterion_id for o in opinions}
    # Maintain rubric order for consistent reporting
    ordered = [cid for cid in _ALL_CRITERIA if cid in criteria_with_opinions]
    return ordered


def _adjudicate_criterion(
    criterion_id: str,
    opinions: list[JudicialOpinion],
    evidences: dict,
) -> CriterionResult:
    """Apply all four deterministic rules and produce a CriterionResult."""

    # Rule 1: Security Override
    score_cap = apply_security_rule(opinions, evidences)

    # Rule 2: Fact Supremacy
    opinions = apply_evidence_rule(opinions, evidences, criterion_id)

    # Rule 3: Functionality Weight (score computation)
    raw_score = compute_final_score(opinions, criterion_id)
    final_score = min(raw_score, score_cap) if score_cap is not None else raw_score
    final_score = max(1, min(5, final_score))

    # Rule 4: Dissent Requirement
    dissent = check_dissent(opinions)

    remediation = _generate_remediation(criterion_id, opinions, final_score, score_cap)

    return CriterionResult(
        dimension_id=criterion_id,
        dimension_name=_DIMENSION_NAMES.get(criterion_id, criterion_id),
        final_score=final_score,
        judge_opinions=opinions,
        dissent_summary=dissent,
        remediation=remediation,
    )


def _generate_remediation(
    criterion_id: str,
    opinions: list[JudicialOpinion],
    score: int,
    score_cap: int | None,
) -> str:
    """
    Generate remediation text from rules first.
    LLM narrative only if a non-trivial score explains a gap.
    """
    # Security override always gets a deterministic message
    if score_cap is not None:
        return (
            f"[Rule of Security] Score capped at {score}/5. "
            "Remove all os.system() calls from src/tools/. "
            "Replace with subprocess.run() inside tempfile.TemporaryDirectory()."
        )

    # Deterministic messages for common patterns
    if score <= 2:
        return _deterministic_remediation(criterion_id, score)

    if score >= 4:
        return f"Implementation meets rubric standards for {_DIMENSION_NAMES.get(criterion_id, criterion_id)}."

    # Score 2-3: use LLM to generate specific remediation from judge arguments
    return _llm_remediation(criterion_id, opinions, score)


def _deterministic_remediation(criterion_id: str, score: int) -> str:
    messages = {
        "git_forensic_analysis": (
            "Commit history shows bulk upload. "
            "Make atomic commits for each phase: environment setup, "
            "tool engineering, graph orchestration. Aim for >3 meaningful commits."
        ),
        "state_management_rigor": (
            "No Pydantic BaseModel or TypedDict found. "
            "Create src/state.py with Evidence(BaseModel), JudicialOpinion(BaseModel), "
            "and AgentState(TypedDict) using Annotated[..., operator.ior/add] reducers."
        ),
        "graph_orchestration": (
            "No StateGraph instantiation found. "
            "Implement src/graph.py with parallel fan-out for detectives, "
            "EvidenceAggregator fan-in, parallel fan-out for judges, "
            "and ChiefJustice synthesis. See rubric for required topology."
        ),
        "safe_tool_engineering": (
            "Tools implementation incomplete or missing. "
            "Implement clone_repo_sandboxed() using tempfile.TemporaryDirectory() "
            "and subprocess.run() with capture_output=True. Avoid os.system()."
        ),
        "structured_output_enforcement": (
            "Structured output binding incomplete. "
            "Ensure all judge nodes call llm.with_structured_output(JudicialOpinion) "
            "and that every LLM call is schema-constrained with no free-text fallback."
        ),
        "theoretical_depth": (
            "PDF report lacks theoretical depth. "
            "Include substantive explanations of Dialectical Synthesis, Fan-In/Fan-Out, "
            "and State Synchronization tied to actual implementation decisions."
        ),
        "report_accuracy": (
            "PDF report references file paths not found in the repository. "
            "Ensure all claimed file paths exist and feature claims match code evidence."
        ),
        "swarm_visual": (
            "No architecture diagram found in PDF report. "
            "Include a diagram showing parallel fan-out/fan-in for both detectives and judges."
        ),
        "judicial_nuance": (
            "Judge personas lack distinction. "
            "Ensure Prosecutor, Defense, and TechLead have conflicting system prompts "
            "with <50% shared text."
        ),
        "chief_justice_synthesis": (
            "ChiefJustice lacks deterministic rules. "
            "Implement security override, fact supremacy, functionality weight, "
            "and dissent requirement as Python if/else logic."
        ),
    }
    return messages.get(criterion_id, f"Score {score}/5: significant gaps detected. Review rubric for {criterion_id}.")


def _llm_remediation(
    criterion_id: str,
    opinions: list[JudicialOpinion],
    score: int,
) -> str:
    """Generate targeted remediation using judge arguments as context."""
    try:
        llm = ChatOpenAI(model=_MODEL, base_url="http://localhost:11434/v1", api_key="ollama", temperature=0.0)
        arguments = "\n".join(
            f"- {o.judge} (score {o.score}): {o.argument[:200]}"
            for o in opinions[:3]
        )
        prompt = ChatPromptTemplate.from_messages([
            ("system", (
                "You are a technical mentor generating a remediation plan. "
                "Be specific, file-level, and actionable. Maximum 3 sentences."
            )),
            ("human", (
                f"Criterion: {_DIMENSION_NAMES.get(criterion_id, criterion_id)}\n"
                f"Final score: {score}/5\n"
                f"Judge arguments:\n{arguments}\n\n"
                "Write a specific remediation instruction for the developer."
            )),
        ])
        chain = prompt | llm
        response = chain.invoke({})
        return response.content.strip()[:500]
    except Exception as exc:
        return f"Score {score}/5: {_deterministic_remediation(criterion_id, score)} [LLM remediation unavailable: {str(exc)[:100]}]"


def _build_executive_summary(results: list[CriterionResult], overall: float) -> str:
    score_label = (
        "Master Thinker" if overall >= 4.5 else
        "Competent Orchestrator" if overall >= 3.0 else
        "Vibe Coder"
    )
    critical = [r for r in results if r.final_score <= 2]
    strong = [r for r in results if r.final_score >= 4]

    summary = f"Overall score: {overall:.1f}/5 — {score_label}. "

    if critical:
        names = ", ".join(r.dimension_name for r in critical)
        summary += f"Critical gaps: {names}. "
    if strong:
        names = ", ".join(r.dimension_name for r in strong)
        summary += f"Strengths: {names}."

    return summary.strip()


def _build_remediation_plan(results: list[CriterionResult]) -> str:
    critical = [r for r in results if r.final_score <= 2]
    if not critical:
        return "No critical remediations required. Review individual criterion feedback for improvements."

    lines = ["Priority remediations (score ≤ 2):"]
    for r in critical:
        lines.append(f"\n**{r.dimension_name}** (score {r.final_score}/5)")
        lines.append(r.remediation)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Markdown report serializer
# ---------------------------------------------------------------------------


def render_markdown_report(report: AuditReport) -> str:
    """Serialize AuditReport to a Markdown string for file output."""
    lines = [
        f"# Audit Report: {report.repo_url}",
        "",
        "## Executive Summary",
        "",
        report.executive_summary,
        "",
        f"**Overall Score:** {report.overall_score:.1f} / 5.0",
        "",
        "---",
        "",
        "## Criterion Breakdown",
    ]

    for c in report.criteria:
        lines += [
            "",
            f"### {c.dimension_name}",
            "",
            f"**Final Score:** {c.final_score} / 5",
            "",
            "**Judge Opinions:**",
            "",
        ]
        for op in c.judge_opinions:
            lines.append(f"- **{op.judge}** (score {op.score}/5): {op.argument}")
            if op.cited_evidence:
                lines.append(f"  - *Cited evidence:* {', '.join(op.cited_evidence)}")

        if c.dissent_summary:
            lines += ["", f"> **Dissent:** {c.dissent_summary}"]

        lines += ["", f"**Remediation:** {c.remediation}", ""]

    lines += [
        "---",
        "",
        "## Remediation Plan",
        "",
        report.remediation_plan,
    ]

    return "\n".join(lines)
