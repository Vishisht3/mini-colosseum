"""
Continuation seed extraction for saved runs.

A run that was stopped after decomposition does not need to start over:
its trace already holds the section plan and any section bodies that were
written and locally accepted. This module rebuilds that seed from a stored
trace (as produced by RunStore.export_trace_json) so the orchestrator can
skip exploration, gate, and decomposition and solve only the sections
whose bodies are still missing.
"""

from dataclasses import dataclass
from typing import Any, Dict, List

from ..models import SectionPlan
from .latex_utils import sanitize_latex_body, extract_fields_from_truncated_json

# Solver nodes have stored their body under different keys over time.
BODY_KEYS = ("solution_body", "latex_body", "proof_body", "proof", "body")

REUSABLE_STATUSES = {"accepted", "conditional"}


@dataclass
class ContinuationSeed:
    plan: SectionPlan
    existing_bodies: Dict[int, str]
    missing_indices: List[int]
    plan_round: int = 1


def extract_section_body(output: Any) -> str:
    """Return the first non-empty proof body stored in a solver output."""
    if not isinstance(output, dict):
        return ""
    for key in BODY_KEYS:
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            return sanitize_latex_body(value)
    raw = output.get("raw")
    if isinstance(raw, str) and raw.strip():
        recovered = extract_fields_from_truncated_json(raw)
        for key in BODY_KEYS:
            val = recovered.get(key)
            if isinstance(val, str) and val.strip():
                return sanitize_latex_body(val)
        return sanitize_latex_body(raw)
    return ""


def _node_id(node: Dict[str, Any]) -> str:
    return str(node.get("node_id") or node.get("id") or "")


def _section_index(node: Dict[str, Any]) -> int:
    node_id = _node_id(node)
    if node_id.startswith("SEC_"):
        try:
            return int(node_id[4:])
        except ValueError:
            return 0
    return 0


def build_continuation_seed(trace: Dict[str, Any]) -> ContinuationSeed:
    """
    Rebuild (plan, existing bodies, missing indices) from a saved trace.

    Raises ValueError when the trace cannot be continued: no saved
    decomposition, an empty plan, or every section already has a body.
    A body is reusable only when its solver node was accepted/conditional
    and the stored text is a real proof, not a skeleton placeholder.
    """
    nodes = trace.get("nodes") or []

    decomposers = [
        n for n in nodes
        if n.get("type") == "decomposer" and (n.get("output") or {}).get("subproblems")
    ]
    if not decomposers:
        raise ValueError("Saved run has no decomposition to continue from.")
    # Latest decomposition round wins if a run was decomposed more than once.
    decomposer = max(decomposers, key=lambda n: n.get("round") or 1)
    # Only solver nodes stored after this decomposer belong to its plan:
    # later rounds renumber sections, so an index solved under an earlier
    # plan can name a different claim.
    dec_pos = nodes.index(decomposer)
    plan_nodes = nodes[dec_pos + 1:]
    plan = SectionPlan.model_validate(decomposer.get("output") or {})
    if not plan.subproblems:
        raise ValueError("Saved run has no decomposition to continue from.")

    plan_round = int(decomposer.get("round") or 1)
    by_index = {sp.index: sp for sp in plan.subproblems}
    existing: Dict[int, str] = {}
    for node in plan_nodes:
        if node.get("type") == "decomposer":
            break
        if node.get("type") != "solver":
            continue
        if node.get("status") not in REUSABLE_STATUSES:
            continue
        idx = _section_index(node)
        if not idx:
            continue
        body = extract_section_body(node.get("output"))
        if not body or "%% SECTION_BODY" in body:
            continue
        node_claim = str((node.get("output") or {}).get("target_claim") or "").strip()
        plan_claim = str(by_index[idx].target_claim or "").strip() if idx in by_index else ""
        if node_claim and plan_claim and node_claim != plan_claim:
            continue
        # Keep the longest stored body if a section was solved twice.
        if idx not in existing or len(body) > len(existing[idx]):
            existing[idx] = body

    plan_indices = [sp.index for sp in plan.subproblems]
    existing = {idx: body for idx, body in existing.items() if idx in plan_indices}
    missing = [idx for idx in plan_indices if idx not in existing]
    if not missing:
        raise ValueError("Saved run already has every section written; nothing to continue.")

    return ContinuationSeed(
        plan=plan,
        existing_bodies=existing,
        missing_indices=missing,
        plan_round=int(decomposer.get("round") or 1),
    )
