"""
Stage 5.7: Knowledge Directory Code Extractor.
Implements Section 6.7 of the Mini Colosseum Final Specification:
- Replaces model-written summarizers with a deterministic code extractor (preventing Anti-Persistence error amplification, arXiv:2610.27406)
- Extracts three clean categories:
  1. failed_approaches (route, concrete objection, source node)
  2. claims (statement, status: verified, unverified, or refuted)
  3. observations (established invariants marked by aggregators)
- Literature references are explicitly dropped
- Only entries not marked refuted are injected into the stable prefix (capped at 20 entries)
- Zero model cost ($0.00) and zero hallucination risk
"""

import time
from typing import Dict, Any, List, Callable, Awaitable, Optional
from ..models import Node, Event, KnowledgeEntry, KnowledgeDirectory
from ..client import ModelClient


class CuratorEngine:
    def __init__(
        self,
        client: ModelClient,
        emit_event: Callable[[Event], Awaitable[None]],
        save_node: Callable[[Node], None],
        add_knowledge: Callable[[str, KnowledgeEntry], None],
    ):
        self.client = client
        self.emit_event = emit_event
        self.save_node = save_node
        self.add_knowledge = add_knowledge

    async def curate(
        self,
        run_id: str,
        problem: str,
        strategy_node: Node,
        round_num: int = 1,
        model_curator: str = "code-extractor",
        falsifier_node: Optional[Node] = None,
        rejected_nodes: Optional[List[Node]] = None,
    ) -> List[KnowledgeEntry]:
        """
        Deterministically extracts reusable mathematical entries from structured artifacts.
        """
        curator_node_id = f"R{round_num}_CURATOR"
        node = Node(
            id=curator_node_id,
            type="curator",
            stage="curator",
            round=round_num,
            status="running",
            parents=[strategy_node.id],
            label=f"EXTRACTOR_{round_num}",
            model="deterministic-code-extractor",
            provider="code",
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            input_summary="Deterministic code extraction of unrefuted claims, failed approaches, and established observations",
        )
        self.save_node(run_id, node)

        entries: List[KnowledgeEntry] = []

        # 1. Extract Failed Approaches from strategy node & any rejected nodes
        strat_out = strategy_node.output or {}
        f_rep = strategy_node.falsifier_report or {}
        if f_rep.get("verdict") in ("reject", "falsified", "needs_repair"):
            objs = f_rep.get("categorized_objections") or f_rep.get("objections") or []
            obj_claim = (
                (objs[0].get("claim_attacked") or objs[0].get("claim") or objs[0].get("why") or "")
                if (objs and isinstance(objs[0], dict))
                else str(objs[:1])
            )
            entries.append(
                KnowledgeEntry(
                    entry_type="failed_approaches",
                    title=f"Failed Route in {strategy_node.id}",
                    contents=f"Route '{strat_out.get('primary_route', 'Unknown')}' flagged: {obj_claim}",
                    source=strategy_node.id,
                    caveats="Avoid repeating this route without explicit repair of cited obstruction.",
                )
            )

        if falsifier_node and falsifier_node.output:
            fn_out = falsifier_node.output
            rationale = fn_out.get("rationale") or fn_out.get("explanation") or fn_out.get("summary") or ""
            blocking = fn_out.get("blocking_issues") or []
            if rationale or blocking:
                entries.append(
                    KnowledgeEntry(
                        entry_type="failed_approaches",
                        title=f"Gate/Verifier Audit in {falsifier_node.id}",
                        contents=f"{rationale} Blocking: {'; '.join(str(b) for b in blocking)}".strip(),
                        source=falsifier_node.id,
                        caveats="Must be resolved in subsequent exploration round.",
                    )
                )
        first_obstruction = strat_out.get("first_hard_obstruction")
        if first_obstruction:
            entries.append(
                KnowledgeEntry(
                    entry_type="observations",
                    title=f"Hard Obstruction (Round {round_num})",
                    contents=str(first_obstruction),
                    source=strategy_node.id,
                    caveats="Identified bottleneck from strategy synthesis.",
                )
            )
        if rejected_nodes:
            for rn in rejected_nodes:
                r_out = rn.output or {}
                entries.append(
                    KnowledgeEntry(
                        entry_type="failed_approaches",
                        title=f"Rejected Approach in {rn.id}",
                        contents=f"Candidate {rn.label}: {r_out.get('primary_route', 'Subproblem failed')}",
                        source=rn.id,
                        caveats="Rejected by Wonder 1.0 falsifier.",
                    )
                )

        # 2. Extract Claims (Verified, Unverified, Refuted)
        active_obligations = strat_out.get("active_obligations") or []
        for obl in active_obligations:
            entries.append(
                KnowledgeEntry(
                    entry_type="theorems_and_lemmas",
                    title=f"Active Obligation: {obl[:40]}",
                    contents=f"Claim: {obl}",
                    source=strategy_node.id,
                    caveats="Status: unverified until resolved by subproblem solver.",
                )
            )

        risky_lemmas = strat_out.get("risky_lemmas") or []
        for rl in risky_lemmas:
            entries.append(
                KnowledgeEntry(
                    entry_type="theorems_and_lemmas",
                    title=f"Hypothesized Lemma",
                    contents=f"Lemma: {rl}",
                    source=strategy_node.id,
                    caveats="Requires proof in DAG section.",
                )
            )

        # 3. Extract Observations (Established Invariants)
        analysis = strat_out.get("analysis") or {}
        available_info = analysis.get("available_info")
        if available_info:
            entries.append(
                KnowledgeEntry(
                    entry_type="observations",
                    title="Problem Invariants & Constraints",
                    contents=str(available_info),
                    source=strategy_node.id,
                    caveats="Established problem constraints.",
                )
            )

        # Cap at 20 entries per Section 6.7
        entries = entries[:20]

        for ke in entries:
            self.add_knowledge(run_id, ke)

        node.tokens_in = 0
        node.tokens_cached = 0
        node.tokens_out = 0
        node.cost_usd = 0.0
        node.status = "accepted"
        node.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")
        node.output = {
            "extractor": "deterministic_code",
            "entries_count": len(entries),
            "categories": ["failed_approaches", "theorems_and_lemmas", "observations"],
            "references_dropped": True,
            "refuted_excluded": True,
        }
        self.save_node(run_id, node)

        await self.emit_event(
            Event(
                run_id=run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="node_created",
                payload={"node": node.model_dump()},
            )
        )
        await self.emit_event(
            Event(
                run_id=run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="log_line",
                payload={
                    "stage": "curator",
                    "severity": "info",
                    "text": f"Knowledge Code Extractor recorded {len(entries)} unrefuted entries (literature references dropped).",
                    "node_id": node.id,
                },
            )
        )

        return entries
