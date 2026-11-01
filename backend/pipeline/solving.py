"""
Stage 4: Subproblem Solving with DAG Scheduler & Local Retry.
Based on Section 5.4 of Mini-Colosseum Specification v1.0.
- A subproblem is eligible once all its dependencies are accepted.
- Eligible sections run in parallel.
- Local falsifier classifies section as ready, conditional, or rejected.
- On rejection, only that section visibly retries on its own node while all other sections stay untouched.
- Retry count increments on the node.
- Accepted bodies replace placeholders in the LaTeX skeleton.
"""

import asyncio
import time
from typing import Dict, Any, List, Callable, Awaitable, Tuple
from ..models import Node, Edge, Event, SectionPlan, SubproblemSpec
from ..client import ModelClient


class SectionSolvingEngine:
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

    async def solve_plan(
        self,
        run_id: str,
        problem: str,
        plan: SectionPlan,
        round_num: int = 1,
        knowledge_prefix: str = "",
        model_solver: str = "muse-spark-1.3",
        model_falsifier: str = "muse-spark-1.3",
        force_section2_retry: bool = False,
    ) -> Tuple[Dict[int, str], str]:
        """
        Executes DAG scheduler:
        - Resolves subproblems according to topological dependency edges
        - Runs eligible independent sections concurrently
        - Performs local retry if a section is rejected
        Returns (completed_section_bodies, assembled_latex_document)
        """
        await self.emit_event(
            Event(
                run_id=run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="stage_changed",
                payload={"stage": "solving", "round": round_num},
            )
        )

        subproblems = {sp.index: sp for sp in plan.subproblems}
        section_nodes: Dict[int, Node] = {}
        completed_bodies: Dict[int, str] = {}
        accepted_indices = set()
        latex_skeleton = plan.latex_skeleton

        # Initialize section nodes in Proof DAG
        for idx, sp in subproblems.items():
            node_id = f"SEC_{sp.index}"
            parent_node_ids = [f"SEC_{dep}" for dep in sp.dependencies]
            node = Node(
                id=node_id,
                type="solver",
                stage="solving",
                round=round_num,
                status="pending",
                parents=parent_node_ids,
                label=f"SEC_{sp.index}",
                model=model_solver,
                input_summary=f"Subproblem {sp.index}: {sp.title}",
                output={"target_claim": sp.target_claim, "title": sp.title},
            )
            section_nodes[idx] = node
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

            # Emit dependency edges for DAG tab
            for dep in sp.dependencies:
                edge = Edge(source=f"SEC_{dep}", target=node.id, type="dependency")
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

        # DAG scheduler loop
        max_retries_per_section = 2
        in_flight_tasks: Dict[int, asyncio.Task] = {}

        async def solve_single_section(idx: int, retry_count: int, prior_critique: str = "") -> bool:
            sp = subproblems[idx]
            node = section_nodes[idx]
            node.status = "running"
            node.retry_count = retry_count
            node.started_at = time.strftime("%Y-%m-%d %H:%M:%S")

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
                        "stage": "solving",
                        "severity": "info",
                        "text": f"Solving Section {sp.index}: '{sp.title}' (attempt {retry_count + 1})",
                        "node_id": node.id,
                    },
                )
            )

            # Prepare context from accepted upstream sections
            dep_context = "\n\n".join(
                [f"=== Upstream Section {dep} ({subproblems[dep].title}) ===\n{completed_bodies.get(dep, '')}" for dep in sp.dependencies]
            )

            solve_prompt = (
                f"Problem: {problem}\n\n"
                f"Section to prove: Section {sp.index}: {sp.title}\n"
                f"Target Claim: {sp.target_claim}\n\n"
                f"Established Upstream Lemmas:\n{dep_context}\n"
            )
            if prior_critique:
                solve_prompt += f"\n\nPrior Attempt Critique (MUST BE REPAIRED):\n{prior_critique}"

            s_out, s_in, s_cached, s_out_tok, s_cost = await self.client.call(
                role="solver",
                prompt=solve_prompt,
                model=model_solver,
                stable_prefix=knowledge_prefix,
                reasoning_effort="medium",
                context_hints={
                    "problem": problem,
                    "section_index": idx,
                    "retry_count": retry_count,
                    "force_retry": force_section2_retry,
                },
            )

            node.output = s_out
            node.tokens_in += s_in
            node.tokens_cached += s_cached
            node.tokens_out += s_out_tok
            node.cost_usd += s_cost

            # Run Section Falsifier
            falsify_prompt = (
                f"Section {sp.index} Claim: {sp.target_claim}\n\n"
                f"Proposed Solution Body:\n{s_out.get('solution_body', '')}\n\n"
                f"Audit this section solution rigorously. Any explicit gap must prevent 'ready'. "
                f"Return verdict ('ready', 'conditional', 'rejected'), fatal_objections, assessment, and suggested_repair."
            )

            f_out, f_in, f_cached, f_out_tok, f_cost = await self.client.call(
                role="section_falsifier",
                prompt=falsify_prompt,
                model=model_falsifier,
                stable_prefix=knowledge_prefix,
                reasoning_effort="medium",
                context_hints={
                    "section_index": idx,
                    "retry_count": retry_count,
                    "force_retry": force_section2_retry,
                },
            )

            node.tokens_in += f_in
            node.tokens_cached += f_cached
            node.tokens_out += f_out_tok
            node.cost_usd += f_cost
            node.falsifier_report = f_out
            node.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")

            f_verdict = f_out.get("verdict", "ready")
            if f_verdict == "ready":
                node.status = "accepted"
                completed_bodies[idx] = s_out.get("solution_body", "")
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
                            "stage": "solving",
                            "severity": "info",
                            "text": f"Section {sp.index} accepted: review passed.",
                            "node_id": node.id,
                        },
                    )
                )
                return True
            else:
                # Section Rejected / Conditional -> triggers local retry!
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
                critique_msg = f_out.get("assessment", "Fatal objections present.")
                await self.emit_event(
                    Event(
                        run_id=run_id,
                        seq=0,
                        timestamp=time.strftime("%H:%M:%S"),
                        event_type="log_line",
                        payload={
                            "stage": "solving",
                            "severity": "warning",
                            "text": f"Section {sp.index} rejected by falsifier: {critique_msg}. Triggering local retry...",
                            "node_id": node.id,
                        },
                    )
                )

                if retry_count < max_retries_per_section:
                    await asyncio.sleep(0.3)
                    # Retry locally with critique
                    return await solve_single_section(idx, retry_count + 1, prior_critique=critique_msg)
                else:
                    node.status = "error"
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
                    return False

        # Schedule loop
        while len(accepted_indices) < len(subproblems):
            # Find eligible sections whose dependencies are met
            eligible = [
                idx for idx, sp in subproblems.items()
                if idx not in accepted_indices
                and idx not in in_flight_tasks
                and all(dep in accepted_indices for dep in sp.dependencies)
            ]

            if not eligible and not in_flight_tasks:
                # Stalled or error
                break

            for el in eligible:
                task = asyncio.create_task(solve_single_section(el, 0))
                in_flight_tasks[el] = task

            # Wait for at least one in-flight task to complete
            done, _ = await asyncio.wait(
                list(in_flight_tasks.values()),
                return_when=asyncio.FIRST_COMPLETED,
            )

            completed_indices = [idx for idx, t in in_flight_tasks.items() if t in done]
            for c_idx in completed_indices:
                success = in_flight_tasks[c_idx].result()
                del in_flight_tasks[c_idx]
                if success:
                    accepted_indices.add(c_idx)

        # Assemble LaTeX document
        assembled_latex = latex_skeleton
        for idx, body in completed_bodies.items():
            placeholder = f"%% SECTION_BODY_{idx} %%"
            if placeholder in assembled_latex:
                assembled_latex = assembled_latex.replace(placeholder, body)
            else:
                assembled_latex += f"\n\n% Section {idx}\n{body}"

        return completed_bodies, assembled_latex
