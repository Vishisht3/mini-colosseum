"""
Stage 4: Subproblem Solving with (3, 1) Tree Aggregation, Test-Time Scaling & Danus Invalidation.
Implements Section 6.1, Section 6.2, and Appendix B of Mini Colosseum Specification:
- Topological scheduling of subproblem DAG; independent sections run concurrently.
- (3, 1) Section Tree:
  1. 3 Spark Open writers produce distinct proof candidates with structured <analysis>.
  2. A separate Wonder falsifier attacks EACH writer's candidate (critiques attached to each draft).
  3. A Spark Open aggregator synthesizes the candidates with their attached falsifier critiques.
  4. A final Wonder falsifier conducts the local review of the aggregated output.
- Acceptance: 'ready' or 'conditional' is accepted ('conditional' keeps obligations visible).
- Local Retry: 'rejected' retries locally up to 2 times with failed draft + critique, then marked blocked.
- Dependency Invalidation & Stale Re-Review (Section 6.6):
  - Normalized section body hashing (SHA-256) and dependency fingerprints.
  - If upstream section body changes, dependent sections turn STALE and get one Wonder re-review.
  - If a section exhausts retries and is BLOCKED, dependents are marked INVALIDATED.
- HMED Distillation Records: records (failed_draft, critique, revised_draft, downstream_verdict).
"""

import asyncio
import time
from typing import Dict, Any, List, Callable, Awaitable, Tuple, Optional
from ..models import Node, Edge, Event, SectionPlan, SubproblemSpec, HMEDRecord
from ..client import ModelClient
from .decomposition import (
    compute_danus_fingerprint,
    compute_body_hash,
    compute_dependency_fingerprint,
    normalize_section_body,
)


