"""
Pipeline Orchestrator for Mini-Colosseum.
Coordinates stages 1-5, revision and re-exploration loops, DAG scheduling,
pause/step/resume controls, and live event emissions.
"""

import asyncio
import time
from typing import Dict, Any, List, Optional, Callable, Awaitable
from ..models import (
    Node, Edge, Event, RunConfig, KnowledgeEntry,
    SectionPlan, VerificationReport
)
from ..client import ModelClient, BudgetExceededError
from ..store import RunStore
from .exploration import ExplorationEngine
from .gate import ReadinessGateEngine
from .decomposition import DecompositionEngine
from .solving import SectionSolvingEngine
from .verification import GlobalVerificationEngine
from .curator import CuratorEngine


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

        # Determine status: if run_finished, use finished status
        current_status = "running"
        if event.event_type == "run_finished":
            current_status = event.payload.get("status", "accepted")

        # Update run stats in DB
        self.store.update_run_status(
            run_id=self.run_id,
            status=current_status,
            stage=event.payload.get("stage", "exploration"),
            round_num=event.payload.get("round", 1),
            cost_usd=self.client.cumulative_cost_usd,
            tokens_in=self.client.total_tokens_in,
            tokens_cached=self.client.total_tokens_cached,
            tokens_out=self.client.total_tokens_out,
            assembled_latex=self.assembled_latex,
        )

        if self.event_callback:
            try:
                await self.event_callback(event)
            except Exception:
                pass

    async def check_pause_and_step(self):
        """Handle pause and step-by-stage execution."""
        if self.is_stopped:
            raise asyncio.CancelledError("Run stopped by user.")
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

    def format_knowledge_prefix(self) -> str:
        """
        Anti-Persistence Raw Memory Format (v1.1, arXiv:2610.27406).
        Replaces hallucinated narrative memory summaries with raw, unfalsified claim provenance.
        Only claims verified and not rejected by falsifiers are injected into stable prefix.
        """
        prov_entries = self.store.get_raw_provenance(self.run_id)
        unfalsified = [p for p in prov_entries if p.get("falsifier_verdict") == "survives"]
        if not unfalsified:
            if not self.knowledge_entries:
                return ""
            lines = ["=== VERIFIED LEMMA INVARIANTS ==="]
            for ke in self.knowledge_entries:
                lines.append(f"• [{ke.entry_type.upper()}] {ke.title}: {ke.contents} (Source: {ke.source})")
            return "\n".join(lines)

        lines = ["=== ANTI-PERSISTENCE VERIFIED PROVENANCE CACHE ==="]
        for p in unfalsified:
            lines.append(f"• [Claim {p.get('claim_id')}] (Node: {p.get('source_node')}): {p.get('target_statement')}")
        return "\n".join(lines)

    async def execute(self, force_section2_retry: bool = False) -> Dict[str, Any]:
        """
        Main execution loop through all 5 stages, supporting re-exploration rounds.
        """
        start_time = time.strftime("%Y-%m-%d %H:%M:%S")
        self.store.create_run(self.config, start_time)

        current_round = 1
        max_rounds = self.config.max_rounds
        strategy_root: Optional[Node] = None
        prior_failed_feedback = ""

        try:
            while current_round <= max_rounds and not self.is_stopped:
                await self.emit_event(
                    Event(
                        run_id=self.run_id,
                        seq=0,
                        timestamp=time.strftime("%H:%M:%S"),
                        event_type="round_started",
                        payload={"round": current_round},
                    )
                )

                # STAGE 1: Strategy Exploration
                await self.check_pause_and_step()
                knowledge_prefix = self.format_knowledge_prefix()
                model_exp = self.config.models_per_role.get("explorer", "muse-spark-1.3")
                model_fal = "muse-wonder-1.0" if self.config.cross_model_review else self.config.models_per_role.get("falsifier", "muse-spark-1.3")
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

                # Curate knowledge from exploration
                await self.curator_engine.curate(
                    run_id=self.run_id,
                    problem=self.config.problem_statement,
                    strategy_node=strategy_root,
                    round_num=current_round,
                    model_curator=self.config.models_per_role.get("curator", "muse-spark-1.3"),
                )

                # STAGE 2: Readiness Gate
                await self.check_pause_and_step()
                gate_node, gate_verdict = await self.gate_engine.evaluate(
                    run_id=self.run_id,
                    problem=self.config.problem_statement,
                    root_node=strategy_root,
                    round_num=current_round,
                    knowledge_prefix=self.format_knowledge_prefix(),
                    model_gate=self.config.models_per_role.get("gate", "muse-wonder-1.0"),
                )

                if gate_verdict in ["needs further exploration", "reject"]:
                    prior_failed_feedback = (
                        f"Round {current_round} gate rejection: {gate_node.output.get('explanation', '')}"
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
                                "text": f"Gate rejected strategy ({gate_verdict}). Triggering re-exploration round {current_round+1}...",
                            },
                        )
                    )
                    current_round += 1
                    continue

                # STAGE 3: Decomposition
                await self.check_pause_and_step()
                dec_node, plan = await self.decomposition_engine.decompose(
                    run_id=self.run_id,
                    problem=self.config.problem_statement,
                    strategy_root=strategy_root,
                    round_num=current_round,
                    knowledge_prefix=self.format_knowledge_prefix(),
                    model_decomposer=self.config.models_per_role.get("decomposer", "muse-wonder-1.0"),
                )

                # STAGE 4: Subproblem Solving (Proof DAG)
                await self.check_pause_and_step()
                model_solv = self.config.models_per_role.get("solver", "muse-spark-1.3")
                model_sec_fal = "muse-wonder-1.0" if self.config.cross_model_review else self.config.models_per_role.get("section_falsifier", "muse-spark-1.3")

                section_bodies, assembled_latex = await self.solving_engine.solve_plan(
                    run_id=self.run_id,
                    problem=self.config.problem_statement,
                    plan=plan,
                    round_num=current_round,
                    knowledge_prefix=self.format_knowledge_prefix(),
                    model_solver=model_solv,
                    model_falsifier=model_sec_fal,
                    force_section2_retry=force_section2_retry,
                )
                self.assembled_latex = assembled_latex

                # STAGE 5: Global Verification
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
                    # Finished with full verified proof!
                    break
                else:
                    prior_failed_feedback = f"Round {current_round} verification defects: {verif_report.summary}"
                    current_round += 1

            # Run Finished
            finish_time = time.strftime("%Y-%m-%d %H:%M:%S")
            self.store.update_run_status(
                run_id=self.run_id,
                status="accepted" if strategy_root and strategy_root.status == "accepted" else "completed",
                stage="verification",
                round_num=min(current_round, max_rounds),
                cost_usd=self.client.cumulative_cost_usd,
                tokens_in=self.client.total_tokens_in,
                tokens_cached=self.client.total_tokens_cached,
                tokens_out=self.client.total_tokens_out,
                finished_at=finish_time,
                assembled_latex=self.assembled_latex,
            )

            await self.emit_event(
                Event(
                    run_id=self.run_id,
                    seq=0,
                    timestamp=time.strftime("%H:%M:%S"),
                    event_type="run_finished",
                    payload={
                        "run_id": self.run_id,
                        "status": "accepted",
                        "cost_usd": self.client.cumulative_cost_usd,
                        "tokens_total": self.client.total_tokens_in + self.client.total_tokens_out,
                        "assembled_latex": self.assembled_latex,
                    },
                )
            )

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
            raise

        return self.store.export_trace_json(self.run_id)
