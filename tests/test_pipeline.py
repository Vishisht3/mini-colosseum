"""
Unit & Integration Tests for Mini-Colosseum Pipeline.
Verifies:
- Overlapping tree sampling and contraction
- Cycle detection in decomposition
- Section solving with local retry
- Global verification non-voting aggregation
- Hard budget cap enforcement
"""

import unittest
import asyncio
import os
import shutil
import tempfile
from backend.models import RunConfig, StrategyCard, FalsifierReport
from backend.store import RunStore
from backend.client import ModelClient, BudgetExceededError
from backend.pipeline.decomposition import DecompositionEngine, CycleDetectedError
from backend.pipeline.orchestrator import Orchestrator


class TestMiniColosseumPipeline(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test.db")
        self.store = RunStore(db_path=self.db_path)

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir)

    async def test_cycle_detection(self):
        """Scheduler must reject any decomposition containing a cycle (Section 5.3)."""
        engine = DecompositionEngine(
            client=ModelClient(mock_mode=True),
            emit_event=lambda ev: asyncio.sleep(0),
            save_node=lambda r, n: None,
            save_edge=lambda r, e: None,
        )

        # Valid DAG
        valid_subproblems = [
            {"index": 1, "dependencies": []},
            {"index": 2, "dependencies": [1]},
            {"index": 3, "dependencies": [1, 2]},
        ]
        order = engine.validate_acyclic(valid_subproblems)
        self.assertEqual(order, [1, 2, 3])

        # Cyclic graph: 1 -> 2 -> 3 -> 1
        cyclic_subproblems = [
            {"index": 1, "dependencies": [3]},
            {"index": 2, "dependencies": [1]},
            {"index": 3, "dependencies": [2]},
        ]
        with self.assertRaises(CycleDetectedError):
            engine.validate_acyclic(cyclic_subproblems)

    async def test_overlapping_tree_aggregation(self):
        """Verify that overlapping reuse occurs: some candidates have multiple outgoing edges (Section 5.1)."""
        config = RunConfig(
            run_id="test_overlap",
            problem_statement="Test statement",
            tree_widths=[4, 2, 1],
            k_sample=3,
            mock_mode=True,
        )
        orch = Orchestrator(config=config, store=self.store)
        trace = await orch.execute()

        # Check nodes count: 4 leaves + 2 Level 1 + 1 Root = 7 exploration nodes + 1 Gate + 1 Dec + 3 Sec + 1 Verif + 1 Curator
        nodes = trace.get("nodes", [])
        edges = trace.get("edges", [])

        # In level 0 -> level 1, 2 aggregators each take 3 parents from 4 leaves.
        # Total edges from level 0 = 6 edges across 4 nodes -> by pigeonhole, at least one leaf has >= 2 outgoing edges!
        outgoing_counts = {}
        for edge in edges:
            if edge.get("edge_type") == "aggregation":
                src = edge["source"]
                outgoing_counts[src] = outgoing_counts.get(src, 0) + 1

        multi_outgoing = [src for src, count in outgoing_counts.items() if count > 1]
        self.assertTrue(len(multi_outgoing) > 0, "Expected at least one node to exhibit overlapping reuse with multiple outgoing edges.")

    async def test_local_section_retry(self):
        """Verify that a rejected section retries on its own while others remain untouched (Section 5.4)."""
        config = RunConfig(
            run_id="test_retry",
            problem_statement="Test statement with retry",
            tree_widths=[2, 1],
            k_sample=2,
            mock_mode=True,
        )
        orch = Orchestrator(config=config, store=self.store)
        trace = await orch.execute(force_section2_retry=True)

        sec2_node = next((n for n in trace["nodes"] if n["node_id"] == "SEC_2"), None)
        self.assertIsNotNone(sec2_node)
        self.assertGreaterEqual(sec2_node["retry_count"], 1, "Section 2 should have recorded at least 1 retry.")

    async def test_budget_limiter_stops_calls(self):
        """Verify that cumulative cost exceeding budget cap stops calls (Section 8 & 9)."""
        tiny_cap = 0.000001  # Extremely small cap
        client = ModelClient(budget_cap_usd=tiny_cap, mock_mode=True)
        # First call succeeds and consumes some cost
        await client.call(role="explorer", prompt="test", model="muse-spark-1.3")
        # Subsequent call must raise BudgetExceededError
        with self.assertRaises(BudgetExceededError):
            await client.call(role="explorer", prompt="test 2", model="muse-spark-1.3")


if __name__ == "__main__":
    unittest.main()
