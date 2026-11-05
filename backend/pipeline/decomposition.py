"""
Stage 3: Proof Decomposition Engine, Cycle Detection & Danus Fingerprinting.
Based on Section 5.3 of Mini-Colosseum Specification v2.0.
- Converts approved strategy into numbered subproblems in topological order
- Each subproblem lists dependencies forming a DAG
- Validates that graph is strictly acyclic (rejects cycles)
- Danus Deterministic Fingerprints: computes SHA-256 fingerprints based on upstream dependencies
- Generates LaTeX master-document skeleton with reserved placeholders
"""

import time
import hashlib
import unicodedata
from typing import Dict, Any, List, Callable, Awaitable, Tuple
from ..models import Node, Edge, Event, SectionPlan, SubproblemSpec
from ..client import ModelClient


class CycleDetectedError(Exception):
    """Raised when decomposition contains a dependency cycle."""
    pass


def normalize_section_body(body: str) -> str:
    """Normalize whitespace and Unicode (NFKC) for deterministic hashing (Section 6.6)."""
    if not body:
        return ""
    normalized = unicodedata.normalize("NFKC", body)
    return " ".join(normalized.split())


def compute_body_hash(body: str) -> str:
    """Compute SHA-256 hash of normalized section body (Section 6.6)."""
    norm = normalize_section_body(body)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


def compute_dependency_fingerprint(dep_hashes: Dict[str, str]) -> str:
    """Compute fingerprint based on dependency IDs and their body hashes (Section 6.6)."""
    sorted_deps = sorted(dep_hashes.items())
    return hashlib.sha256(str(sorted_deps).encode("utf-8")).hexdigest()[:16]


