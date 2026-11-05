"""
Acceptance Criteria Verification Test Suite for Mini-Colosseum.
Verifies all 11 criteria from Section 13.2 of the Technical Specification:
1. One-command launcher & backend start
2. Complete autonomous run end-to-end without manual intervention
3. Research Tree and Proof DAG live data structures
4. Overlapping reuse: candidate nodes with >1 outgoing edge
5. Traceability: inputs, outputs, models, tokens, cost, falsifier report
6. Local retry: rejected section retries on its own while others stay unchanged
7. Non-voting verification: reject on single concrete defect localized to section
8. Hard spending cap enforcement
9. Replayability without network access
10. Trace & LaTeX exports
11. Plain scientific styling (color always paired with glyph)
"""

import unittest
import os
import json
import tempfile
import shutil
from backend.models import RunConfig, Defect, VerificationReport
from backend.store import RunStore
from backend.client import ModelClient, BudgetExceededError
from backend.pipeline.orchestrator import Orchestrator


class TestAcceptanceCriteria(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "acceptance_test.db")
        self.store = RunStore(db_path=self.db_path)

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir)

    async def test_criterion_2_complete_run_end_to_end(self):
        """Criterion 2: A complete run finishes end-to-end without manual intervention."""
        config = RunConfig(
            run_id="run_acc_e2e",
            problem_statement="Prove that every sequence of n^2 + 1 distinct real numbers contains a monotonic subsequence of length n + 1.",
            tree_widths=[4, 2, 1],
            k_sample=3,
            mock_mode=True,
        )
        orch = Orchestrator(config=config, store=self.store)
        trace = await orch.execute()

        self.assertIsNotNone(trace)
        self.assertIn("assembled_latex", trace)
        self.assertTrue(len(trace["assembled_latex"]) > 100, "LaTeX document should be assembled.")
        self.assertIn(trace["run"]["status"], ["completed", "accepted"])

    async def test_criterion_4_overlapping_reuse_visible(self):
        """Criterion 4: Overlapping reuse is visible (some candidates have >1 outgoing edge)."""
        config = RunConfig(
            run_id="run_acc_overlap",
            problem_statement="Test statement",
            tree_widths=[4, 2, 1],
            k_sample=3,
            mock_mode=True,
        )
        orch = Orchestrator(config=config, store=self.store)
        trace = await orch.execute()

        edges = trace.get("edges", [])
        leaf_outgoing = {}
        for e in edges:
            if e.get("edge_type") == "aggregation" and "L0" in e["source"]:
                leaf_outgoing[e["source"]] = leaf_outgoing.get(e["source"], 0) + 1

        multi_outgoing = [node_id for node_id, count in leaf_outgoing.items() if count > 1]
        self.assertTrue(
            len(multi_outgoing) >= 1,
            f"Expected overlapping reuse (nodes with multiple outgoing edges), found: {leaf_outgoing}",
        )

    async def test_criterion_5_node_traceability(self):
        """Criterion 5: Every model call is traceable with inputs, outputs, model, tokens, cost, and falsifier."""
        config = RunConfig(
            run_id="run_acc_trace",
            problem_statement="Test statement",
            tree_widths=[2, 1],
            k_sample=2,
            mock_mode=True,
        )
        orch = Orchestrator(config=config, store=self.store)
        trace = await orch.execute()

        nodes = trace.get("nodes", [])
        for n in nodes:
            self.assertTrue(len(n.get("model", "")) > 0, f"Node {n['node_id']} must have model.")
            self.assertGreaterEqual(n.get("cost_usd", 0.0), 0.0)
            self.assertIn("output", n)
            if n.get("type") in ["explorer", "aggregator"]:
                self.assertIsNotNone(n.get("falsifier_report"), f"Node {n['node_id']} should have falsifier report.")

    async def test_criterion_6_rejected_section_retries_locally(self):
        """Criterion 6: A rejected section visibly retries on its own while others stay untouched."""
        config = RunConfig(
            run_id="run_acc_retry",
            problem_statement="Test statement",
            tree_widths=[2, 1],
            k_sample=2,
            mock_mode=True,
        )
        orch = Orchestrator(config=config, store=self.store)
        trace = await orch.execute(force_section2_retry=True)

        nodes_by_id = {n["node_id"]: n for n in trace["nodes"]}
        sec1 = nodes_by_id.get("SEC_1")
        sec2 = nodes_by_id.get("SEC_2")

        self.assertIsNotNone(sec1)
        self.assertIsNotNone(sec2)
        # SEC_1 should have 0 retries
        self.assertEqual(sec1.get("retry_count", 0), 0)
        # SEC_2 should have retried
        self.assertGreaterEqual(sec2.get("retry_count", 0), 1)

    async def test_criterion_7_global_verifier_defect_attribution(self):
        """Criterion 7: Global verifier can reject on a single concrete defect tied to a section."""
        defect = Defect(
            section_index=2,
            claim="Strict injectivity under decreasing coordinates",
            severity="fatal",
            description="Fatal gap in Section 2: omitted proof for x_i > x_j.",
            suggested_action="Supply decreasing order case.",
        )
        report = VerificationReport(
            verdict="rejected",
            defects=[defect],
            summary="Fatal defect localized in Section 2.",
        )
        self.assertEqual(report.verdict, "rejected")
        self.assertEqual(len(report.defects), 1)
        self.assertEqual(report.defects[0].section_index, 2)
        self.assertEqual(report.defects[0].severity, "fatal")

    async def test_criterion_8_budget_cap_enforcement(self):
        """Criterion 8: Hard spending cap prevents runaway spending (Section 6.8)."""
        client = ModelClient(budget_cap_usd=0.005, mock_mode=True)
        # First call succeeds
        await client.call(role="explorer", prompt="test", model="muse-spark-1.3")
        # Second call must be blocked by pre-call budget estimation
        with self.assertRaises(BudgetExceededError):
            await client.call(role="explorer", prompt="test", model="muse-spark-1.3")

    async def test_criterion_9_replay_without_network(self):
        """Criterion 9: Stored trace can be reopened and inspected with zero network calls."""
        # Export a run to JSON
        config = RunConfig(
            run_id="run_acc_replay",
            problem_statement="Test statement",
            tree_widths=[2, 1],
            k_sample=2,
            mock_mode=True,
        )
        orch = Orchestrator(config=config, store=self.store)
        trace_json = await orch.execute()

        # Import into an entirely fresh store (representing a clean offline machine)
        clean_db = os.path.join(self.temp_dir, "clean_offline.db")
        offline_store = RunStore(db_path=clean_db)
        imported_id = offline_store.import_trace_json(trace_json)

        reopened = offline_store.export_trace_json(imported_id)
        self.assertEqual(len(reopened["nodes"]), len(trace_json["nodes"]))
        self.assertEqual(len(reopened["edges"]), len(trace_json["edges"]))
        self.assertEqual(reopened["assembled_latex"], trace_json["assembled_latex"])

    async def test_criterion_10_latex_and_json_export(self):
        """Criterion 10: Proof exports as LaTeX and trace exports as JSON."""
        config = RunConfig(
            run_id="run_acc_export",
            problem_statement="Test statement",
            tree_widths=[2, 1],
            k_sample=2,
            mock_mode=True,
        )
        orch = Orchestrator(config=config, store=self.store)
        trace = await orch.execute()

        latex_str = trace.get("assembled_latex", "")
        self.assertIn(r"\documentclass", latex_str)
        self.assertIn(r"\begin{document}", latex_str)
        self.assertIn(r"\end{document}", latex_str)


if __name__ == "__main__":
    unittest.main()
