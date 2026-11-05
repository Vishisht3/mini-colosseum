"""
Mini-Colosseum v2.0 Data Models & Contract
Based on Section 10 of Mini-Colosseum Specification v2.0
Implements:
- ASearcher structured <analysis> fields
- Danus deterministic SHA-256 fingerprints
- DeepSeekMath-V2 exact-quote verifications
- Test-Time Scaling (K=4 rollouts)
- Dual-provider model routing & credit tracking
"""

from typing import List, Dict, Any, Optional, Literal, Union
from pydantic import BaseModel, Field
import time
import uuid

NodeType = Literal[
    "explorer",
    "falsifier",
    "aggregator",
    "gate",
    "decomposer",
    "solver",
    "section_falsifier",
    "section_aggregator",
    "global_verifier",
    "revision",
    "curator",
]

StageType = Literal[
    "exploration",
    "gate",
    "decomposition",
    "solving",
    "verification",
    "revision",
    "curator",
]

StatusType = Literal[
    "pending",
    "running",
    "accepted",
    "conditional",
    "rejected",
    "error",
]

EventType = Literal[
    "node_created",
    "node_updated",
    "edge_added",
    "stage_changed",
    "round_started",
    "log_line",
    "budget_warning",
    "error",
    "run_finished",
    "revision_applied",
    "reexplore_started",
    "provider_fallback",
]


class ASearcherAnalysis(BaseModel):
    """
    ASearcher (Structured Analysis Block):
    Mimics uncertainty-aware reasoning without End-to-End RL training.
    Spark Open models output this block before generating actions/proofs.
    """
    available_info: str = ""
    plan: str = ""
    uncertainties: List[str] = Field(default_factory=list)


class PrimaryRouteDetail(BaseModel):
    """Appendix A: primary_route structured breakdown."""
    mechanism: str = ""
    reduction: str = ""
    lemmas: List[str] = Field(default_factory=list)
    evidence: str = ""


class Objection(BaseModel):
    """Appendix A: objections[] {id, severity, claim_attacked, quote, why, cheap_test}."""
    id: str = Field(default_factory=lambda: f"obj_{uuid.uuid4().hex[:6]}")
    severity: Literal["fatal", "major", "minor", "unverified_warning"] = "major"
    claim_attacked: str = ""
    quote: str = ""
    why: str = ""
    cheap_test: str = ""
    quote_verified: bool = True


class FalsifierReport(BaseModel):
    """Appendix A: Falsifier report output schema."""
    verdict: Literal["survives", "needs_repair", "reject", "falsified"] = "survives"
    assessment: str = ""
    objections: List[Union[Objection, Dict[str, Any]]] = Field(default_factory=list)
    unresolved_to_preserve: List[str] = Field(default_factory=list)
    minimal_weakenings: List[str] = Field(default_factory=list)
    dropped_objections: List[str] = Field(default_factory=list)
    # Compatibility fields
    weakest_lemmas: List[str] = Field(default_factory=list)
    hidden_assumptions: List[str] = Field(default_factory=list)
    boundary_cases: List[str] = Field(default_factory=list)
    theorem_misuse: List[str] = Field(default_factory=list)
    categorized_objections: List[Dict[str, Any]] = Field(default_factory=list)
    decisive_tests: List[str] = Field(default_factory=list)
    unresolved_objections: List[str] = Field(default_factory=list)


class StrategyCard(BaseModel):
    """Appendix A: Strategy card output schema."""
    analysis: Optional[ASearcherAnalysis] = None
    normalized_problem: str = ""
    primary_route: Union[str, PrimaryRouteDetail, Dict[str, Any]] = ""
    backup_routes: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    first_hard_obstruction: str = ""
    active_obligations: List[str] = Field(default_factory=list)
    next_task: str = ""
    concrete_next_task: str = ""  # alias for backward compatibility
    readiness_assessment: str = ""
    risky_lemmas: List[str] = Field(default_factory=list)
    preserved_critiques: List[Dict[str, Any]] = Field(default_factory=list)


class GateObligation(BaseModel):
    """Appendix A: Gate obligations[] {id, severity (minor, major), assigned_section}."""
    id: str
    severity: Literal["minor", "major"] = "minor"
    assigned_section: Optional[int] = None


class GateDecision(BaseModel):
    """Appendix A: Gate decision output schema."""
    decision: Literal["ready", "ready_with_obligations", "explore_more", "reject"] = "ready"
    blocking_issues: List[str] = Field(default_factory=list)
    obligations: List[GateObligation] = Field(default_factory=list)
    rationale: str = ""


class SectionSolution(BaseModel):
    """Appendix A: Section solution output schema."""
    status: Literal["solved", "partial", "blocked"] = "solved"
    latex_body: str = ""
    claimed_result: str = ""
    bridge_claims: List[str] = Field(default_factory=list)
    open_obligations: List[str] = Field(default_factory=list)
    analysis: Optional[ASearcherAnalysis] = None


class SectionReview(BaseModel):
    """Appendix A: Section review output schema."""
    verdict: Literal["ready", "conditional", "rejected"] = "ready"
    fatal_objections: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    claims_not_established: List[str] = Field(default_factory=list)


class GlobalDefect(BaseModel):
    """Appendix A: Global verification defects[] {section, kind, description, quote, supporting_section}."""
    section: Optional[int] = None
    kind: str = ""
    description: str = ""
    quote: str = ""
    supporting_section: Optional[int] = None


class GlobalVerdict(BaseModel):
    """Appendix A: Global verdict output schema."""
    verdict: Literal["accept", "reject", "accepted", "rejected"] = "accept"
    defects: List[Union[GlobalDefect, Dict[str, Any]]] = Field(default_factory=list)
    next_action: Literal["revise", "re_explore", "accept"] = "accept"