def compute_danus_fingerprint(target_claim: str, title: str, dep_fingerprints: Dict[str, str]) -> str:
    """
    Danus (Deterministic Fingerprints, 2026):
    Every proof section in the DAG generates a SHA-256 fingerprint based on its target
    claim and its upstream dependency fingerprints.
    """
    sorted_deps = sorted(dep_fingerprints.items())
    raw = f"CLAIM:{target_claim}|TITLE:{title}|DEPS:{sorted_deps}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class DecompositionEngine:
    def __init__(
        self,
        client: ModelClient,
        emit_event: Callable[[Event], Awaitable[None]],
        save_node: Callable[[Node], None],
        save_edge: Callable[[Edge], None],
    ):
        self.client = client
        self.emit_event = emit_event
        self.save_node = save_node
        self.save_edge = save_edge

    def validate_acyclic(self, subproblems: List[Dict[str, Any]]) -> List[int]:
        """
        Verify graph is a Directed Acyclic Graph (DAG) and return topological ordering.
        Raises CycleDetectedError if a cycle is present.
        """
        indices = [sp["index"] for sp in subproblems]
        index_set = set(indices)
        adj: Dict[int, List[int]] = {i: [] for i in indices}
        in_degree: Dict[int, int] = {i: 0 for i in indices}

        for sp in subproblems:
            u = sp["index"]
            for dep in sp.get("dependencies", []):
                if dep in index_set:
                    adj[dep].append(u)
                    in_degree[u] += 1

        queue = [i for i in indices if in_degree[i] == 0]
        topo_order = []

        while queue:
            curr = queue.pop(0)
            topo_order.append(curr)
            for neighbor in adj[curr]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(topo_order) != len(indices):
            raise CycleDetectedError(f"Decomposition contains dependency cycle! Processed: {topo_order}, Total: {indices}")

        return topo_order

    async def decompose(
        self,
        run_id: str,
        problem: str,
        strategy_root: Node,
        round_num: int = 1,
        knowledge_prefix: str = "",
        model_decomposer: str = "muse-wonder-1.0",
    ) -> Tuple[Node, SectionPlan]:
        """
        Decomposes approved strategy into topological subproblems, computes Danus fingerprints,
        and creates LaTeX skeleton.
        """
        dec_node_id = f"R{round_num}_DEC"
        dec_route = self.client.get_route("decomposer", model_override=model_decomposer)
        dec_node = Node(
            id=dec_node_id,
            type="decomposer",
            stage="decomposition",
            round=round_num,
            status="running",
            parents=[strategy_root.id],
            label=f"DEC_{round_num}",
            model=dec_route.primary.model,
            provider=dec_route.primary.provider,
            primary_provider=dec_route.primary.provider,
            primary_model=dec_route.primary.model,
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            input_summary="Decompose approved strategy into topological subproblem DAG with Danus fingerprints",
        )
        self.save_node(run_id, dec_node)

        await self.emit_event(
            Event(
                run_id=run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="stage_changed",
                payload={"stage": "decomposition", "round": round_num},
            )
        )
        await self.emit_event(
            Event(
                run_id=run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="node_created",
                payload={"node": dec_node.model_dump()},
            )
        )

        prompt = (
            f"Problem statement: {problem}\n\n"
            f"Approved Strategy:\n{strategy_root.output}\n\n"
            "Decompose this strategy into an ordered list of concrete, non-trivial subproblems in topological order.\n"
            "Each subproblem must specify: index (1, 2, ...), title, target_claim, and dependencies (list of earlier subproblem indices).\n"
            "Also produce a clean LaTeX master-document skeleton with placeholder tags (e.g. %% SECTION_BODY_1 %%).\n"
            "Ensure the dependencies form a strict Directed Acyclic Graph without cycles."
        )

        call_res = await self.client.call(
            role="decomposer",
            prompt=prompt,
            model=model_decomposer,
            schema=SectionPlan,
            stable_prefix=knowledge_prefix,
            reasoning_effort="high",
            context_hints={"problem": problem, "node_id": dec_node_id, "round": round_num},
        )
        out, t_in, t_cached, t_out, cost = call_res
        dec_node.provider = getattr(call_res, "provider", "meta")
        dec_node.model = getattr(call_res, "model", model_decomposer)
        dec_node.primary_provider = dec_route.primary.provider
        dec_node.primary_model = dec_route.primary.model
        dec_node.fallback_used = getattr(call_res, "fallback_used", False)
        dec_node.fallback_reason = getattr(call_res, "fallback_reason", None)

        # Validate DAG and enforce at most 6 sections (Section 6.1)
        subproblems_raw = out.get("subproblems", [])
        if len(subproblems_raw) > 6:
            subproblems_raw = subproblems_raw[:6]

        if not subproblems_raw:
            # An empty plan must never be "accepted": ask once for a real
            # list of sections, then fail honestly if none arrives.
            await self.emit_event(
                Event(
                    run_id=run_id,
                    seq=0,
                    timestamp=time.strftime("%H:%M:%S"),
                    event_type="log_line",
                    payload={
                        "stage": "decomposition",
                        "severity": "warning",
                        "text": "Decomposition returned no sections. Requesting one repair attempt...",
                        "node_id": dec_node.id,
                    },
                )
            )
            repair_out, r_in, r_cached, r_out, r_cost = await self.client.call(
                role="decomposer",
                prompt=(
                    f"Problem statement: {problem}\n\n"
                    "Your previous reply contained no sections. Return a JSON object with a non-empty "
                    "'subproblems' list of 2 to 6 concrete sections in dependency order. Each item must have: "
                    "index, title, target_claim, dependencies. Also include 'latex_skeleton' with %% SECTION_BODY_1 %% style placeholders."
                ),
                model=model_decomposer,
                schema=SectionPlan,
                stable_prefix=knowledge_prefix,
                reasoning_effort="high",
            )
            t_in += r_in
            t_cached += r_cached
            t_out += r_out
            cost += r_cost
            out = repair_out
            subproblems_raw = out.get("subproblems", [])[:6]
            if not subproblems_raw:
                raise RuntimeError("Decomposition produced no sections, so no proof could be written.")

        try:
            topo_order = self.validate_acyclic(subproblems_raw)
        except CycleDetectedError as err:
            # Section 6.1: Ask once for a repair if cyclic
            await self.emit_event(
                Event(
                    run_id=run_id,
                    seq=0,
                    timestamp=time.strftime("%H:%M:%S"),
                    event_type="log_line",
                    payload={
                        "stage": "decomposition",
                        "severity": "warning",
                        "text": f"Cycle detected in decomposition: {err}. Requesting one-time repair from decomposer...",
                        "node_id": dec_node.id,
                    },
                )
            )
            repair_prompt = (
                f"Problem statement: {problem}\n\n"
                f"The decomposition produced a cycle error: {err}.\n"
                "Repair this decomposition into an ordered list of at most 6 subproblems forming a strict Directed Acyclic Graph (DAG) without cycles.\n"
                "Each subproblem must specify: index, title, target_claim, and dependencies."
            )
            repair_out, r_in, r_cached, r_out, r_cost = await self.client.call(
                role="decomposer",
                prompt=repair_prompt,
                model=model_decomposer,
                schema=SectionPlan,
                stable_prefix=knowledge_prefix,
                reasoning_effort="high",
            )
            t_in += r_in
            t_cached += r_cached
            t_out += r_out
            cost += r_cost
            out = repair_out
            subproblems_raw = out.get("subproblems", [])[:6]
            topo_order = self.validate_acyclic(subproblems_raw)

        # Compute Danus SHA-256 fingerprints in topological order
        subproblems_by_index = {sp["index"]: sp for sp in subproblems_raw}
        subproblem_fps: Dict[int, str] = {}
        for idx in topo_order:
            sp = subproblems_by_index[idx]
            dep_fps = {str(dep): subproblem_fps[dep] for dep in sp.get("dependencies", []) if dep in subproblem_fps}
            fp = compute_danus_fingerprint(sp.get("target_claim", ""), sp.get("title", ""), dep_fps)
            sp["danus_fingerprint"] = fp
            sp["dependency_fingerprints"] = dep_fps
            subproblem_fps[idx] = fp

        dec_node.output = out
        dec_node.tokens_in = t_in
        dec_node.tokens_cached = t_cached
        dec_node.tokens_out = t_out
        dec_node.cost_usd = cost
        dec_node.status = "accepted"
        dec_node.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")

        self.save_node(run_id, dec_node)
        await self.emit_event(
            Event(
                run_id=run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="node_updated",
                payload={"node": dec_node.model_dump()},
            )
        )
        await self.emit_event(
            Event(
                run_id=run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="log_line",
                payload={
                    "stage": "decomposition",
                    "severity": "info",
                    "text": (
                        f"Decomposition accepted: {len(subproblems_raw)} subproblems topologically sorted. "
                        f"Danus SHA-256 fingerprints initialized (e.g. SEC_1: {subproblem_fps.get(1, '')[:8]}...)."
                    ),
                    "node_id": dec_node.id,
                },
            )
        )

        plan = SectionPlan(
            subproblems=[SubproblemSpec(**sp) for sp in subproblems_raw],
            latex_skeleton=out.get("latex_skeleton", ""),
        )
        return dec_node, plan
