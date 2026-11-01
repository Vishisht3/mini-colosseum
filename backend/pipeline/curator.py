"""
Stage 5.7: Knowledge Directory Curator Engine.
Based on Section 5.7 of Mini-Colosseum Specification v1.0.
Curates:
- Theorems and lemmas
- Failed approaches
- References
- Observations
The directory is placed in the stable prefix of later prompts to leverage prompt caching.
"""

import time
from typing import Dict, Any, List, Callable, Awaitable
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
        model_curator: str = "muse-spark-1.3",
    ) -> List[KnowledgeEntry]:
        """
        Extract reusable mathematical knowledge from the round's artifacts.
        """
        curator_node_id = f"R{round_num}_CURATOR"
        node = Node(
            id=curator_node_id,
            type="curator",
            stage="curator",
            round=round_num,
            status="running",
            parents=[strategy_node.id],
            label=f"CURATOR_{round_num}",
            model=model_curator,
            started_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            input_summary="Extract reusable theorems, failed approaches, references, and observations",
        )
        self.save_node(run_id, node)

        prompt = (
            f"Problem: {problem}\n\n"
            f"Strategy Card:\n{strategy_node.output}\n\n"
            f"Falsifier Critique:\n{strategy_node.falsifier_report}\n\n"
            "Extract 4 categories of reusable mathematical entries:\n"
            "1. theorems_and_lemmas\n2. failed_approaches\n3. references\n4. observations\n"
            "Include title, contents, source, and caveats for each."
        )

        out, t_in, t_cached, t_out, cost = await self.client.call(
            role="curator",
            prompt=prompt,
            model=model_curator,
            schema=None,
            reasoning_effort="low",
            context_hints={"problem": problem, "node_id": curator_node_id, "round": round_num},
        )

        node.output = out
        node.tokens_in = t_in
        node.tokens_cached = t_cached
        node.tokens_out = t_out
        node.cost_usd = cost
        node.status = "accepted"
        node.finished_at = time.strftime("%Y-%m-%d %H:%M:%S")

        self.save_node(run_id, node)

        entries: List[KnowledgeEntry] = []
        for cat in ["theorems_and_lemmas", "failed_approaches", "references", "observations"]:
            for item in out.get(cat, []):
                ke = KnowledgeEntry(
                    entry_type=cat,  # type: ignore
                    title=item.get("title", ""),
                    contents=item.get("contents", ""),
                    source=item.get("source", f"Round {round_num}"),
                    caveats=item.get("caveats", ""),
                )
                self.add_knowledge(run_id, ke)
                entries.append(ke)

        await self.emit_event(
            Event(
                run_id=run_id,
                seq=0,
                timestamp=time.strftime("%H:%M:%S"),
                event_type="log_line",
                payload={
                    "stage": "curator",
                    "severity": "info",
                    "text": f"Knowledge directory updated: {len(entries)} entries recorded.",
                    "node_id": node.id,
                },
            )
        )

        return entries
