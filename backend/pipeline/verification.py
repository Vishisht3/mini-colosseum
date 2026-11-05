"""
Stage 5: Global Verification Engine & DeepSeekMath-V2 Exact-Quote Verification.
Implements Section 6.1 and 6.5 of the Mini Colosseum Final Specification:
- Two independent Wonder 1.0 reviewers read the assembled proof document against the problem without shared chat history
- DeepSeekMath-V2 exact-quote rule: each objection must quote the text it attacks (normalized Unicode, whitespace-collapsed, >= 12 chars)
- Verifier critiques lacking a verbatim substring match in the assembled LaTeX source are automatically downgraded to unverified warnings
- Non-voting aggregation: one single concrete fatal defect with a verified exact quote rejects the proof
"""

import asyncio
import re
import time
import unicodedata
from typing import Dict, Any, List, Callable, Awaitable, Tuple
from ..models import Node, Event, VerificationReport, Defect
from ..client import ModelClient


def normalize_for_quote(s: str) -> str:
    """Normalize Unicode (NFKC) and collapse all whitespace to single spaces."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s))
    return re.sub(r"\s+", " ", s).strip()


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
        Runs global verification with two independent reviewers without shared chat history,
        Unicode & whitespace-normalized DeepSeekMath-V2 exact-quote verification, and non-voting aggregation.
        """
        verif_node_id = f"R{round_num}_GLOBAL_VERIF"
        verifier_route = self.client.get_route("global_verifier", model_override=model_verifier)
        verif_node = Node(
            id=verif_node_id,
            type="global_verifier",
            stage="verification",
            round=round_num,
            status="running",
            parents=[f"SEC_{i}" for i in section_bodies.keys()],
            label=f"VERIF_{round_num}",
            model=verifier_route.primary.model,
            provider=verifier_route.primary.provider,
            primary_provider=verifier_route.primary.provider,
            primary_model=verifier_route.primary.model,
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            input_summary=f"Audit complete assembled proof document with 2 independent Wonder 1.0 reviewers and DeepSeekMath-V2 exact-quote validation",
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
                f"You are Independent Global Reviewer {reviewer_idx+1} (Wonder 1.0). Conduct an adversarial audit.\n"
                "Verify whether all claims logically follow, no circular reasoning exists between sections, "
                "and every lemma is correctly applied.\n"
                "DEEPSEEKMATH-V2 EXACT-QUOTE REQUIREMENT: For every defect or objection you cite, you MUST include an 'exact_quote' "
                "containing a verbatim substring (at least 12 characters) directly from the proof text above. "
                "Critiques without verified quotes will be automatically downgraded to unverified warnings.\n"
                "Remember: One single concrete fatal defect with a verified exact quote is sufficient to reject."
            )
            return await self.client.call(
                role="global_verifier",
                prompt=prompt,
                model=model_verifier,
                schema=VerificationReport,
                stable_prefix=knowledge_prefix,
                reasoning_effort="high",
                context_hints={
                    "problem": problem,
                    "node_id": verif_node_id,
                    "round": round_num,
                    "reviewer_idx": reviewer_idx,
                    "assembled_latex": assembled_latex,
                },
            )

        reviewer_tasks = [run_single_reviewer(i) for i in range(num_reviewers)]
        results = await asyncio.gather(*reviewer_tasks)

        all_raw_defects: List[Dict[str, Any]] = []
        total_in = 0
        total_cached = 0
        total_out = 0
        total_cost = 0.0

        for res in results:
            report_dict, t_in, t_cached, t_out, cost = res
            total_in += t_in
            total_cached += t_cached
            total_out += t_out
            total_cost += cost
            for d in report_dict.get("defects", []):
                if d not in all_raw_defects:
                    all_raw_defects.append(d)

        first_result = results[0] if results else None

        verif_node.tokens_in = total_in
        verif_node.tokens_cached = total_cached
        verif_node.tokens_out = total_out
        verif_node.cost_usd = total_cost
        verif_node.provider = getattr(first_result, "provider", verifier_route.primary.provider) if first_result else verifier_route.primary.provider
        verif_node.model = getattr(first_result, "model", model_verifier) if first_result else model_verifier
        verif_node.primary_provider = verifier_route.primary.provider
        verif_node.primary_model = verifier_route.primary.model
        verif_node.fallback_used = bool(getattr(first_result, "fallback_used", False)) if first_result else False
        verif_node.fallback_reason = getattr(first_result, "fallback_reason", None) if first_result else None
        verif_node.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")

        # --- DeepSeekMath-V2: Exact-Quote Substring Verification ---
        norm_doc = normalize_for_quote(assembled_latex)
        verified_defects: List[Defect] = []
        downgraded_warnings: List[Defect] = []
        exact_quotes_checked = 0
        exact_quotes_passed = 0

        for raw_d in all_raw_defects:
            defect = Defect(**raw_d) if isinstance(raw_d, dict) else raw_d
            raw_quote = defect.exact_quote.strip() if defect.exact_quote else ""
            norm_quote = normalize_for_quote(raw_quote)

            if norm_quote:
                exact_quotes_checked += 1
                # Must be at least 12 characters and present in normalized LaTeX source
                if len(norm_quote) >= 12 and norm_quote in norm_doc:
                    defect.quote_verified = True
                    defect.downgraded_warning = False
                    exact_quotes_passed += 1
                    verified_defects.append(defect)
                else:
                    # Hallucinated or truncated quote -> strict downgrade to unverified warning
                    defect.quote_verified = False
                    defect.downgraded_warning = True
                    defect.severity = "unverified_warning"
                    downgraded_warnings.append(defect)
            else:
                defect.quote_verified = False
                defect.downgraded_warning = True
                defect.severity = "unverified_warning"
                downgraded_warnings.append(defect)

        # Non-voting aggregation: only verified fatal defects trigger rejection
        fatal_defects = [d for d in verified_defects if d.severity == "fatal"]
        if fatal_defects:
            final_verdict = "rejected"
            summary = f"Global verification rejected: {len(fatal_defects)} verified fatal defect(s) detected with exact-quote proof."
        elif downgraded_warnings and not verified_defects:
            final_verdict = "accepted"
            summary = (
                f"Global verification accepted: {len(downgraded_warnings)} critique(s) lacked verbatim quote matches in LaTeX source "
                f"and were automatically downgraded to unverified warnings (DeepSeekMath-V2 anti-hallucination guard)."
            )
        elif any(d.severity == "major" for d in verified_defects):
            final_verdict = "conditional"
            summary = f"Global verification conditional: {len(verified_defects)} verified minor/major objections."
        else:
            final_verdict = "accepted"
            summary = "Global verification passed: proof is sound, exact-quote verified, and fully established."

        final_report = VerificationReport(
            verdict=final_verdict,
            defects=verified_defects,
            downgraded_warnings=downgraded_warnings,
            summary=summary,
            exact_quotes_checked=exact_quotes_checked,
            exact_quotes_passed=exact_quotes_passed,
        )

        verif_node.output = final_report.model_dump()
        verif_node.status = "accepted" if final_verdict == "accepted" else ("conditional" if final_verdict == "conditional" else "rejected")

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
                    "severity": "info" if verif_node.status == "accepted" else ("warning" if verif_node.status == "conditional" else "error"),
                    "text": (
                        f"Global Verification {final_report.verdict.upper()} (DeepSeekMath-V2: {exact_quotes_passed}/{exact_quotes_checked} quotes verified, "
                        f"{len(downgraded_warnings)} downgraded): {final_report.summary}"
                    ),
                    "node_id": verif_node.id,
                },
            )
        )

        return verif_node, final_report
