"""
Stage 2: Readiness Gate Engine.
Based on Section 5.2 of Mini-Colosseum Specification v1.0.
Audits:
- Fatal bridge claims
- Cited theorems and hypotheses
- Target equivalence
- Hidden hard steps
- Unresolved falsifier objections
Returns one of four verdicts:
1. ready for decomposition
2. eligible with explicit obligations
3. needs further exploration
4. reject
"""

import time
from typing import Dict, Any, Callable, Awaitable, Tuple
from ..models import Node, Event
from ..client import ModelClient


class ReadinessGateEngine:
    def __init__(
        self,
        client: ModelClient,
        emit_event: Callable[[Event], Awaitable[None]],
        save_node: Callable[[Node], None],
    ):
        self.client = client
        self.emit_event = emit_event
        self.save_node = save_node

    async def evaluate(
        self,
        run_id: str,
        problem: str,
        root_node: Node,
        round_num: int = 1,
        knowledge_prefix: str = "",
        model_gate: str = "muse-wonder-1.0",
    ) -> Tuple[Node, str]:
        """
        Evaluate readiness gate on the approved exploration root.
        Returns: (gate_node, verdict)
        """
        gate_node_id = f"R{round_num}_GATE"
        gate_node = Node(
            id=gate_node_id,
            type="gate",
            stage="gate",
            round=round_num,
            status="running",
            parents=[root_node.id],
            label=f"GATE_{round_num}",
            model=model_gate,
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            input_summary=f"Audit root candidate {root_node.label} for decomposition readiness",
        )
        self.save_node(run_id, gate_node)

        await self.emit_event(
            Event(
                run_id=run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="stage_changed",
                payload={"stage": "gate", "round": round_num},
            )
        )
        await self.emit_event(
            Event(
                run_id=run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="node_created",
                payload={"node": gate_node.model_dump()},
            )
        )

        prompt = (
            f"Original Problem: {problem}\n\n"
            f"Candidate Root Strategy to Audit:\n{root_node.output}\n\n"
            f"Falsifier Attacks and Objections:\n{root_node.falsifier_report}\n\n"
            "Audit this strategy card thoroughly:\n"
            "1. Fatal bridge claims: are there unproven leaps of faith?\n"
            "2. Cited theorems: are hypotheses properly satisfied?\n"
            "3. Target equivalence: does this actually prove the target statement?\n"
            "4. Hidden hard steps: is a difficult subproblem swept under the rug?\n"
            "5. Unresolved falsifier objections.\n\n"
            "Return JSON with verdict ('ready for decomposition', 'eligible with explicit obligations', 'needs further exploration', or 'reject'), "
            "fatal_bridge_claims, cited_theorems, target_equivalence, hidden_hard_steps, obligation_severity ('none', 'minor', 'major'), and explanation."
        )

        out, t_in, t_cached, t_out, cost = await self.client.call(
            role="gate",
            prompt=prompt,
            model=model_gate,
            stable_prefix=knowledge_prefix,
            reasoning_effort="high",
            context_hints={"problem": problem, "node_id": gate_node_id, "round": round_num},
        )

        gate_node.output = out
        gate_node.tokens_in = t_in
        gate_node.tokens_cached = t_cached
        gate_node.tokens_out = t_out
        gate_node.cost_usd = cost
        gate_node.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")

        verdict = out.get("verdict", "ready for decomposition")
        if verdict in ["ready for decomposition", "eligible with explicit obligations"]:
            gate_node.status = "accepted" if verdict == "ready for decomposition" else "conditional"
        else:
            gate_node.status = "rejected"

        self.save_node(run_id, gate_node)
        await self.emit_event(
            Event(
                run_id=run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="node_updated",
                payload={"node": gate_node.model_dump()},
            )
        )
        await self.emit_event(
            Event(
                run_id=run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="log_line",
                payload={
                    "stage": "gate",
                    "severity": "info" if gate_node.status == "accepted" else "warning",
                    "text": f"Readiness Gate verdict: {verdict}. {out.get('explanation', '')}",
                    "node_id": gate_node.id,
                },
            )
        )

        return gate_node, verdict
