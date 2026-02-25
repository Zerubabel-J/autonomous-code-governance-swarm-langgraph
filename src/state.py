import operator
from typing import Annotated, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# Detective Output
# ---------------------------------------------------------------------------


class Evidence(BaseModel):
    # RISK-2 MITIGATION: frozen=True makes Evidence immutable after collection.
    # No node may modify evidence once written to state.
    model_config = ConfigDict(frozen=True)

    goal: str = Field(description="The forensic goal this evidence addresses")
    found: bool = Field(description="Whether the artifact was located")
    # RISK-3 MITIGATION: content is excluded from judge prompts.
    # Populate only when a specific code snippet is needed for verification.
    content: Optional[str] = Field(
        default=None,
        description="Raw code snippet — never passed directly to judge prompts",
    )
    location: str = Field(
        description="File path, commit hash, or 'N/A' if not found"
    )
    rationale: str = Field(
        description="Explanation of what was found or why it was not found"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence level of this evidence (0.0 = uncertain, 1.0 = certain)",
    )


# ---------------------------------------------------------------------------
# Judge Output
# ---------------------------------------------------------------------------


class JudicialOpinion(BaseModel):
    judge: Literal["Prosecutor", "Defense", "TechLead"]
    criterion_id: str = Field(description="Rubric dimension ID this opinion addresses")
    score: int = Field(ge=1, le=5, description="Score from 1 (worst) to 5 (best)")
    argument: str = Field(description="Reasoning behind the score")
    # RISK-3 MITIGATION: cited_evidence holds Evidence.location strings only,
    # never raw content values.
    cited_evidence: List[str] = Field(
        description="List of Evidence.location values cited in the argument"
    )


# ---------------------------------------------------------------------------
# Chief Justice Output
# ---------------------------------------------------------------------------


class CriterionResult(BaseModel):
    dimension_id: str
    dimension_name: str
    final_score: int = Field(ge=1, le=5)
    judge_opinions: List[JudicialOpinion]
    # RISK-1 MITIGATION: dissent_summary is mandatory when score variance > 2.
    # ChiefJustice deterministic rules populate this before any LLM narrative.
    dissent_summary: Optional[str] = Field(
        default=None,
        description="Required when score variance across judges exceeds 2",
    )
    remediation: str = Field(
        description="Specific file-level instructions for improvement"
    )


class AuditReport(BaseModel):
    repo_url: str
    executive_summary: str
    overall_score: float = Field(ge=1.0, le=5.0)
    criteria: List[CriterionResult]
    remediation_plan: str


# ---------------------------------------------------------------------------
# Graph State
# ---------------------------------------------------------------------------


class AgentState(TypedDict):
    repo_url: str
    pdf_path: str
    rubric_dimensions: List[Dict]

    # RISK-2 MITIGATION: operator.ior merges dicts without overwriting keys.
    # All detective writes MUST use namespaced keys: "{detective}_{criterion_id}"
    # to prevent silent collision between parallel agents.
    evidences: Annotated[Dict[str, List[Evidence]], operator.ior]

    # operator.add appends lists — each judge appends its own JudicialOpinion.
    opinions: Annotated[List[JudicialOpinion], operator.add]

    # Written once by ChiefJustice only. No reducer — single writer.
    final_report: Optional[AuditReport]