class RevisionOutput(BaseModel):
    """Appendix A: Revision output schema."""
    revised_section_body: Optional[str] = None
    revised_outline: Optional[str] = None


class SubproblemSpec(BaseModel):
    id: str
    index: int
    title: str
    target_claim: str
    dependencies: List[int] = Field(default_factory=list)
    status: StatusType = "pending"
    retry_count: int = 0
    assigned_solver_model: str = "muse-spark-1.3"
    solution_body: Optional[str] = None
    bridge_claims: List[str] = Field(default_factory=list)
    obligations: List[str] = Field(default_factory=list)
    # Danus deterministic fingerprinting
    danus_fingerprint: str = ""
    dependency_fingerprints: Dict[str, str] = Field(default_factory=dict)
    is_stale: bool = False
    is_invalidated: bool = False
    # Test-time scaling K rollouts
    rollouts: List[Dict[str, Any]] = Field(default_factory=list)


class SectionPlan(BaseModel):
    subproblems: List[SubproblemSpec] = Field(default_factory=list)
    latex_skeleton: str = ""


class Defect(BaseModel):
    section_index: Optional[int] = None
    supporting_section: Optional[int] = None
    using_section: Optional[int] = None
    claim: str = ""
    severity: Literal["fatal", "major", "minor", "unverified_warning"] = "major"
    description: str = ""
    suggested_action: str = ""
    # DeepSeekMath-V2 exact-quote matching:
    exact_quote: str = ""
    quote_verified: bool = True
    downgraded_warning: bool = False


class VerificationReport(BaseModel):
    verdict: Literal["accepted", "conditional", "rejected"] = "accepted"
    defects: List[Defect] = Field(default_factory=list)
    downgraded_warnings: List[Defect] = Field(default_factory=list)
    summary: str = ""
    unresolved_objections_preserved: List[str] = Field(default_factory=list)
    exact_quotes_checked: int = 0
    exact_quotes_passed: int = 0


class Node(BaseModel):
    id: str
    type: NodeType
    stage: StageType
    round: int = 1
    status: StatusType = "pending"
    parents: List[str] = Field(default_factory=list)
    label: str
    model: str = "muse-spark-1.3"
    provider: str = "meta"  # 'meta' or 'baseten'
    primary_provider: Optional[str] = "meta"
    primary_model: Optional[str] = None
    fallback_used: bool = False
    fallback_reason: Optional[str] = None
    tokens_in: int = 0
    tokens_cached: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    input_summary: str = ""
    input_ref: str = ""
    output: Dict[str, Any] = Field(default_factory=dict)
    analysis: Optional[Dict[str, Any]] = None
    danus_fingerprint: Optional[str] = None
    is_stale: bool = False
    is_invalidated: bool = False
    rollouts: List[Dict[str, Any]] = Field(default_factory=list)
    falsifier_report: Optional[Dict[str, Any]] = None
    objections: List[Dict[str, Any]] = Field(default_factory=list)
    retry_count: int = 0
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class Edge(BaseModel):
    source: str
    target: str
    type: str = "aggregation"  # 'aggregation', 'dependency', 'revision'


class Event(BaseModel):
    run_id: str
    seq: int
    timestamp: str
    event_type: EventType
    payload: Dict[str, Any] = Field(default_factory=dict)


class KnowledgeEntry(BaseModel):
    entry_type: Literal["theorems_and_lemmas", "failed_approaches", "references", "observations"]
    title: str
    contents: str
    source: str
    caveats: str = ""


class RawProvenanceEntry(BaseModel):
    claim_id: str
    source_node: str
    target_statement: str
    falsifier_verdict: str = "survives"
    failure_point: Optional[str] = None
    tested_boundary_cases: List[str] = Field(default_factory=list)


class HMEDRecord(BaseModel):
    """
    Revision-Consequence Record for Hindsight Meta-Experience Distillation (HMED).
    Enables post-training / RL on failure-and-repair trajectories without runtime instability.
    """
    record_id: str
    run_id: str
    stage: str
    subproblem_index: Optional[int] = None
    failed_draft: str
    critique: str
    revised_draft: str
    downstream_verdict: str = "accepted"
    attribution_defect: Optional[str] = None
    cost_usd: float = 0.0
    model_solver: str = "muse-spark-1.3"
    model_falsifier: str = "muse-wonder-1.0"


class KnowledgeDirectory(BaseModel):
    entries: List[KnowledgeEntry] = Field(default_factory=list)
    raw_provenance: List[RawProvenanceEntry] = Field(default_factory=list)


class RunConfig(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    problem_statement: str
    tree_widths: List[int] = Field(default_factory=lambda: [9, 6, 3, 1])
    k_sample: int = 4
    k_rollouts: int = 4  # Test-time scaling K rollouts per section
    cross_model_review: bool = True  # Spark Open vs Wonder 1.0
    models_per_role: Dict[str, str] = Field(
        default_factory=lambda: {
            "explorer": "muse-spark-1.3",
            "falsifier": "muse-wonder-1.0",
            "aggregator": "muse-spark-1.3",
            "gate": "muse-wonder-1.0",
            "decomposer": "muse-wonder-1.0",
            "solver": "muse-spark-1.3",
            "section_falsifier": "muse-wonder-1.0",
            "global_verifier": "muse-wonder-1.0",
            "curator": "muse-spark-1.3",
        }
    )
    budget_cap_usd: float = 7.0
    budget_cap_meta_usd: float = 150.0  # Meta Model API pool
    budget_cap_baseten_usd: float = 100.0  # Baseten partner pool
    max_rounds: int = 2
    mock_mode: bool = False
    baseten_base_url: Optional[str] = None
    baseten_fallback_enabled: bool = False
