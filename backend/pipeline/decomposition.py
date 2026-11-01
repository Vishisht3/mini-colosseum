"""
Stage 3: Proof Decomposition Engine & Cycle Detection.
Based on Section 5.3 of Mini-Colosseum Specification v1.0.
- Converts approved strategy into numbered subproblems in topological order
- Each subproblem lists dependencies forming a DAG
- Validates that graph is strictly acyclic (rejects cycles)
- Generates LaTeX master-document skeleton with reserved placeholders
"""

import time
from typing import Dict, Any, List, Callable, Awaitable, Tuple
from ..models import Node, Edge, Event, SectionPlan, SubproblemSpec
from ..client import ModelClient


class CycleDetectedError(Exception):
    """Raised when decomposition contains a dependency cycle."""
    pass


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
        Decomposes approved strategy into topological subproblems and LaTeX skeleton.
        """
        dec_node_id = f"R{round_num}_DEC"
        dec_node = Node(
            id=dec_node_id,
            type="decomposer",
            stage="decomposition",
            round=round_num,
            status="running",
            parents=[strategy_root.id],
            label=f"DEC_{round_num}",
            model=model_decomposer,
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            input_summary="Decompose approved strategy into topological subproblem DAG",
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

        out, t_in, t_cached, t_out, cost = await self.client.call(
            role="decomposer",
            prompt=prompt,
            model=model_decomposer,
            schema=SectionPlan,
            stable_prefix=knowledge_prefix,
            reasoning_effort="high",
            context_hints={"problem": problem, "node_id": dec_node_id, "round": round_num},
        )

        # Validate DAG
        subproblems_raw = out.get("subproblems", [])
        self.validate_acyclic(subproblems_raw)

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
                    "text": f"Decomposition accepted: {len(subproblems_raw)} subproblems generated in topological order.",
                    "node_id": dec_node.id,
                },
            )
        )

        plan = SectionPlan(
            subproblems=[SubproblemSpec(**sp) for sp in subproblems_raw],
            latex_skeleton=out.get("latex_skeleton", ""),
        )
        return dec_node, plan
