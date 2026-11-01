"""
Mini-Colosseum Data Models & Contract
Based on Section 10 of Mini-Colosseum Specification v1.0
"""

from typing import List, Dict, Any, Optional, Literal
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
]


class FalsifierReport(BaseModel):
    verdict: Literal["survives", "needs_repair", "reject", "falsified"] = "survives"
    assessment: str = ""
    weakest_lemmas: List[str] = Field(default_factory=list)
    hidden_assumptions: List[str] = Field(default_factory=list)
    boundary_cases: List[str] = Field(default_factory=list)
    theorem_misuse: List[str] = Field(default_factory=list)
    categorized_objections: List[Dict[str, Any]] = Field(default_factory=list)
    decisive_tests: List[str] = Field(default_factory=list)
    unresolved_objections: List[str] = Field(default_factory=list)


class StrategyCard(BaseModel):
    normalized_problem: str = ""
    primary_route: str = ""
    backup_routes: List[str] = Field(default_factory=list)
    risky_lemmas: List[str] = Field(default_factory=list)
    first_hard_obstruction: str = ""
    active_obligations: List[str] = Field(default_factory=list)
    concrete_next_task: str = ""
    readiness_assessment: str = ""


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


class SectionPlan(BaseModel):
    subproblems: List[SubproblemSpec] = Field(default_factory=list)
    latex_skeleton: str = ""


class Defect(BaseModel):
    section_index: Optional[int] = None
    supporting_section: Optional[int] = None
    using_section: Optional[int] = None
    claim: str = ""
    severity: Literal["fatal", "major", "minor"] = "major"
    description: str = ""
    suggested_action: str = ""


class VerificationReport(BaseModel):
    verdict: Literal["accepted", "conditional", "rejected"] = "accepted"
    defects: List[Defect] = Field(default_factory=list)
    summary: str = ""
    unresolved_objections_preserved: List[str] = Field(default_factory=list)


class Node(BaseModel):
    id: str
    type: NodeType
    stage: StageType
    round: int = 1
    status: StatusType = "pending"
    parents: List[str] = Field(default_factory=list)
    label: str
    model: str = "muse-spark-1.3"
    tokens_in: int = 0
    tokens_cached: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    input_summary: str = ""
    input_ref: str = ""
    output: Dict[str, Any] = Field(default_factory=dict)
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


class KnowledgeDirectory(BaseModel):
    entries: List[KnowledgeEntry] = Field(default_factory=list)


class RunConfig(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    problem_statement: str
    size_preset: Literal["Small", "Medium", "Custom"] = "Small"
    tree_widths: List[int] = Field(default_factory=lambda: [4, 2, 1])
    k_sample: int = 3
    models_per_role: Dict[str, str] = Field(
        default_factory=lambda: {
            "explorer": "muse-spark-1.3",
            "falsifier": "muse-spark-1.3",
            "aggregator": "muse-spark-1.3",
            "gate": "muse-wonder-1.0",
            "decomposer": "muse-wonder-1.0",
            "solver": "muse-spark-1.3",
            "section_falsifier": "muse-spark-1.3",
            "global_verifier": "muse-wonder-1.0",
            "curator": "muse-spark-1.3",
        }
    )
    budget_cap_usd: float = 20.0
    max_rounds: int = 2
    mock_mode: bool = True  # True enables rich deterministic/synthetic simulation when no API key
