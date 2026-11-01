"""
Stage 5: Global Verification Engine.
Based on Section 5.5 of Mini-Colosseum Specification v1.0.
- Multiple independent reviewers read the assembled proof document
- Non-voting aggregation: one single concrete fatal defect is sufficient to reject!
- Defects are precisely localized to section or claim, naming both supporting and using sections for cross-section defects.
"""

import asyncio
import time
from typing import Dict, Any, List, Callable, Awaitable, Tuple
from ..models import Node, Event, VerificationReport, Defect
from ..client import ModelClient


class GlobalVerificationEngine:
    def __init__(
        self,
        client: ModelClient,
        emit_event: Callable[[Event], Awaitable[None]],
        save_node: Callable[[Node], None],
    ):
        self.client = client
        self.emit_event = emit_event
        self.save_node = save_node

    async def verify(
        self,
        run_id: str,
        problem: str,
        assembled_latex: str,
        section_bodies: Dict[int, str],
        round_num: int = 1,
        knowledge_prefix: str = "",
        model_verifier: str = "muse-wonder-1.0",
        num_reviewers: int = 2,
    ) -> Tuple[Node, VerificationReport]:
        """
        Runs global verification with independent reviewers and non-voting aggregation.
        """
        verif_node_id = f"R{round_num}_GLOBAL_VERIF"
        verif_node = Node(
            id=verif_node_id,
            type="global_verifier",
            stage="verification",
            round=round_num,
            status="running",
            parents=[f"SEC_{i}" for i in section_bodies.keys()],
            label=f"VERIF_{round_num}",
            model=model_verifier,
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            input_summary="Audit complete assembled proof document across all sections",
        )
        self.save_node(run_id, verif_node)

        await self.emit_event(
            Event(
                run_id=run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="stage_changed",
                payload={"stage": "verification", "round": round_num},
            )
        )
        await self.emit_event(
            Event(
                run_id=run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="node_created",
                payload={"node": verif_node.model_dump()},
            )
        )

        async def run_single_reviewer(reviewer_idx: int) -> Tuple[Dict[str, Any], int, int, int, float]:
            prompt = (
                f"Problem to Prove: {problem}\n\n"
                f"Complete Assembled Proof Document:\n{assembled_latex}\n\n"
                f"You are Independent Global Reviewer {reviewer_idx+1}. Conduct an adversarial, holistic audit.\n"
                "Verify whether all claims logically follow, no circular reasoning exists between sections, "
                "and every lemma is correctly applied.\n"
                "Remember: It is NOT a majority vote. One concrete fatal defect is enough to reject."
            )
            return await self.client.call(
                role="global_verifier",
                prompt=prompt,
                model=model_verifier,
                schema=VerificationReport,
                stable_prefix=knowledge_prefix,
                reasoning_effort="high",
                context_hints={"problem": problem, "node_id": verif_node_id, "round": round_num},
            )

        reviewer_tasks = [run_single_reviewer(i) for i in range(num_reviewers)]
        results = await asyncio.gather(*reviewer_tasks)

        all_defects: List[Dict[str, Any]] = []
        total_in = 0
        total_cached = 0
        total_out = 0
        total_cost = 0.0
        final_verdict = "accepted"

        for report_dict, t_in, t_cached, t_out, cost in results:
            total_in += t_in
            total_cached += t_cached
            total_out += t_out
            total_cost += cost
            defects = report_dict.get("defects", [])
            for d in defects:
                if d not in all_defects:
                    all_defects.append(d)
                if d.get("severity") == "fatal":
                    final_verdict = "rejected"
            if report_dict.get("verdict") == "rejected":
                final_verdict = "rejected"

        verif_node.tokens_in = total_in
        verif_node.tokens_cached = total_cached
        verif_node.tokens_out = total_out
        verif_node.cost_usd = total_cost
        verif_node.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")

        final_report = VerificationReport(
            verdict="rejected" if final_verdict == "rejected" else "accepted",
            defects=[Defect(**d) for d in all_defects],
            summary="Global verification passed: proof is sound and fully established." if final_verdict == "accepted" else "Global verification rejected: fatal defect identified.",
        )

        verif_node.output = final_report.model_dump()
        verif_node.status = "accepted" if final_report.verdict == "accepted" else "rejected"

        self.save_node(run_id, verif_node)
        await self.emit_event(
            Event(
                run_id=run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="node_updated",
                payload={"node": verif_node.model_dump()},
            )
        )
        await self.emit_event(
            Event(
                run_id=run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="log_line",
                payload={
                    "stage": "verification",
                    "severity": "info" if verif_node.status == "accepted" else "error",
                    "text": f"Global Verification {final_report.verdict.upper()}: {final_report.summary}",
                    "node_id": verif_node.id,
                },
            )
        )

        return verif_node, final_report