class SectionSolvingEngine:
    def __init__(
        self,
        client: ModelClient,
        emit_event: Callable[[Event], Awaitable[None]],
        save_node: Callable[[Node], None],
        save_edge: Callable[[Edge], None],
        save_hmed: Optional[Callable[[Any], None]] = None,
    ):
        self.client = client
        self.emit_event = emit_event
        self.save_node = save_node
        self.save_edge = save_edge
        self.save_hmed = save_hmed

    async def solve_plan(
        self,
        run_id: str,
        problem: str,
        plan: SectionPlan,
        round_num: int = 1,
        knowledge_prefix: str = "",
        model_solver: str = "meta-models/muse-spark-open-1026",
        model_falsifier: str = "muse-wonder-1.0",
        force_section2_retry: bool = False,
        k_rollouts: int = 3,
    ) -> Tuple[Dict[int, str], str]:
        """
        Executes DAG scheduler using (3, 1) section trees with per-candidate falsifiers:
        - Resolves subproblems according to topological dependency edges.
        - Runs eligible independent sections concurrently.
        - For each section: 3 writers -> 3 paired Wonder falsifiers -> 1 aggregator -> 1 local review.
        - Returns (completed_section_bodies, assembled_latex_document).
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
        section_body_hashes: Dict[int, str] = {}
        subproblem_fps: Dict[int, str] = {sp.index: sp.danus_fingerprint for sp in plan.subproblems}
        accepted_indices = set()
        latex_skeleton = plan.latex_skeleton

        # Initialize section nodes in Proof DAG
        for idx, sp in subproblems.items():
            node_id = f"SEC_{sp.index}"
            parent_node_ids = [f"SEC_{dep}" for dep in sp.dependencies]
            sol_route = self.client.get_route("solver", model_override=model_solver)
            node = Node(
                id=node_id,
                type="solver",
                stage="solving",
                round=round_num,
                status="pending",
                parents=parent_node_ids,
                label=f"SEC_{sp.index}",
                model=sol_route.primary.model,
                provider=sol_route.primary.provider,
                primary_model=sol_route.primary.model,
                primary_provider=sol_route.primary.provider,
                danus_fingerprint=sp.danus_fingerprint,
                is_stale=False,
                is_invalidated=False,
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

        # Number of writers in section tree: default 3 (Section 6.1 / Appendix B)
        n_writers = max(2, min(k_rollouts, 4))
        max_retries_per_section = 2
        in_flight_tasks: Dict[int, asyncio.Task] = {}

        async def solve_single_section(idx: int, retry_count: int, prior_critique: str = "", prior_failed_body: str = "") -> bool:
            sp = subproblems[idx]
            node = section_nodes[idx]
            node.status = "running"
            node.retry_count = retry_count
            node.is_stale = False
            node.is_invalidated = False
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
                        "text": f"Solving Section {sp.index}: '{sp.title}' (attempt {retry_count + 1}, (3,1) tree: {n_writers} writers + per-candidate falsifiers)",
                        "node_id": node.id,
                    },
                )
            )

            # Upstream context
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

            # --- STEP 1: Run N parallel writers (Spark Open) ---
            async def generate_writer_draft(w_num: int) -> Tuple[Dict[str, Any], int, int, int, float]:
                return await self.client.call(
                    role="solver",
                    prompt=solve_prompt + f"\n\n[Writer {w_num}/{n_writers}: Explore distinct proof derivation variant]",
                    model=model_solver,
                    stable_prefix=knowledge_prefix,
                    reasoning_effort="medium",
                    context_hints={
                        "problem": problem,
                        "section_index": idx,
                        "retry_count": retry_count,
                        "force_retry": force_section2_retry,
                        "writer_num": w_num,
                        "target_claim": sp.target_claim,
                    },
                )

            writer_results = await asyncio.gather(*[generate_writer_draft(i) for i in range(1, n_writers + 1)])

            total_s_in = sum(r[1] for r in writer_results)
            total_s_cached = sum(r[2] for r in writer_results)
            total_s_out = sum(r[3] for r in writer_results)
            total_s_cost = sum(r[4] for r in writer_results)

            node.tokens_in += total_s_in
            node.tokens_cached += total_s_cached
            node.tokens_out += total_s_out
            node.cost_usd += total_s_cost

            raw_drafts = [r[0] for r in writer_results]

            # --- STEP 2: Attack EACH writer's draft with a Wonder Falsifier (Section 6.1 / Appendix B) ---
            async def falsify_draft(draft_idx: int, draft: Dict[str, Any]) -> Tuple[Dict[str, Any], int, int, int, float]:
                body = draft.get("solution_body", "")
                f_prompt = (
                    f"Section {sp.index} Claim: {sp.target_claim}\n\n"
                    f"Candidate Proof Body (Writer {draft_idx + 1}):\n{body}\n\n"
                    "Audit this section derivation. Identify any gap, unwarranted leap, boundary issue, or misuse.\n"
                    "Return JSON with: verdict ('survives', 'needs_repair', 'reject', 'falsified'), objections[] {id, severity, claim_attacked, quote, why, cheap_test}."
                )
                return await self.client.call(
                    role="section_falsifier",
                    prompt=f_prompt,
                    model=model_falsifier,
                    stable_prefix=knowledge_prefix,
                    reasoning_effort="medium",
                    context_hints={
                        "section_index": idx,
                        "writer_num": draft_idx + 1,
                        "retry_count": retry_count,
                    },
                )

            falsifier_results = await asyncio.gather(*[falsify_draft(i, d) for i, d in enumerate(raw_drafts)])

            for i, f_res in enumerate(falsifier_results):
                f_out, f_in, f_cached, f_out_tok, f_cost = f_res
                node.tokens_in += f_in
                node.tokens_cached += f_cached
                node.tokens_out += f_out_tok
                node.cost_usd += f_cost
                # Attach critique to candidate (Critique-Preserving Tree Aggregation)
                raw_drafts[i]["falsifier_critique"] = f_out

            node.rollouts = raw_drafts
            sp.rollouts = raw_drafts

            # --- STEP 3: Spark Open Aggregator Synthesizes Drafts + Attached Critiques ---
            agg_prompt = (
                f"Problem: {problem}\n\n"
                f"Section {sp.index}: {sp.title}\n"
                f"Target Claim: {sp.target_claim}\n\n"
                f"You are the Section Aggregator. Synthesize the {n_writers} candidate proof drafts below along with their Wonder falsifier critiques into a single, cohesive, rigorous proof body for this section.\n"
                "Resolve any objections raised by the falsifiers while preserving valid lemmas.\n\n"
            )
            for i, draft in enumerate(raw_drafts):
                critique_summary = draft.get("falsifier_critique", {}).get("assessment", "Audited.")
                agg_prompt += f"--- Candidate {i+1} ---\n{draft.get('solution_body', '')}\nCritique: {critique_summary}\n\n"

            agg_res = await self.client.call(
                role="solver",
                prompt=agg_prompt,
                model=model_solver,
                stable_prefix=knowledge_prefix,
                reasoning_effort="medium",
                context_hints={
                    "section_index": idx,
                    "is_aggregation": True,
                    "force_retry": force_section2_retry,
                    "retry_count": retry_count,
                },
            )
            agg_out, a_in, a_cached, a_out_tok, a_cost = agg_res
            node.tokens_in += a_in
            node.tokens_cached += a_cached
            node.tokens_out += a_out_tok
            node.cost_usd += a_cost

            # Aggregated candidate is primary
            aggregated_solution = agg_out
            if not aggregated_solution.get("solution_body"):
                aggregated_solution["solution_body"] = raw_drafts[0].get("solution_body", "")

            node.output = aggregated_solution
            node.analysis = aggregated_solution.get("analysis") or raw_drafts[0].get("analysis")
            sol_route = self.client.get_route("solver", model_override=model_solver)
            node.provider = getattr(agg_res, "provider", "meta")
            node.model = getattr(agg_res, "model", model_solver)
            node.primary_provider = sol_route.primary.provider
            node.primary_model = sol_route.primary.model
            node.fallback_used = getattr(agg_res, "fallback_used", False)
            node.fallback_reason = getattr(agg_res, "fallback_reason", None)

            # --- STEP 4: Final Wonder Local Review (Section 6.1) ---
            review_prompt = (
                f"Section {sp.index} Claim: {sp.target_claim}\n\n"
                f"Synthesized Section Solution:\n{aggregated_solution.get('solution_body', '')}\n\n"
                "Perform the formal Local Review. Return JSON:\n"
                "verdict ('ready', 'conditional', 'rejected'), fatal_objections[], claims_not_established[], assessment, suggested_repair, exact_quote."
            )
            rev_out, r_in, r_cached, r_out_tok, r_cost = await self.client.call(
                role="section_falsifier",
                prompt=review_prompt,
                model=model_falsifier,
                stable_prefix=knowledge_prefix,
                reasoning_effort="medium",
                context_hints={
                    "section_index": idx,
                    "is_local_review": True,
                    "force_retry": force_section2_retry,
                    "retry_count": retry_count,
                },
            )
            node.tokens_in += r_in
            node.tokens_cached += r_cached
            node.tokens_out += r_out_tok
            node.cost_usd += r_cost
            node.falsifier_report = rev_out
            node.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")

            review_verdict = rev_out.get("verdict", "ready")

            # Section 6.1: Ready or conditional is accepted
            if review_verdict in ["ready", "conditional"]:
                node.status = "accepted" if review_verdict == "ready" else "conditional"
                sol_body = aggregated_solution.get("solution_body", "")
                completed_bodies[idx] = sol_body

                # Body hash and dependency fingerprint (Section 6.6)
                old_body_hash = section_body_hashes.get(idx, "")
                new_body_hash = compute_body_hash(sol_body)
                section_body_hashes[idx] = new_body_hash

                dep_hashes = {str(dep): section_body_hashes.get(dep, "") for dep in sp.dependencies}
                dep_fp = compute_dependency_fingerprint(dep_hashes)
                node.danus_fingerprint = dep_fp
                sp.danus_fingerprint = dep_fp
                subproblem_fps[idx] = dep_fp

                # If body changed after a retry, downstream accepted sections turn STALE and get re-reviewed
                if old_body_hash and new_body_hash != old_body_hash:
                    for downstream_idx, downstream_sp in subproblems.items():
                        if idx in downstream_sp.dependencies and downstream_idx in accepted_indices:
                            downstream_node = section_nodes[downstream_idx]
                            downstream_node.is_stale = True
                            downstream_node.status = "stale"
                            downstream_sp.is_stale = True
                            self.save_node(run_id, downstream_node)
                            await self.emit_event(
                                Event(
                                    run_id=run_id,
                                    seq=0,
                                    timestamp=time.strftime("%H:%M:%S"),
                                    event_type="log_line",
                                    payload={
                                        "stage": "solving",
                                        "severity": "warning",
                                        "text": (
                                            f"[Danus Section Hash] SEC_{idx} body updated ({new_body_hash[:8]}). "
                                            f"Downstream dependency SEC_{downstream_idx} marked STALE; initiating Wonder re-review..."
                                        ),
                                        "node_id": downstream_node.id,
                                    },
                                )
                            )
                            await self.emit_event(
                                Event(
                                    run_id=run_id,
                                    seq=0,
                                    timestamp=time.strftime("%H:%M:%S"),
                                    event_type="node_updated",
                                    payload={"node": downstream_node.model_dump()},
                                )
                            )
                            # Conduct Wonder Re-review on the stale dependent (Section 6.6)
                            await self._re_review_stale_section(
                                run_id=run_id,
                                idx=downstream_idx,
                                sp=downstream_sp,
                                node=downstream_node,
                                current_body=completed_bodies.get(downstream_idx, ""),
                                upstream_context=f"Updated Upstream SEC_{idx}:\n{sol_body}",
                                model_falsifier=model_falsifier,
                                knowledge_prefix=knowledge_prefix,
                            )

                self.save_node(run_id, node)

                # Record revision-consequence tuple for HMED distillation if retried
                if retry_count > 0 and self.save_hmed:
                    hmed = HMEDRecord(
                        record_id=f"HMED-{run_id}-SEC{idx}-{retry_count}",
                        run_id=run_id,
                        stage="solving",
                        subproblem_index=idx,
                        failed_draft=prior_failed_body or prior_critique,
                        critique=prior_critique,
                        revised_draft=sol_body,
                        downstream_verdict=node.status,
                        cost_usd=round(node.cost_usd, 6),
                        model_solver=model_solver,
                        model_falsifier=model_falsifier,
                    )
                    self.save_hmed(hmed)

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
                            "text": f"Section {sp.index} accepted ({node.status}): local review passed (Body Hash: {new_body_hash[:8]}).",
                            "node_id": node.id,
                        },
                    )
                )
                return True
            else:
                # Section Rejected -> local retry up to 2 times, then blocked
                node.status = "rejected"
                self.save_node(run_id, node)
                critique_msg = rev_out.get("assessment", "Fatal defects identified in section solution.")

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
                            "severity": "warning",
                            "text": f"Section {sp.index} rejected by Wonder local review: {critique_msg}. Triggering local retry...",
                            "node_id": node.id,
                        },
                    )
                )

                if retry_count < max_retries_per_section:
                    await asyncio.sleep(0.1)
                    failed_body = aggregated_solution.get("solution_body", "")
                    return await solve_single_section(
                        idx=idx,
                        retry_count=retry_count + 1,
                        prior_critique=critique_msg,
                        prior_failed_body=failed_body,
                    )
                else:
                    # Retry limit reached -> mark blocked, invalidate dependents (Section 6.1 / 6.6)
                    node.status = "blocked"
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
                    # Downstream dependents become invalidated
                    for downstream_idx, downstream_sp in subproblems.items():
                        if idx in downstream_sp.dependencies:
                            downstream_node = section_nodes[downstream_idx]
                            downstream_node.status = "invalidated"
                            downstream_node.is_invalidated = True
                            downstream_sp.is_invalidated = True
                            self.save_node(run_id, downstream_node)
                            await self.emit_event(
                                Event(
                                    run_id=run_id,
                                    seq=0,
                                    timestamp=time.strftime("%H:%M:%S"),
                                    event_type="node_updated",
                                    payload={"node": downstream_node.model_dump()},
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
                                        "severity": "error",
                                        "text": (
                                            f"[Danus Invalidation] SEC_{idx} exhausted retries and is BLOCKED. "
                                            f"Downstream dependent SEC_{downstream_idx} is marked INVALIDATED."
                                        ),
                                        "node_id": downstream_node.id,
                                    },
                                )
                            )
                    return False

        # Schedule loop through topological DAG
        while len(accepted_indices) < len(subproblems):
            eligible = [
                idx for idx, sp in subproblems.items()
                if idx not in accepted_indices
                and idx not in in_flight_tasks
                and all(dep in accepted_indices for dep in sp.dependencies)
                and not section_nodes[idx].is_invalidated
            ]

            if not eligible and not in_flight_tasks:
                break

            for el in eligible:
                task = asyncio.create_task(solve_single_section(el, 0))
                in_flight_tasks[el] = task

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

    async def _re_review_stale_section(
        self,
        run_id: str,
        idx: int,
        sp: SubproblemSpec,
        node: Node,
        current_body: str,
        upstream_context: str,
        model_falsifier: str,
        knowledge_prefix: str,
    ):
        """Conduct one Wonder re-review for a section marked STALE due to upstream change (Section 6.6)."""
        prompt = (
            f"Section {sp.index}: {sp.title}\n"
            f"Target Claim: {sp.target_claim}\n\n"
            f"Existing Section Body:\n{current_body}\n\n"
            f"An upstream dependency has been updated:\n{upstream_context}\n\n"
            "Audit whether this section remains valid under the updated upstream lemmas. "
            "Return JSON: verdict ('ready', 'conditional', 'rejected'), assessment."
        )
        rev_out, r_in, r_cached, r_out_tok, r_cost = await self.client.call(
            role="section_falsifier",
            prompt=prompt,
            model=model_falsifier,
            stable_prefix=knowledge_prefix,
            reasoning_effort="medium",
            context_hints={"section_index": idx, "is_stale_rereview": True},
        )
        node.tokens_in += r_in
        node.tokens_cached += r_cached
        node.tokens_out += r_out_tok
        node.cost_usd += r_cost

        verdict = rev_out.get("verdict", "ready")
        if verdict in ["ready", "conditional"]:
            node.status = "accepted" if verdict == "ready" else "conditional"
            node.is_stale = False
            sp.is_stale = False
            self.save_node(run_id, node)
            await self.emit_event(
                Event(
                    run_id=run_id,
                    seq=0,
                    timestamp=time.strftime("%H:%M:%S"),
                    event_type="log_line",
                    payload={
                        "stage": "solving",
                        "severity": "info",
                        "text": f"Stale Section {sp.index} successfully re-reviewed and cleared: {verdict}.",
                        "node_id": node.id,
                    },
                )
            )
            await self.emit_event(
                Event(
                    run_id=run_id,
                    seq=0,
                    timestamp=time.strftime("%H:%M:%S"),
                    event_type="node_updated",
                    payload={"node": node.model_dump()},
                )
            )
        else:
            node.status = "rejected"
            node.is_stale = True
            sp.is_stale = True
            self.save_node(run_id, node)
            await self.emit_event(
                Event(
                    run_id=run_id,
                    seq=0,
                    timestamp=time.strftime("%H:%M:%S"),
                    event_type="log_line",
                    payload={
                        "stage": "solving",
                        "severity": "warning",
                        "text": f"Stale Section {sp.index} rejected during re-review. Needs section patch.",
                        "node_id": node.id,
                    },
                )
            )
