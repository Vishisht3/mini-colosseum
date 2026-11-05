"""Budget pools must report the client's true per-provider spend, not node sums."""
import asyncio
from types import SimpleNamespace

from backend.client import ModelClient
from backend import server


def test_budget_pools_reflect_client_accounting():
    client = ModelClient(
        api_key="test-meta", baseten_api_key="test-baseten",
        baseten_fallback_enabled=True, mock_mode=True,
    )

    async def main():
        # Baseten-primary explorer call (falls on Baseten accounting) + Meta falsifier call
        await client.generate(role="explorer", prompt="draft")
        await client.generate(role="falsifier", prompt="check")
        server.active_orchestrator = SimpleNamespace(client=client)
        try:
            return await server.get_budget_pools()
        finally:
            server.active_orchestrator = None

    pools = asyncio.run(main())
    assert pools["meta_usage"] == round(client.cumulative_meta_usd, 4)
    assert pools["baseten_usage"] == round(client.cumulative_baseten_usd, 4)
    assert pools["fireworks_usage"] == round(client.cumulative_fireworks_usd, 4)
    assert pools["total_usage"] == round(client.cumulative_cost_usd, 4)
    assert abs(pools["total_usage"] - (pools["meta_usage"] + pools["baseten_usage"] + pools["fireworks_usage"])) < 0.01
    assert pools["calls"] == client.total_calls
    assert pools["meta"]["spent"] == pools["meta_usage"]
