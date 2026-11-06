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
from pydantic import BaseModel, Field, model_validator
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


def _as_text(value: Any) -> str:
    """Coerce model output (str, list of steps, dict, number) into plain text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(_as_text(item) for item in value)
    if isinstance(value, dict):
        return "; ".join(f"{key}: {_as_text(val)}" for key, val in value.items())
    return str(value)


def _as_text_list(value: Any) -> List[str]:
    """Coerce model output (single string or mixed list) into a list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [_as_text(item) for item in value]
    return [_as_text(value)]


def _norm_enum(data: dict, field: str, mapping: dict) -> None:
    """Normalize an enum field in-place: case/space/hyphen-insensitive, with synonyms."""
    value = data.get(field)
    if isinstance(value, str):
        key = value.strip().lower().replace("-", "_").replace(" ", "_")
        if key in mapping:
            data[field] = mapping[key]


_SEVERITY_MAP = {
    "fatal": "fatal", "major": "major", "minor": "minor",
    "unverified_warning": "unverified_warning", "warning": "unverified_warning",
    "critical": "fatal", "high": "major", "low": "minor",
}


class ASearcherAnalysis(BaseModel):
    """
    ASearcher (Structured Analysis Block):
    Mimics uncertainty-aware reasoning without End-to-End RL training.
    Spark Open models output this block before generating actions/proofs.
    """
    available_info: str = ""
    plan: str = ""
    uncertainties: List[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _coerce_text(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"plan": data}
        if isinstance(data, dict):
            data = dict(data)
            for field in ("available_info", "plan"):
                if field in data:
                    data[field] = _as_text(data[field])
            if "uncertainties" in data:
                data["uncertainties"] = _as_text_list(data["uncertainties"])
        return data


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

    @model_validator(mode="before")
    @classmethod
    def _coerce_severity(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"claim_attacked": data, "why": data, "severity": "major"}
        if isinstance(data, dict):
            data = dict(data)
            _norm_enum(data, "severity", _SEVERITY_MAP)
        return data


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

    @model_validator(mode="before")
    @classmethod
    def _coerce_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            for field in ("objections", "categorized_objections"):
                if isinstance(data.get(field), str):
                    data[field] = [{"claim": data[field]}]
                elif isinstance(data.get(field), dict):
                    data[field] = [data[field]]
                elif isinstance(data.get(field), (list, tuple)):
                    data[field] = [
                        item.model_dump() if isinstance(item, BaseModel) else (item if isinstance(item, dict) else {"claim": _as_text(item)})
                        for item in data[field]
                    ]
            _norm_enum(data, "verdict", {
                "survives": "survives", "survive": "survives", "pass": "survives", "passed": "survives", "accepted": "survives", "accept": "survives", "ready": "survives", "valid": "survives",
                "needs_repair": "needs_repair", "repair": "needs_repair",
                "reject": "reject", "rejected": "reject", "fail": "reject",
                "falsified": "falsified", "false": "falsified",
            })
            if "assessment" in data:
                data["assessment"] = _as_text(data["assessment"])
            for field in (
                "unresolved_to_preserve",
                "minimal_weakenings",
                "dropped_objections",
                "weakest_lemmas",
                "hidden_assumptions",
                "boundary_cases",
                "theorem_misuse",
                "decisive_tests",
                "unresolved_objections",
            ):
                if field in data:
                    data[field] = _as_text_list(data[field])
            if data.get("objections") and not data.get("categorized_objections"):
                data["categorized_objections"] = [
                    item if isinstance(item, dict) else (item.model_dump() if hasattr(item, "model_dump") else {"claim": _as_text(item)})
                    for item in data["objections"]
                ]
            elif data.get("categorized_objections") and not data.get("objections"):
                data["objections"] = list(data["categorized_objections"])
            if data.get("unresolved_to_preserve") and not data.get("unresolved_objections"):
                data["unresolved_objections"] = list(data["unresolved_to_preserve"])
            elif data.get("unresolved_objections") and not data.get("unresolved_to_preserve"):
                data["unresolved_to_preserve"] = list(data["unresolved_objections"])
        return data


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

    @model_validator(mode="before")
    @classmethod
    def _coerce_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            # Models often return routes/obligations as a list of steps or a single string.
            if isinstance(data.get("primary_route"), (list, tuple)):
                data["primary_route"] = _as_text(data["primary_route"])
            if isinstance(data.get("primary_route"), dict):
                route = data["primary_route"]
                if "raw" in route:
                    data["primary_route"] = _as_text(route.get("raw"))
                elif not any(route.get(k) for k in ("mechanism", "reduction", "evidence", "lemmas")):
                    data["primary_route"] = _as_text(route)
            if isinstance(data.get("analysis"), str):
                data["analysis"] = {"plan": data["analysis"]}
            elif isinstance(data.get("analysis"), (list, tuple)):
                data["analysis"] = {"available_info": _as_text(data["analysis"])}
            for field in ("normalized_problem", "first_hard_obstruction", "next_task", "concrete_next_task", "readiness_assessment"):
                if field in data:
                    data[field] = _as_text(data[field])
            for field in ("active_obligations", "risky_lemmas"):
                if field in data:
                    data[field] = _as_text_list(data[field])
            if isinstance(data.get("backup_routes"), (str, dict)):
                data["backup_routes"] = [data["backup_routes"]]
            if isinstance(data.get("preserved_critiques"), str):
                data["preserved_critiques"] = [{"claim": data["preserved_critiques"]}]
            elif "preserved_critiques" in data and isinstance(data["preserved_critiques"], (list, tuple)):
                data["preserved_critiques"] = [
                    item if isinstance(item, dict) else {"claim": _as_text(item)}
                    for item in data["preserved_critiques"]
                ]
        return data


class GateObligation(BaseModel):
    """Appendix A: Gate obligations[] {id, severity (minor, major), assigned_section}."""
    id: str
    severity: Literal["minor", "major"] = "minor"
    assigned_section: Optional[int] = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_severity(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"id": data, "severity": "minor"}
        if isinstance(data, dict):
            data = dict(data)
            if not data.get("id"):
                data["id"] = _as_text(
                    data.get("description") or data.get("obligation") or data.get("claim") or "obligation"
                )
            _norm_enum(data, "severity", {"fatal": "major", "major": "major", "minor": "minor", "high": "major", "low": "minor"})
        return data


class GateDecision(BaseModel):
    """Appendix A: Gate decision output schema."""
    decision: Literal["ready", "ready_with_obligations", "explore_more", "reject"] = "ready"
    blocking_issues: List[str] = Field(default_factory=list)
    obligations: List[GateObligation] = Field(default_factory=list)
    rationale: str = ""
    explanation: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            _norm_enum(data, "decision", {
                "ready": "ready", "accept": "ready", "accepted": "ready",
                "ready_with_obligations": "ready_with_obligations", "conditional": "ready_with_obligations",
                "explore_more": "explore_more", "explore": "explore_more", "needs_further_exploration": "explore_more",
                "reject": "reject", "rejected": "reject",
            })
            if "blocking_issues" in data:
                data["blocking_issues"] = _as_text_list(data["blocking_issues"])
            if "rationale" in data:
                data["rationale"] = _as_text(data["rationale"])
            if "explanation" in data:
                data["explanation"] = _as_text(data["explanation"])
            if data.get("rationale") and not data.get("explanation"):
                data["explanation"] = data["rationale"]
            elif data.get("explanation") and not data.get("rationale"):
                data["rationale"] = data["explanation"]
        return data


class SectionSolution(BaseModel):
    """Appendix A: Section solution output schema."""
    status: Literal["solved", "partial", "blocked"] = "solved"
    latex_body: str = ""
    solution_body: str = ""
    claimed_result: str = ""
    bridge_claims: List[str] = Field(default_factory=list)
    open_obligations: List[str] = Field(default_factory=list)
    analysis: Optional[ASearcherAnalysis] = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            _norm_enum(data, "status", {
                "solved": "solved", "complete": "solved", "completed": "solved", "done": "solved", "accepted": "solved",
                "partial": "partial", "partially_solved": "partial",
                "blocked": "blocked", "failed": "blocked", "reject": "blocked", "rejected": "blocked",
            })
            for field in ("latex_body", "solution_body", "claimed_result"):
                if field in data:
                    data[field] = _as_text(data[field])
            if data.get("solution_body") and not data.get("latex_body"):
                data["latex_body"] = data["solution_body"]
            elif data.get("latex_body") and not data.get("solution_body"):
                data["solution_body"] = data["latex_body"]
            for field in ("bridge_claims", "open_obligations"):
                if field in data:
                    data[field] = _as_text_list(data[field])
        return data


class SectionReview(BaseModel):
    """Appendix A: Section review output schema."""
    verdict: Literal["ready", "conditional", "rejected"] = "ready"
    fatal_objections: List[Union[str, Dict[str, Any]]] = Field(default_factory=list)
    claims_not_established: List[str] = Field(default_factory=list)
    minor_suggestions: List[str] = Field(default_factory=list)
    summary: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            _norm_enum(data, "verdict", {
                "ready": "ready", "accept": "ready", "accepted": "ready",
                "conditional": "conditional",
                "rejected": "rejected", "reject": "rejected",
            })
            if "claims_not_established" in data:
                data["claims_not_established"] = _as_text_list(data["claims_not_established"])
            if "minor_suggestions" in data:
                data["minor_suggestions"] = _as_text_list(data["minor_suggestions"])
            if "summary" in data:
                data["summary"] = _as_text(data["summary"])
            if isinstance(data.get("fatal_objections"), str):
                data["fatal_objections"] = [data["fatal_objections"]]
        return data


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

    @model_validator(mode="before")
    @classmethod
    def _coerce_enums(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            if isinstance(data.get("defects"), str):
                data["defects"] = [{"description": data["defects"]}]
            elif isinstance(data.get("defects"), dict):
                data["defects"] = [data["defects"]]
            _norm_enum(data, "verdict", {
                "accept": "accept", "accepted": "accept",
                "reject": "reject", "rejected": "reject",
            })
            _norm_enum(data, "next_action", {
                "revise": "revise", "revision": "revise",
                "re_explore": "re_explore", "reexplore": "re_explore", "explore": "re_explore",
                "accept": "accept", "accepted": "accept", "done": "accept",
            })
        return data


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

    @model_validator(mode="before")
    @classmethod
    def _coerce_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            for wrap_key in ("plan", "decomposition", "section_plan", "output", "result", "content"):
                inner = data.get(wrap_key)
                if isinstance(inner, dict) and ("subproblems" in inner or "sections" in inner):
                    merged = dict(inner)
                    merged.update({k: v for k, v in data.items() if k != wrap_key})
                    data = merged
                    break
            raw_items = None
            for key in ("subproblems", "sections", "sub_problems", "tasks", "steps"):
                if isinstance(data.get(key), (list, tuple)) and data[key]:
                    raw_items = list(data[key])
                    break
            if raw_items is None and isinstance(data.get("subproblems"), (list, tuple)):
                raw_items = list(data["subproblems"])
            if raw_items is not None:
                # First pass: normalize each item into a dict and inspect raw indices
                norm_items: List[Dict[str, Any]] = []
                raw_indices: List[Optional[int]] = []
                for item in raw_items:
                    if isinstance(item, BaseModel):
                        item = item.model_dump()
                    elif isinstance(item, str):
                        item = {"title": item, "target_claim": item}
                    elif isinstance(item, dict):
                        item = dict(item)
                    else:
                        item = {"title": _as_text(item), "target_claim": _as_text(item)}
                    raw_idx = item.get("index")
                    parsed_idx: Optional[int] = None
                    if raw_idx is not None and not isinstance(raw_idx, bool):
                        try:
                            parsed_idx = int(raw_idx)
                        except (TypeError, ValueError):
                            parsed_idx = None
                    raw_indices.append(parsed_idx)
                    norm_items.append(item)

                # Detect 0-based indexing or duplicate/missing indices and map cleanly to 1..N
                old_to_new: Dict[int, int] = {}
                for pos, r_idx in enumerate(raw_indices, start=1):
                    if r_idx is not None and r_idx not in old_to_new:
                        old_to_new[r_idx] = pos

                has_zero_index = any(r_idx == 0 for r_idx in raw_indices)
                has_invalid_or_dup = (
                    len(set(r for r in raw_indices if r is not None)) != len(norm_items)
                    or any(r is None or r <= 0 for r in raw_indices)
                )

                items = []
                for pos, item in enumerate(norm_items, start=1):
                    r_idx = raw_indices[pos - 1]
                    if has_zero_index or has_invalid_or_dup or r_idx is None:
                        index = pos
                    else:
                        index = r_idx
                    item["index"] = index
                    if not item.get("id"):
                        item["id"] = f"SEC_{index}"
                    if not item.get("title"):
                        item["title"] = item.get("name") or item.get("section") or f"Section {index}"
                    if not item.get("target_claim"):
                        item["target_claim"] = (
                            item.get("claim")
                            or item.get("target")
                            or item.get("goal")
                            or item.get("description")
                            or item.get("title")
                        )
                    deps = item.get("dependencies")
                    if isinstance(deps, (int, str)):
                        deps = [deps]
                    if isinstance(deps, (list, tuple)):
                        coerced = []
                        for d in deps:
                            try:
                                d_int = int(d)
                                if (has_zero_index or has_invalid_or_dup) and d_int in old_to_new:
                                    d_int = old_to_new[d_int]
                                if 1 <= d_int <= len(norm_items) and d_int != index and d_int not in coerced:
                                    coerced.append(d_int)
                            except (TypeError, ValueError):
                                pass
                        item["dependencies"] = coerced
                    items.append(item)
                data["subproblems"] = items
            if "latex_skeleton" in data:
                data["latex_skeleton"] = _as_text(data["latex_skeleton"])
        return data


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

    @model_validator(mode="before")
    @classmethod
    def _coerce_severity(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"description": data, "severity": "major"}
        if isinstance(data, dict):
            data = dict(data)
            _norm_enum(data, "severity", _SEVERITY_MAP)
            if data.get("section_index") is None and data.get("section") is not None:
                try:
                    data["section_index"] = int(data["section"])
                except (TypeError, ValueError):
                    pass
            if not data.get("exact_quote") and data.get("quote"):
                data["exact_quote"] = _as_text(data["quote"])
        return data


class VerificationReport(BaseModel):
    verdict: Literal["accepted", "conditional", "rejected"] = "accepted"
    defects: List[Defect] = Field(default_factory=list)
    downgraded_warnings: List[Defect] = Field(default_factory=list)
    summary: str = ""
    unresolved_objections_preserved: List[str] = Field(default_factory=list)
    exact_quotes_checked: int = 0
    exact_quotes_passed: int = 0

    @model_validator(mode="before")
    @classmethod
    def _coerce_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            for _f in ("defects", "downgraded_warnings"):
                if isinstance(data.get(_f), (list, tuple)):
                    data[_f] = [
                        item.model_dump() if isinstance(item, BaseModel) else (item if isinstance(item, dict) else {"description": _as_text(item)})
                        for item in data[_f]
                    ]
            for field in ("defects", "downgraded_warnings"):
                if isinstance(data.get(field), str):
                    data[field] = [{"description": data[field]}]
                elif isinstance(data.get(field), dict):
                    data[field] = [data[field]]
            _norm_enum(data, "verdict", {
                "accepted": "accepted", "accept": "accepted",
                "conditional": "conditional",
                "rejected": "rejected", "reject": "rejected",
            })
            if "summary" in data:
                data["summary"] = _as_text(data["summary"])
            if "unresolved_objections_preserved" in data:
                data["unresolved_objections_preserved"] = _as_text_list(data["unresolved_objections_preserved"])
        return data


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
    tree_widths: List[int] = Field(default_factory=lambda: [12, 8, 4, 1])
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
    budget_cap_usd: float = 50.0
    budget_cap_meta_usd: float = 150.0  # Meta Model API pool
    budget_cap_baseten_usd: float = 100.0  # Baseten partner pool
    max_rounds: int = 15
    max_sections: int = 15
    mock_mode: bool = False
    baseten_base_url: Optional[str] = None
    baseten_fallback_enabled: bool = False
    fireworks_base_url: Optional[str] = None
    fireworks_fallback_enabled: bool = False
    budget_cap_fireworks_usd: float = 100.0
