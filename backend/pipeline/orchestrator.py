"""
Pipeline Orchestrator & Deterministic State Machine for Mini-Colosseum v2.0.
Implements the 5-Stage Orchestration Pipeline per Section 6.1 of Mini Colosseum Specification:
1. Strategy Exploration (Stellar Colosseum tree aggregation, ASearcher analysis, up to 15-20 rounds)
2. Readiness Gate (Reject routes back to Stage 1, obligations assigned to sections)
3. Proof Decomposition (Up to 15 sections, cycle detection with 1 repair attempt, Danus fingerprints)
4. Subproblem Solving ((K, 1) section trees with per-candidate falsifiers, local review, local retry, stale re-review)
5. Global Verification & Section-Targeted Revision:
   - 2 independent Wonder reviewers + non-voting defect aggregator + exact-quote check.
   - If defects found: runs up to 2 targeted revision cycles patching only affected sections.
   - Stale dependents undergo Wonder re-review.
   - If revisions fail or re-explore requested: triggers re-exploration (up to max_rounds) with rejected draft + feedback.
"""

import time
import asyncio
from typing import Dict, Any, List, Optional, Callable, Awaitable
from ..models import (
    RunConfig,
    Node,
    Edge,
    Event,
    KnowledgeEntry,
    VerificationReport,
    SectionSolution,
)
from ..store import RunStore
from ..client import ModelClient, BudgetExceededError
from .exploration import ExplorationEngine
from .gate import ReadinessGateEngine
from .decomposition import DecompositionEngine
from .solving import SectionSolvingEngine
from .verification import GlobalVerificationEngine
from .curator import CuratorEngine
from .latex_utils import sanitize_latex_body, assemble_latex_document


class ReexploreSignal(Exception):
    """Raised when re-exploration is triggered either manually or via gate/verification."""
    pass


