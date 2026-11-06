"""
Stage 1: Strategy Exploration Engine with Overlapping Tree Aggregation.
Based on Section 5.1 of Mini-Colosseum Specification v1.0.
Implements the core paper mechanism:
- Generates leaf strategy candidates
- Paired falsifiers attack each candidate
- Level-by-level contraction tree where each aggregator draws k distinct inputs uniformly at random from below
- Overlapping reuse: candidate nodes may be consumed by multiple aggregation nodes
"""

import asyncio
import random
import time
from typing import List, Dict, Any, Callable, Awaitable
from ..models import Node, Edge, Event, StrategyCard, FalsifierReport
from ..client import ModelClient


class ExplorationEngine:
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

    async def run_exploration(
        self,
        run_id: str,
        problem: str,
        widths: List[int],
        k: int,
        round_num: int = 1,
        knowledge_prefix: str = "",
        model_explorer: str = "muse-spark-1.3",
        model_falsifier: str = "muse-spark-1.3",
        model_aggregator: str = "muse-spark-1.3",
        prior_context: str = "",
    ) -> Node:
        """
        Runs the full multi-level overlapping tree aggregation.
        Returns the root aggregator Node.
        """
        await self.emit_event(
            Event(
                run_id=run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="stage_changed",
                payload={"stage": "exploration", "round": round_num},
            )
        )
        await self.emit_event(
            Event(
                run_id=run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="log_line",
                payload={
                    "stage": "exploration",
                    "severity": "info",
                    "text": f"Starting Exploration Round {round_num} with widths {widths}, k={k}",
                },
            )
        )

        leaf_width = widths[0]
        current_level_nodes: List[Node] = []

        # --- LEVEL 0: Generate Leaf Candidates and Attack them with Paired Falsifiers ---
        async def create_leaf(idx: int) -> Node:
            node_id = f"R{round_num}_L0_{idx+1}"
            label = f"S{idx+1}" if round_num == 1 else f"R{round_num}.S{idx+1}"
            exp_route = self.client.get_route("explorer", model_override=model_explorer)
            node = Node(
                id=node_id,
                type="explorer",
                stage="exploration",
                round=round_num,
                status="running",
                parents=[],
                label=label,
                model=exp_route.primary.model,
                provider=exp_route.primary.provider,
                primary_model=exp_route.primary.model,
                primary_provider=exp_route.primary.provider,
                started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                input_summary=f"Generate candidate research strategy for problem: {problem[:60]}...",
            )
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

            # Prompt explorer
            prompt = (
                f"Problem statement: {problem}\n\n"
                f"You are Candidate Generator {idx+1}. Propose a distinct, rigorous strategy route to prove this statement.\n"
                f"Focus on candidate lemmas, primary route, potential obstruction, and active obligations."
            )
            if prior_context:
                prompt += f"\n\nPrior round context and rejected aspects:\n{prior_context}"

            call_res = await self.client.call(
                role="explorer",
                prompt=prompt,
                model=model_explorer,
                schema=StrategyCard,
                stable_prefix=knowledge_prefix,
                reasoning_effort="low",
                context_hints={"problem": problem, "node_id": node_id, "round": round_num},
            )
            out, t_in, t_cached, t_out, cost = call_res

            node.output = out
            node.analysis = out.get("analysis")
            node.tokens_in = t_in
            node.tokens_cached = t_cached
            node.tokens_out = t_out
            node.cost_usd = cost
            node.provider = getattr(call_res, "provider", "meta")
            node.model = getattr(call_res, "model", model_explorer)
            node.primary_provider = exp_route.primary.provider
            node.primary_model = exp_route.primary.model
            node.fallback_used = getattr(call_res, "fallback_used", False)
            node.fallback_reason = getattr(call_res, "fallback_reason", None)

            # Paired Falsifier Attack
            await self.emit_event(
                Event(
                    run_id=run_id,
                    seq=0,
                    timestamp=time.strftime("%H:%M:%S"),
                    event_type="log_line",
                    payload={
                        "stage": "exploration",
                        "severity": "info",
                        "text": f"Falsifier attacking candidate {node.label}...",
                        "node_id": node.id,
                    },
                )
            )

            falsifier_prompt = (
                f"Problem: {problem}\n\n"
                f"Candidate Strategy to attack:\n{out}\n\n"
                f"Scrutinize this strategy. Identify weakest central lemmas, hidden assumptions, "
                f"boundary cases, and potential theorem misuse. Assign a verdict: survives, needs_repair, reject, or falsified."
            )

            # One unreadable checker reply must not kill the whole run:
            # treat the candidate as needing repair and carry on.
            f_out, f_in, f_cached, f_out_tok, f_cost = {}, 0, 0, 0, 0.0
            try:
                f_out, f_in, f_cached, f_out_tok, f_cost = await self.client.call(
                    role="falsifier",
                    prompt=falsifier_prompt,
                    model=model_falsifier,
                    schema=FalsifierReport,
                    stable_prefix=knowledge_prefix,
                    reasoning_effort="medium",
                    context_hints={"problem": problem, "node_id": node_id, "round": round_num},
                )
            except Exception as falsifier_exc:
                f_out = {
                    "verdict": "needs_repair",
                    "assessment": f"Checker reply could not be read ({falsifier_exc}). Candidate kept for repair.",
                    "objections": [],
                    "categorized_objections": [],
                }
                await self.emit_event(
                    Event(
                        run_id=run_id,
                        seq=0,
                        timestamp=time.strftime("%H:%M:%S"),
                        event_type="log_line",
                        payload={
                            "stage": "exploration",
                            "severity": "warning",
                            "text": f"Falsifier reply for candidate {node.label} could not be read; candidate marked as needing repair.",
                            "node_id": node.id,
                        },
                    )
                )

            node.tokens_in += f_in
            node.tokens_cached += f_cached
            node.tokens_out += f_out_tok
            node.cost_usd += f_cost
            node.falsifier_report = f_out
            node.objections = f_out.get("categorized_objections") or f_out.get("objections", [])
            node.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")

            verdict = f_out.get("verdict", "survives")
            if verdict == "survives":
                node.status = "accepted"
            elif verdict == "needs_repair":
                node.status = "conditional"
            else:
                node.status = "rejected"

            self.save_node(run_id, node)
            await self.emit_event(
                Event(
                    run_id=run_id,
                    seq=0,
                    timestamp=time.strftime("%H:%M:%S"),
                    event_type="node_updated",
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
                        "stage": "exploration",
                        "severity": "warning" if verdict in ["needs_repair", "rejected"] else "info",
                        "text": f"Falsifier({node.label}) verdict: {verdict}",
                        "node_id": node.id,
                    },
                )
            )
            return node

        # Launch all leaf explorers in parallel
        leaf_tasks = [create_leaf(i) for i in range(leaf_width)]
        current_level_nodes = await asyncio.gather(*leaf_tasks)

        # --- LEVEL 1 to ROOT: Overlapping Random-Sample Tree Aggregation ---
        for level_idx, width in enumerate(widths[1:], start=1):
            next_level_nodes: List[Node] = []
            is_root = (level_idx == len(widths) - 1) and (width == 1)

            async def create_aggregator(agg_idx: int) -> Node:
                node_id = f"R{round_num}_L{level_idx}_{agg_idx+1}"
                if is_root:
                    label = "ROOT" if round_num == 1 else f"R{round_num}.ROOT"
                else:
                    level_letter = chr(ord('A') + level_idx - 1)
                    label = f"{level_letter}{agg_idx+1}" if round_num == 1 else f"R{round_num}.{level_letter}{agg_idx+1}"

                # Uniform random sampling of k distinct parents from current level without replacement
                parent_count = min(k, len(current_level_nodes))
                sampled_parents = random.sample(current_level_nodes, parent_count)
                parent_ids = [p.id for p in sampled_parents]

                agg_route = self.client.get_route("aggregator", model_override=model_aggregator)
                agg_node = Node(
                    id=node_id,
                    type="aggregator",
                    stage="exploration",
                    round=round_num,
                    status="running",
                    parents=parent_ids,
                    label=label,
                    model=agg_route.primary.model,
                    provider=agg_route.primary.provider,
                    primary_model=agg_route.primary.model,
                    primary_provider=agg_route.primary.provider,
                    started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                    input_summary=f"Aggregate {len(parent_ids)} candidates: {', '.join([p.label for p in sampled_parents])}",
                )
                self.save_node(run_id, agg_node)
                await self.emit_event(
                    Event(
                        run_id=run_id,
                        seq=0,
                        timestamp=time.strftime("%H:%M:%S"),
                        event_type="node_created",
                        payload={"node": agg_node.model_dump()},
                    )
                )

                # Save and emit edges immediately so overlapping reuse is rendered live
                for p in sampled_parents:
                    edge = Edge(source=p.id, target=agg_node.id, type="aggregation")
                    self.save_edge(run_id, edge)
                    await self.emit_event(
                        Event(
                            run_id=run_id,
                            seq=0,
                            timestamp=time.strftime("%H:%M:%S"),
                            event_type="edge_added",
                            payload={"edge": edge.model_dump()},
                        )
                    )

                # Stellar Colosseum: Critique-Preserving Trees
                # Instead of dropping failed outputs, falsifier critiques remain attached
                preserved_critiques = []
                parents_summary = []
                for p in sampled_parents:
                    if p.falsifier_report:
                        preserved_critiques.append({
                            "candidate": p.label,
                            "verdict": p.falsifier_report.get("verdict"),
                            "objections": p.falsifier_report.get("categorized_objections", []),
                            "assessment": p.falsifier_report.get("assessment", ""),
                        })
                    parents_summary.append(
                        f"--- Candidate {p.label} ---\n"
                        f"Output: {p.output}\n"
                        f"Preserved Falsifier Critique & Objections: {p.falsifier_report}\n"
                    )

                prompt = (
                    f"Problem: {problem}\n\n"
                    f"Synthesize the following {len(sampled_parents)} candidate routes with their preserved critiques:\n\n"
                    + "\n".join(parents_summary)
                    + "\n\nProduce one consolidated strategy card. "
                    "Address every serious objection: reject, weaken, repair, refute with a specific reason, or carry forward. "
                    "Never just average or pick one without synthesis."
                )

                call_res = await self.client.call(
                    role="aggregator",
                    prompt=prompt,
                    model=model_aggregator,
                    schema=StrategyCard,
                    stable_prefix=knowledge_prefix,
                    reasoning_effort="medium" if not is_root else "high",
                    context_hints={
                        "problem": problem,
                        "node_id": node_id,
                        "parents": [p.label for p in sampled_parents],
                        "preserved_critiques": preserved_critiques,
                        "round": round_num,
                    },
                )
                out, t_in, t_cached, t_out, cost = call_res
                if not out.get("preserved_critiques"):
                    out["preserved_critiques"] = preserved_critiques

                # Attach falsifier review on aggregator (Section 6.1: receives child reports and flags dropped objections)
                child_critiques_summary = "\n".join([
                    f"- Child candidate '{p.label}' objections: {p.falsifier_report.get('categorized_objections', []) if p.falsifier_report else 'none'}"
                    for p in sampled_parents
                ])
                f_prompt = (
                    f"Problem: {problem}\n\n"
                    f"Aggregated strategy to scrutinize:\n{out}\n\n"
                    f"Child Falsifier Reports from sampled candidates:\n{child_critiques_summary}\n\n"
                    "Scrutinize the aggregated synthesis thoroughly:\n"
                    "1. Evaluate whether the synthesized route resolves or weakens claimed lemmas.\n"
                    "2. CRITICAL AUDIT: Check whether any fatal or major objections from the child reports were improperly "
                    "dropped, bypassed, or ignored without an explicit mathematical resolution. If so, list them in 'dropped_objections'.\n"
                    "3. Assign verdict: survives, needs_repair, reject, or falsified."
                )
                f_out, f_in, f_cached, f_out_tok, f_cost = await self.client.call(
                    role="falsifier",
                    prompt=f_prompt,
                    model=model_falsifier,
                    schema=FalsifierReport,
                    stable_prefix=knowledge_prefix,
                    reasoning_effort="medium",
                    context_hints={
                        "problem": problem,
                        "node_id": node_id,
                        "round": round_num,
                        "child_critiques": preserved_critiques,
                    },
                )

                agg_node.output = out
                agg_node.analysis = out.get("analysis")
                agg_node.provider = getattr(call_res, "provider", "meta")
                agg_node.model = getattr(call_res, "model", model_aggregator)
                agg_node.primary_provider = agg_route.primary.provider
                agg_node.primary_model = agg_route.primary.model
                agg_node.fallback_used = getattr(call_res, "fallback_used", False)
                agg_node.fallback_reason = getattr(call_res, "fallback_reason", None)
                agg_node.falsifier_report = f_out
                agg_node.objections = f_out.get("categorized_objections") or f_out.get("objections", [])
                agg_node.tokens_in = t_in + f_in
                agg_node.tokens_cached = t_cached + f_cached
                agg_node.tokens_out = t_out + f_out_tok
                agg_node.cost_usd = cost + f_cost
                agg_node.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")

                verdict = f_out.get("verdict", "survives")
                agg_node.status = "accepted" if verdict == "survives" else ("conditional" if verdict == "needs_repair" else "rejected")

                self.save_node(run_id, agg_node)
                await self.emit_event(
                    Event(
                        run_id=run_id,
                        seq=0,
                        timestamp=time.strftime("%H:%M:%S"),
                        event_type="node_updated",
                        payload={"node": agg_node.model_dump()},
                    )
                )
                await self.emit_event(
                    Event(
                        run_id=run_id,
                        seq=0,
                        timestamp=time.strftime("%H:%M:%S"),
                        event_type="log_line",
                        payload={
                            "stage": "exploration",
                            "severity": "info",
                            "text": f"Synthesized {agg_node.label} from [{', '.join([p.label for p in sampled_parents])}]",
                            "node_id": agg_node.id,
                        },
                    )
                )
                return agg_node

            agg_tasks = [create_aggregator(i) for i in range(width)]
            next_level_nodes = await asyncio.gather(*agg_tasks)
            current_level_nodes = next_level_nodes

        root_node = current_level_nodes[0]
        await self.emit_event(
            Event(
                run_id=run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="log_line",
                payload={
                    "stage": "exploration",
                    "severity": "info",
                    "text": f"Exploration Round {round_num} complete. Root node {root_node.label} ready for gate.",
                    "node_id": root_node.id,
                },
            )
        )
        return root_node
