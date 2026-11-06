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
from ..models import Node, Event, GateDecision
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
        gate_route = self.client.get_route("gate", model_override=model_gate)
        gate_node = Node(
            id=gate_node_id,
            type="gate",
            stage="gate",
            round=round_num,
            status="running",
            parents=[root_node.id],
            label=f"GATE_{round_num}",
            model=gate_route.primary.model,
            provider=gate_route.primary.provider,
            primary_provider=gate_route.primary.provider,
            primary_model=gate_route.primary.model,
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
            "Audit this strategy card thoroughly per Section 6.1 and Appendix A:\n"
            "1. Fatal bridge claims: are there unproven leaps of faith?\n"
            "2. Cited theorems: are hypotheses properly satisfied?\n"
            "3. Target equivalence: does this actually prove the target statement?\n"
            "4. Hidden hard steps: is a difficult subproblem swept under the rug?\n"
            "5. Unresolved falsifier objections.\n\n"
            "Return JSON matching Appendix A Gate Decision schema:\n"
            "- decision: 'ready', 'ready_with_obligations', 'explore_more', or 'reject'\n"
            "- blocking_issues: list of fatal issues (if any)\n"
            "- obligations: list of objects {id, severity ('minor' or 'major'), assigned_section}\n"
            "- rationale: explanation of the readiness evaluation\n"
            "Rule: Obligations are the steps the later writing stage exists to carry out. If the route is sound and every obligation is assigned to a concrete section and is a provable step (including citing and applying a standard theorem with its hypotheses checked in that section), return 'ready_with_obligations' and pass the obligations on. Return 'explore_more' only when the route itself is incomplete or truncated, an obligation has no assigned section, or a bridge claim is false or cannot be proved as stated.\n"
            "Judge readiness against the strategy's own stated goal: if the goal is to prove stated bounds, "
            "do not require an exact answer beyond those bounds, and do not treat a hard step as hidden "
            "when the strategy lists it as an explicit subproblem to be proved."
        )

        call_res = await self.client.call(
            role="gate",
            prompt=prompt,
            model=model_gate,
            schema=GateDecision,
            stable_prefix=knowledge_prefix,
            reasoning_effort="high",
            context_hints={"problem": problem, "node_id": gate_node_id, "round": round_num},
        )
        out, t_in, t_cached, t_out, cost = call_res

        gate_node.output = out
        gate_node.tokens_in = t_in
        gate_node.tokens_cached = t_cached
        gate_node.tokens_out = t_out
        gate_node.cost_usd = cost
        gate_node.provider = getattr(call_res, "provider", "meta")
        gate_node.model = getattr(call_res, "model", model_gate)
        gate_node.primary_provider = gate_route.primary.provider
        gate_node.primary_model = gate_route.primary.model
        gate_node.fallback_used = getattr(call_res, "fallback_used", False)
        gate_node.fallback_reason = getattr(call_res, "fallback_reason", None)
        gate_node.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")

        decision = out.get("decision") or out.get("verdict", "ready")
        # Check for major obligations
        obligations = out.get("obligations", [])
        has_major = any(o.get("severity") == "major" and not o.get("assigned_section") for o in obligations if isinstance(o, dict))

        if has_major and decision in ["ready", "ready_with_obligations"]:
            decision = "explore_more"

        if decision in ["ready", "ready for decomposition"]:
            gate_node.status = "accepted"
            verdict = "ready for decomposition"
        elif decision in ["ready_with_obligations", "eligible with explicit obligations"]:
            gate_node.status = "conditional"
            verdict = "eligible with explicit obligations"
        elif decision == "explore_more":
            gate_node.status = "rejected"
            verdict = "needs further exploration"
        else:
            gate_node.status = "rejected"
            verdict = "reject"

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
                    "text": f"Readiness Gate verdict: {verdict}. {out.get('rationale') or out.get('explanation', '')}",
                    "node_id": gate_node.id,
                },
            )
        )

        return gate_node, verdict