class Orchestrator:
    def __init__(
        self,
        config: RunConfig,
        store: RunStore,
        client: Optional[ModelClient] = None,
        event_callback: Optional[Callable[[Event], Awaitable[None]]] = None,
    ):
        self.config = config
        self.store = store
        self.run_id = config.run_id
        self.client = client or ModelClient(
            budget_cap_usd=config.budget_cap_usd,
            mock_mode=config.mock_mode,
        )
        self.event_callback = event_callback
        self.seq = 0

        # Control states
        self.is_paused = False
        self.is_stopped = False
        self.step_event = asyncio.Event()
        self.step_mode = False
        self.reexplore_requested = False

        # Engines
        self.exploration_engine = ExplorationEngine(
            self.client, self.emit_event, self._save_node, self._save_edge
        )
        self.gate_engine = ReadinessGateEngine(
            self.client, self.emit_event, self._save_node
        )
        self.decomposition_engine = DecompositionEngine(
            self.client, self.emit_event, self._save_node, self._save_edge
        )
        self.solving_engine = SectionSolvingEngine(
            self.client,
            self.emit_event,
            self._save_node,
            self._save_edge,
            save_hmed=self.store.save_hmed_record,
        )
        self.verification_engine = GlobalVerificationEngine(
            self.client, self.emit_event, self._save_node
        )
        self.curator_engine = CuratorEngine(
            self.client, self.emit_event, self._save_node, self._add_knowledge
        )

        self.knowledge_entries: List[KnowledgeEntry] = []
        self.assembled_latex = ""
        self._is_finalized = False
        self.current_round = 1
        self.max_rounds = max(1, min(int(getattr(config, "max_rounds", 15) or 15), 20))

        # Hook fallback callback to emit provider_fallback events
        async def _on_provider_fallback(payload: Dict[str, Any]):
            await self.emit_event(
                Event(
                    run_id=self.run_id,
                    seq=0,
                    timestamp=time.strftime("%H:%M:%S"),
                    event_type="provider_fallback",
                    payload=payload,
                )
            )
        self.client.fallback_callback = _on_provider_fallback

    def _save_node(self, run_id: str, node: Node):
        self.store.save_node(run_id, node)

    def _save_edge(self, run_id: str, edge: Edge):
        self.store.save_edge(run_id, edge)

    def _add_knowledge(self, run_id: str, entry: KnowledgeEntry):
        self.knowledge_entries.append(entry)
        self.store.add_knowledge(run_id, entry)

    async def emit_event(self, event: Event):
        self.seq += 1
        event.seq = self.seq
        event.run_id = self.run_id
        if not event.timestamp:
            event.timestamp = time.strftime("%H:%M:%S")

        self.store.save_event(event)

        current_status = "running"
        if event.event_type == "run_finished":
            current_status = event.payload.get("status", "completed")

        # Prevent accidental status resets: never overwrite terminal state with 'running'
        if not self._is_finalized or event.event_type == "run_finished":
            self.store.update_run_status(
                run_id=self.run_id,
                status=current_status,
                stage=event.payload.get("stage", "exploration"),
                round_num=event.payload.get("round", getattr(self, "current_round", 1)),
                cost_usd=self.client.cumulative_cost_usd,
                tokens_in=self.client.total_tokens_in,
                tokens_cached=self.client.total_tokens_cached,
                tokens_out=self.client.total_tokens_out,
                assembled_latex=self.assembled_latex,
                cost_meta_usd=self.client.cumulative_meta_usd,
                cost_baseten_usd=self.client.cumulative_baseten_usd,
                tokens_meta_in=self.client.total_meta_tokens_in,
                tokens_meta_out=self.client.total_meta_tokens_out,
                tokens_baseten_in=self.client.total_baseten_tokens_in,
                tokens_baseten_out=self.client.total_baseten_tokens_out,
            )

        if self.event_callback:
            try:
                await self.event_callback(event)
            except Exception:
                pass

    async def _finalize_run(self, final_status: str, error_message: Optional[str] = None):
        """Unified finalization mechanism ensuring correct terminal state and accounting (Section 7.B)."""
        if self._is_finalized:
            return
        self._is_finalized = True
        if final_status in ("cancelled", "failed", "budget_exceeded", "unresolved"):
            self.store.reset_running_nodes(self.run_id)
        finish_time = time.strftime("%Y-%m-%d %H:%M:%S")

        self.store.update_run_status(
            run_id=self.run_id,
            status=final_status,
            stage="verification",
            round_num=min(getattr(self, "current_round", 1), getattr(self, "max_rounds", 15)),
            cost_usd=self.client.cumulative_cost_usd,
            tokens_in=self.client.total_tokens_in,
            tokens_cached=self.client.total_tokens_cached,
            tokens_out=self.client.total_tokens_out,
            finished_at=finish_time,
            assembled_latex=self.assembled_latex,
            cost_meta_usd=self.client.cumulative_meta_usd,
            cost_baseten_usd=self.client.cumulative_baseten_usd,
            tokens_meta_in=self.client.total_meta_tokens_in,
            tokens_meta_out=self.client.total_meta_tokens_out,
            tokens_baseten_in=self.client.total_baseten_tokens_in,
            tokens_baseten_out=self.client.total_baseten_tokens_out,
        )

        payload = {
            "run_id": self.run_id,
            "status": final_status,
            "cost_usd": self.client.cumulative_cost_usd,
            "cost_meta_usd": self.client.cumulative_meta_usd,
            "cost_baseten_usd": self.client.cumulative_baseten_usd,
            "tokens_total": self.client.total_tokens_in + self.client.total_tokens_out,
            "assembled_latex": self.assembled_latex,
        }
        if error_message:
            payload["error"] = error_message

        await self.emit_event(
            Event(
                run_id=self.run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="run_finished",
                payload=payload,
            )
        )

    async def check_pause_and_step(self):
        """Handle pause, step-by-stage execution, and manual re-explore check."""
        if self.is_stopped:
            raise asyncio.CancelledError("Run stopped by user.")
        if self.reexplore_requested:
            self.reexplore_requested = False
            raise ReexploreSignal("Manual re-exploration requested by user.")
        if self.is_paused or self.step_mode:
            await self.step_event.wait()
            self.step_event.clear()

    def pause(self):
        self.is_paused = True

    def resume(self):
        self.is_paused = False
        self.step_mode = False
        self.step_event.set()

    def step(self):
        self.step_mode = True
        self.step_event.set()

    def stop(self):
        self.is_stopped = True
        self.step_event.set()

    def trigger_reexplore(self):
        """Signal orchestrator to trigger a re-exploration round (FR14)."""
        self.reexplore_requested = True
        self.step_event.set()

    def format_knowledge_prefix(self) -> str:
        """
        Anti-Persistence Raw Memory Format (Section 6.7, arXiv:2610.27406):
        - Literature references dropped.
        - Unrefuted entries + failed approaches/objections injected into stable prefix across rounds.
        - Retains up to 30 most recent entries to sustain long-horizon (15-round) exploration.
        """
        lines = []

        # 1. Unrefuted raw provenance claims
        prov_entries = self.store.get_raw_provenance(self.run_id)
        unfalsified_prov = [p for p in prov_entries if p.get("falsifier_verdict") in ("survives", "needs_repair")]
        for p in unfalsified_prov[-10:]:
            lines.append(f"• [Claim {p.get('claim_id')}] (Node: {p.get('source_node')}): {p.get('target_statement')}")

        # 2. Unrefuted knowledge entries (failed approaches, observations, lemmas)
        active_ke = [ke for ke in self.knowledge_entries if getattr(ke, "status", "") != "refuted"]
        for ke in active_ke[-25:]:
            lines.append(f"• [{ke.entry_type.upper()}] {ke.title}: {ke.contents}")

        capped_lines = lines[-30:]
        if not capped_lines:
            return ""
        return "=== ACCUMULATED KNOWLEDGE DIRECTORY (ANTI-PERSISTENCE) ===\n" + "\n".join(capped_lines)

    @staticmethod
    def _identify_affected_sections(verif_report: VerificationReport, section_bodies: Dict[int, str]) -> List[int]:
        """Resolve which sections need revision from Defect.section_index, supporting/using_section, or exact_quote."""
        affected = set()
        for d in verif_report.defects:
            sec_idx = getattr(d, "section_index", None)
            if sec_idx is not None and sec_idx in section_bodies:
                affected.add(sec_idx)
                continue
            for alt_field in ("using_section", "supporting_section"):
                alt_idx = getattr(d, alt_field, None)
                if alt_idx is not None and alt_idx in section_bodies:
                    affected.add(alt_idx)
            quote = getattr(d, "exact_quote", "") or ""
            if quote and len(quote.strip()) >= 8:
                q_norm = " ".join(quote.split())
                for idx, body in section_bodies.items():
                    if q_norm in " ".join(body.split()):
                        affected.add(idx)
        return sorted(affected)

    async def execute(
        self,
        force_section2_retry: bool = False,
        seed_plan=None,
        seed_bodies=None,
        resume_existing: bool = False,
    ) -> Dict[str, Any]:
        """
        Main execution loop through all 5 stages, supporting:
        - Readiness gate routing back to exploration on reject (up to max_rounds)
        - Section-targeted revision (max 2 cycles) patching affected sections
        - Stale dependent re-review
        - Re-exploration rounds (up to 15-20 rounds) with accumulated knowledge + rejected feedback
        """
        start_time = time.strftime("%Y-%m-%d %H:%M:%S")
        seed_pending = seed_plan is not None
        if resume_existing:
            # Continuation of a saved run: keep its row, cost ledger, and event sequence.
            self.store.reopen_run(self.run_id)
            self.seq = self.store.get_max_event_seq(self.run_id)
            self._is_finalized = False
        else:
            self.store.create_run(self.config, start_time)

        current_round = 1
        max_rounds = max(1, min(int(getattr(self.config, "max_rounds", 15) or 15), 20))
        strategy_root: Optional[Node] = None
        prior_failed_feedback = ""
        final_run_status = "unresolved"

        try:
            while current_round <= max_rounds and not self.is_stopped:
                self.current_round = current_round
                self.max_rounds = max_rounds
                try:
                    await self.emit_event(
                        Event(
                            run_id=self.run_id,
                            seq=0,
                            timestamp=time.strftime("%H:%M:%S"),
                            event_type="round_started",
                            payload={"round": current_round},
                        )
                    )

                    plan = seed_plan if seed_pending else None
                    seeded_bodies = seed_bodies if seed_pending else None
                    if seed_pending:
                        seed_pending = False
                        await self.emit_event(
                            Event(
                                run_id=self.run_id,
                                seq=0,
                                timestamp=time.strftime("%H:%M:%S"),
                                event_type="log_line",
                                payload={
                                    "stage": "solving",
                                    "severity": "info",
                                    "text": f"Continuation: reusing {len(seed_bodies or {})} saved section bodies; solving {len(seed_plan.subproblems) - len(seed_bodies or {})} remaining sections.",
                                },
                            )
                        )
                    if plan is None:
                        # STAGE 1: Strategy Exploration
                        await self.check_pause_and_step()
                        knowledge_prefix = self.format_knowledge_prefix()
                        model_exp = self.config.models_per_role.get("explorer", "muse-spark-1.3")
                        model_fal = (
                            "muse-wonder-1.0"
                            if self.config.cross_model_review
                            else self.config.models_per_role.get("falsifier", "muse-spark-1.3")
                        )
                        model_agg = self.config.models_per_role.get("aggregator", "muse-spark-1.3")

                        strategy_root = await self.exploration_engine.run_exploration(
                            run_id=self.run_id,
                            problem=self.config.problem_statement,
                            widths=self.config.tree_widths,
                            k=self.config.k_sample,
                            round_num=current_round,
                            knowledge_prefix=knowledge_prefix,
                            model_explorer=model_exp,
                            model_falsifier=model_fal,
                            model_aggregator=model_agg,
                            prior_context=prior_failed_feedback,
                        )

                        # Record raw provenance for the round's root strategy claim
                        f_rep = strategy_root.falsifier_report or {}
                        primary_route_str = str((strategy_root.output or {}).get("primary_route") or "")[:300]
                        if primary_route_str:
                            self.store.add_raw_provenance(
                                self.run_id,
                                {
                                    "claim_id": f"R{current_round}_ROOT",
                                    "source_node": strategy_root.id,
                                    "target_statement": primary_route_str,
                                    "falsifier_verdict": f_rep.get("verdict", "survives"),
                                    "failure_point": (strategy_root.output or {}).get("first_hard_obstruction"),
                                    "tested_boundary_cases": f_rep.get("boundary_cases", []),
                                },
                            )

                        # STAGE 2: Readiness Gate (Wonder 1.0)
                        await self.check_pause_and_step()
                        gate_node, gate_verdict = await self.gate_engine.evaluate(
                            run_id=self.run_id,
                            problem=self.config.problem_statement,
                            root_node=strategy_root,
                            round_num=current_round,
                            knowledge_prefix=self.format_knowledge_prefix(),
                            model_gate=self.config.models_per_role.get("gate", "muse-wonder-1.0"),
                        )

                        # Curate knowledge from exploration + Gate audit
                        await self.curator_engine.curate(
                            run_id=self.run_id,
                            problem=self.config.problem_statement,
                            strategy_node=strategy_root,
                            round_num=current_round,
                            model_curator=self.config.models_per_role.get("curator", "muse-spark-1.3"),
                            falsifier_node=gate_node if gate_verdict in ["needs further exploration", "reject"] else None,
                        )

                        # Reject discards the route and returns to exploration (up to max_rounds)
                        if gate_verdict in ["needs further exploration", "reject"]:
                            gate_rationale = (
                                gate_node.output.get("rationale")
                                or gate_node.output.get("explanation")
                                or ""
                            )
                            blocking = gate_node.output.get("blocking_issues") or []
                            blocking_str = f" Blocking issues: {'; '.join(str(b) for b in blocking)}" if blocking else ""
                            prior_failed_feedback = (
                                f"Round {current_round} gate rejection ({gate_verdict}): {gate_rationale}.{blocking_str}"
                            )
                            await self.emit_event(
                                Event(
                                    run_id=self.run_id,
                                    seq=0,
                                    timestamp=time.strftime("%H:%M:%S"),
                                    event_type="log_line",
                                    payload={
                                        "stage": "gate",
                                        "severity": "warning",
                                        "text": f"Gate rejected strategy route ({gate_verdict}). Carrying findings forward to exploration Round {current_round+1}/{max_rounds}...",
                                    },
                                )
                            )
                            current_round += 1
                            continue

                        # STAGE 3: Decomposition (Wonder 1.0, up to max_sections)
                        await self.check_pause_and_step()
                        dec_node, plan = await self.decomposition_engine.decompose(
                            run_id=self.run_id,
                            problem=self.config.problem_statement,
                            strategy_root=strategy_root,
                            round_num=current_round,
                            knowledge_prefix=self.format_knowledge_prefix(),
                            model_decomposer=self.config.models_per_role.get("decomposer", "muse-wonder-1.0"),
                            max_sections=getattr(self.config, "max_sections", 15),
                            gate_obligations=gate_node.output.get("obligations", []),
                        )

                    # STAGE 4: Subproblem Solving ((K,1) Trees + Local Review)
                    await self.check_pause_and_step()
                    model_solv = self.config.models_per_role.get("solver", "muse-spark-1.3")
                    model_sec_fal = (
                        "muse-wonder-1.0"
                        if self.config.cross_model_review
                        else self.config.models_per_role.get("section_falsifier", "muse-spark-1.3")
                    )

                    section_bodies, assembled_latex = await self.solving_engine.solve_plan(
                        run_id=self.run_id,
                        problem=self.config.problem_statement,
                        plan=plan,
                        round_num=current_round,
                        knowledge_prefix=self.format_knowledge_prefix(),
                        model_solver=model_solv,
                        model_falsifier=model_sec_fal,
                        force_section2_retry=force_section2_retry,
                        existing_bodies=seeded_bodies,
                        k_rollouts=getattr(self.config, "k_rollouts", 4),
                    )
                    self.assembled_latex = assembled_latex

                    # STAGE 5: Global Verification (Two Wonder Reviewers + Exact-Quote Check)
                    await self.check_pause_and_step()
                    verif_node, verif_report = await self.verification_engine.verify(
                        run_id=self.run_id,
                        problem=self.config.problem_statement,
                        assembled_latex=self.assembled_latex,
                        section_bodies=section_bodies,
                        round_num=current_round,
                        knowledge_prefix=self.format_knowledge_prefix(),
                        model_verifier=self.config.models_per_role.get("global_verifier", "muse-wonder-1.0"),
                    )

                    if verif_report.verdict == "accepted":
                        final_run_status = "accepted"
                        break

                    # Conditional with no fatal defect is accepted-with-obligations
                    if verif_report.verdict == "conditional" and not any(
                        getattr(d, "severity", "") == "fatal" for d in verif_report.defects
                    ):
                        await self.emit_event(
                            Event(
                                run_id=self.run_id,
                                seq=0,
                                timestamp=time.strftime("%H:%M:%S"),
                                event_type="log_line",
                                payload={
                                    "stage": "verification",
                                    "severity": "info",
                                    "text": "Global verification conditional with no fatal defects: accepting draft with obligations recorded.",
                                },
                            )
                        )
                        final_run_status = "accepted"
                        break

                    # --- TARGETED SECTION REVISION (Section 6.1: at most 2 cycles) ---
                    max_revision_cycles = 2
                    rev_cycle = 0
                    revision_accepted = False
                    subproblems_by_idx = {sp.index: sp for sp in plan.subproblems}

                    affected_sections = self._identify_affected_sections(verif_report, section_bodies)

                    if affected_sections:
                        while rev_cycle < max_revision_cycles and not revision_accepted and not self.is_stopped:
                            rev_cycle += 1
                            await self.emit_event(
                                Event(
                                    run_id=self.run_id,
                                    seq=0,
                                    timestamp=time.strftime("%H:%M:%S"),
                                    event_type="log_line",
                                    payload={
                                        "stage": "revision",
                                        "severity": "warning",
                                        "text": f"Starting Revision Cycle {rev_cycle}/{max_revision_cycles}: Patching affected sections {affected_sections}...",
                                    },
                                )
                            )

                            for sec_idx in affected_sections:
                                sec_defects = [
                                    d for d in verif_report.defects
                                    if getattr(d, "section_index", None) == sec_idx
                                    or getattr(d, "using_section", None) == sec_idx
                                    or getattr(d, "supporting_section", None) == sec_idx
                                ]
                                if not sec_defects:
                                    sec_defects = list(verif_report.defects)
                                defect_text = "\n".join(
                                    [
                                        f"- {d.severity.upper()}: {d.description} (Quote: '{getattr(d, 'exact_quote', '')}')"
                                        for d in sec_defects
                                    ]
                                )
                                sp_title = subproblems_by_idx[sec_idx].title if sec_idx in subproblems_by_idx else f"Section {sec_idx}"

                                rev_prompt = (
                                    f"Problem: {self.config.problem_statement}\n\n"
                                    f"Section {sec_idx} ({sp_title}) Proof to Revise:\n{section_bodies[sec_idx]}\n\n"
                                    f"Verifier Defects to Resolve:\n{defect_text}\n\n"
                                    "Revise this section to eliminate all defects and ensure complete deductive rigor. "
                                    "Use formal LaTeX environments (\\begin{lemma}, \\begin{theorem}, \\begin{proof}) and do NOT include a leading \\section{...} heading. "
                                    "Return JSON with: status ('solved'), solution_body, claimed_result."
                                )
                                rev_out, _, _, _, _ = await self.client.call(
                                    role="solver",
                                    prompt=rev_prompt,
                                    model=model_solv,
                                    schema=SectionSolution,
                                    stable_prefix=self.format_knowledge_prefix(),
                                    reasoning_effort="high",
                                    context_hints={"section_index": sec_idx, "is_revision": True},
                                )
                                revised_body = rev_out.get("solution_body") or rev_out.get("latex_body")
                                if revised_body:
                                    section_bodies[sec_idx] = sanitize_latex_body(revised_body, section_title=sp_title)
                                    await self.emit_event(
                                        Event(
                                            run_id=self.run_id,
                                            seq=0,
                                            timestamp=time.strftime("%H:%M:%S"),
                                            event_type="revision_applied",
                                            payload={
                                                "section_index": sec_idx,
                                                "cycle": rev_cycle,
                                                "defects_addressed": len(sec_defects),
                                            },
                                        )
                                    )

                            # Reassemble LaTeX document cleanly with patched sections
                            self.assembled_latex = assemble_latex_document(plan, section_bodies)

                            # Re-verify with Global Verification
                            verif_node, verif_report = await self.verification_engine.verify(
                                run_id=self.run_id,
                                problem=self.config.problem_statement,
                                assembled_latex=self.assembled_latex,
                                section_bodies=section_bodies,
                                round_num=current_round,
                                knowledge_prefix=self.format_knowledge_prefix(),
                                model_verifier=self.config.models_per_role.get("global_verifier", "muse-wonder-1.0"),
                            )

                            if verif_report.verdict == "accepted" or (
                                verif_report.verdict == "conditional"
                                and not any(getattr(d, "severity", "") == "fatal" for d in verif_report.defects)
                            ):
                                revision_accepted = True
                                final_run_status = "accepted"
                                break
                            else:
                                affected_sections = self._identify_affected_sections(verif_report, section_bodies)

                    if revision_accepted or verif_report.verdict == "accepted":
                        final_run_status = "accepted"
                        break

                    # Record global verification defects into knowledge directory before next round
                    for d in verif_report.defects[:5]:
                        self._add_knowledge(
                            self.run_id,
                            KnowledgeEntry(
                                entry_type="failed_approaches",
                                title=f"Global Defect in Round {current_round} (Sec {getattr(d, 'section_index', '?')})",
                                contents=f"{d.severity}: {d.description}",
                                source=verif_node.id,
                                caveats="Must be repaired in next exploration round.",
                            ),
                        )

                    # Re-exploration fallback with rejected draft and feedback (Section 6.1)
                    prior_failed_feedback = (
                        f"Round {current_round} rejected draft with open defects: {verif_report.summary}. "
                        f"Prior draft excerpt: {self.assembled_latex[:400]}..."
                    )
                    await self.emit_event(
                        Event(
                            run_id=self.run_id,
                            seq=0,
                            timestamp=time.strftime("%H:%M:%S"),
                            event_type="reexplore_started",
                            payload={
                                "round": current_round + 1,
                                "reason": f"Global verification rejected draft: {verif_report.summary}",
                            },
                        )
                    )
                    current_round += 1

                except ReexploreSignal as e:
                    # User triggered manual re-explore
                    await self.emit_event(
                        Event(
                            run_id=self.run_id,
                            seq=0,
                            timestamp=time.strftime("%H:%M:%S"),
                            event_type="reexplore_started",
                            payload={"round": current_round + 1, "reason": str(e)},
                        )
                    )
                    prior_failed_feedback = f"Manual re-exploration requested. Prior assembled proof:\n{self.assembled_latex[:400]}..."
                    current_round += 1
                    continue

            # Run Finished (Section 7.B)
            resolved_status = "completed" if final_run_status in ["accepted", "completed"] else final_run_status
            await self._finalize_run(final_status=resolved_status)

        except BudgetExceededError as e:
            await self.emit_event(
                Event(
                    run_id=self.run_id,
                    seq=0,
                    timestamp=time.strftime("%H:%M:%S"),
                    event_type="budget_warning",
                    payload={"message": str(e), "cost_usd": self.client.cumulative_cost_usd},
                )
            )
            await self.emit_event(
                Event(
                    run_id=self.run_id,
                    seq=0,
                    timestamp=time.strftime("%H:%M:%S"),
                    event_type="log_line",
                    payload={"stage": "all", "severity": "error", "text": f"BUDGET CAP REACHED: {e}"},
                )
            )
            await self._finalize_run(final_status="budget_exceeded", error_message=str(e))
        except asyncio.CancelledError:
            await self.emit_event(
                Event(
                    run_id=self.run_id,
                    seq=0,
                    timestamp=time.strftime("%H:%M:%S"),
                    event_type="log_line",
                    payload={"stage": "all", "severity": "warning", "text": "Run stopped by user."},
                )
            )
            await self._finalize_run(final_status="cancelled", error_message="Run stopped by user.")
        except Exception as e:
            await self.emit_event(
                Event(
                    run_id=self.run_id,
                    seq=0,
                    timestamp=time.strftime("%H:%M:%S"),
                    event_type="error",
                    payload={"error": str(e)},
                )
            )
            await self.emit_event(
                Event(
                    run_id=self.run_id,
                    seq=0,
                    timestamp=time.strftime("%H:%M:%S"),
                    event_type="log_line",
                    payload={"stage": "all", "severity": "error", "text": f"Execution error: {e}"},
                )
            )
            await self._finalize_run(final_status="failed", error_message=str(e))
            raise

        return self.store.export_trace_json(self.run_id)
