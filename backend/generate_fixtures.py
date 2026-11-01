"""
Script to generate the three required benchmark fixture runs:
1. fixture_clean_success.json (clean 5-stage success)
2. fixture_section_retry.json (demonstrates Section 2 rejection and local retry)
3. fixture_re_exploration.json (demonstrates Gate rejection in Round 1 and successful Round 2)
"""

import asyncio
import os
import json
from backend.models import RunConfig
from backend.store import RunStore
from backend.client import ModelClient
from backend.pipeline.orchestrator import Orchestrator

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


async def generate_fixtures():
    os.makedirs(FIXTURES_DIR, exist_ok=True)
    temp_db = os.path.join(FIXTURES_DIR, "temp_gen.db")
    if os.path.exists(temp_db):
        os.remove(temp_db)

    store = RunStore(db_path=temp_db)

    # 1. Clean Success
    print("Generating fixture 1: Clean Success...")
    cfg1 = RunConfig(
        run_id="run_clean_success",
        problem_statement="Prove that every sequence of n^2 + 1 distinct real numbers contains a monotonic subsequence of length n + 1.",
        size_preset="Small",
        tree_widths=[4, 2, 1],
        k_sample=3,
        budget_cap_usd=20.0,
        max_rounds=1,
        mock_mode=True,
    )
    orch1 = Orchestrator(config=cfg1, store=store)
    trace1 = await orch1.execute(force_section2_retry=False)
    with open(os.path.join(FIXTURES_DIR, "fixture_clean_success.json"), "w") as f:
        json.dump(trace1, f, indent=2)

    # 2. Section Retry
    print("Generating fixture 2: Section Retry...")
    cfg2 = RunConfig(
        run_id="run_section_retry",
        problem_statement="Prove that in any 2-coloring of the edges of a complete graph K_6 with colors Red and Blue, there exists at least one monochromatic triangle.",
        size_preset="Small",
        tree_widths=[4, 2, 1],
        k_sample=3,
        budget_cap_usd=20.0,
        max_rounds=1,
        mock_mode=True,
    )
    orch2 = Orchestrator(config=cfg2, store=store)
    trace2 = await orch2.execute(force_section2_retry=True)
    with open(os.path.join(FIXTURES_DIR, "fixture_section_retry.json"), "w") as f:
        json.dump(trace2, f, indent=2)

    # 3. Re-exploration (2 rounds)
    print("Generating fixture 3: Re-exploration...")
    cfg3 = RunConfig(
        run_id="run_re_exploration",
        problem_statement="Prove that every planar graph G with n vertices and girth at least 5 has an independent set of size at least n / 3.",
        size_preset="Small",
        tree_widths=[4, 2, 1],
        k_sample=3,
        budget_cap_usd=20.0,
        max_rounds=2,
        mock_mode=True,
    )
    orch3 = Orchestrator(config=cfg3, store=store)
    # Simulate a gate rejection in round 1 by monkey-patching gate evaluate once
    orig_gate = orch3.gate_engine.evaluate
    gate_call_count = 0

    async def patched_gate(*args, **kwargs):
        nonlocal gate_call_count
        gate_call_count += 1
        node, verdict = await orig_gate(*args, **kwargs)
        if gate_call_count == 1:
            node.output["verdict"] = "needs further exploration"
            node.output["explanation"] = "Round 1 candidate relied on unverified edge density bound for planar graphs of girth 5 without explicit Euler characteristic derivation."
            node.status = "rejected"
            store.save_node(orch3.run_id, node)
            return node, "needs further exploration"
        return node, verdict

    orch3.gate_engine.evaluate = patched_gate
    trace3 = await orch3.execute(force_section2_retry=False)
    with open(os.path.join(FIXTURES_DIR, "fixture_re_exploration.json"), "w") as f:
        json.dump(trace3, f, indent=2)

    print("Fixtures successfully created in backend/fixtures/!")


if __name__ == "__main__":
    asyncio.run(generate_fixtures())
