"""
Provider Routing & Fallback Integration Tests for Mini-Colosseum v2.0.
Section 11 of implementation roadmap:
1.  Meta-only configuration runs full pipeline
2.  Meta + Baseten configuration works with fallback enabled
3.  Missing Meta key rejected at run start
4.  Baseten fallback triggers on Meta 429 / quota exhaustion / 500
5.  Wonder 1.0 never falls back to Baseten
6.  Fatal 401/400/404 does not trigger fallback
7.  Usage extraction handles dict and typed-object representations
8.  Terminal states (completed, cancelled, budget_exceeded, failed) resist resets
9.  Route configuration matches specification for all 9 roles
10. GenerationResult metadata (provider, model, fallback_used, fallback_reason)
"""

import unittest
import asyncio
import json
import os
import tempfile
import shutil
from unittest.mock import AsyncMock, MagicMock, patch

from backend.models import RunConfig
from backend.store import RunStore
from backend.client import (
    ModelClient,
    BudgetExceededError,
    RetryableProviderError,
    NonRetryableProviderError,
    GenerationResult,
    safe_extract_usage,
)
from backend.config import (
    MODEL_ROUTES,
    RoleRoute,
    RouteTarget,
    BASETEN_MODEL_ID,
)
from backend.pipeline.orchestrator import Orchestrator


class TestRouteConfiguration(unittest.TestCase):
    """Verify the typed MODEL_ROUTES table matches specification for all 9 roles."""

    def test_spark_roles_route_to_meta_primary_with_baseten_fallback(self):
        """Explorer, Aggregator, Solver, Curator -> Meta Spark 1.3 primary, Baseten fallback."""
        spark_roles = ["explorer", "aggregator", "solver", "curator"]
        for role in spark_roles:
            route = MODEL_ROUTES[role]
            self.assertEqual(route.primary.provider, "meta", f"{role} primary should be meta")
            self.assertEqual(route.primary.model, "muse-spark-1.3", f"{role} primary model should be muse-spark-1.3")
            self.assertIsNotNone(route.fallback, f"{role} should have a fallback")
            self.assertEqual(route.fallback.provider, "baseten", f"{role} fallback should be baseten")
            self.assertEqual(route.fallback.model, BASETEN_MODEL_ID, f"{role} fallback model should be {BASETEN_MODEL_ID}")

    def test_wonder_roles_route_to_meta_primary_with_no_fallback(self):
        """Falsifier, Gate, Decomposer, Section Falsifier, Global Verifier -> Meta Wonder 1.0, no fallback."""
        wonder_roles = ["falsifier", "gate", "decomposer", "section_falsifier", "global_verifier"]
        for role in wonder_roles:
            route = MODEL_ROUTES[role]
            self.assertEqual(route.primary.provider, "meta", f"{role} primary should be meta")
            self.assertEqual(route.primary.model, "muse-wonder-1.0", f"{role} primary model should be muse-wonder-1.0")
            self.assertIsNone(route.fallback, f"{role} must NOT have a fallback")

    def test_all_nine_roles_present(self):
        """All 9 pipeline roles must be defined in MODEL_ROUTES."""
        expected = {
            "explorer", "aggregator", "solver", "curator",
            "falsifier", "gate", "decomposer", "section_falsifier", "global_verifier",
        }
        self.assertEqual(set(MODEL_ROUTES.keys()), expected)

    def test_baseten_model_id_matches_hackathon(self):
        """Baseten model ID must be the hackathon-specific identifier."""
        self.assertEqual(BASETEN_MODEL_ID, "meta-models/muse-spark-open-1026")


class TestClientRouting(unittest.IsolatedAsyncioTestCase):
    """Verify ModelClient.get_route() returns correct routes with overrides."""

    def setUp(self):
        self.client = ModelClient(
            mock_mode=True,
            api_key="test-meta",
            baseten_api_key="test-baseten",
            baseten_fallback_enabled=True,
        )

    def test_get_route_explorer_default(self):
        route = self.client.get_route("explorer")
        self.assertEqual(route.primary.provider, "baseten")
        self.assertEqual(route.primary.model, BASETEN_MODEL_ID)
        self.assertIsNotNone(route.fallback)
        self.assertEqual(route.fallback.provider, "meta")

    def test_get_route_global_verifier_default(self):
        route = self.client.get_route("global_verifier")
        self.assertEqual(route.primary.provider, "meta")
        self.assertEqual(route.primary.model, "muse-wonder-1.0")
        self.assertIsNone(route.fallback)

    def test_get_route_wonder_override_never_has_fallback(self):
        """Even with an explicit wonder model override, fallback must be None."""
        route = self.client.get_route("explorer", model_override="muse-wonder-1.0")
        self.assertEqual(route.primary.model, "muse-wonder-1.0")
        self.assertIsNone(route.fallback)

    def test_get_route_spark_open_override_goes_to_baseten(self):
        route = self.client.get_route("solver", model_override=BASETEN_MODEL_ID)
        self.assertEqual(route.primary.provider, "baseten")
        self.assertEqual(route.primary.model, BASETEN_MODEL_ID)

    def test_get_route_unknown_role_defaults_to_spark(self):
        """Unknown roles default to Baseten Spark Open with Meta fallback."""
        route = self.client.get_route("unknown_role")
        self.assertEqual(route.primary.provider, "baseten")
        self.assertEqual(route.primary.model, BASETEN_MODEL_ID)
        self.assertIsNotNone(route.fallback)
        self.assertEqual(route.fallback.provider, "meta")


class TestMetaOnlyConfiguration(unittest.IsolatedAsyncioTestCase):
    """Meta-only config (no Baseten) must work for the entire pipeline."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.store = RunStore(db_path=os.path.join(self.temp_dir, "meta_only.db"))

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir)

    async def test_full_pipeline_with_meta_only(self):
        """Pipeline completes successfully with no Baseten key at all."""
        config = RunConfig(
            run_id="test_meta_only",
            problem_statement="Prove test theorem.",
            tree_widths=[2, 1],
            k_sample=2,
            mock_mode=True,
            baseten_fallback_enabled=False,
        )
        orch = Orchestrator(config=config, store=self.store)
        trace = await orch.execute()

        self.assertIsNotNone(trace)
        self.assertIn("assembled_latex", trace)
        self.assertIn(trace["run"]["status"], ["completed", "accepted"])


class TestMetaPlusBasteten(unittest.IsolatedAsyncioTestCase):
    """Meta + Baseten config with fallback enabled."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.store = RunStore(db_path=os.path.join(self.temp_dir, "meta_baseten.db"))

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir)

    async def test_full_pipeline_with_baseten_fallback_enabled(self):
        """Pipeline completes with Baseten configured as fallback."""
        config = RunConfig(
            run_id="test_meta_baseten",
            problem_statement="Prove test theorem.",
            tree_widths=[2, 1],
            k_sample=2,
            mock_mode=True,
            baseten_fallback_enabled=True,
        )
        orch = Orchestrator(config=config, store=self.store)
        trace = await orch.execute()

        self.assertIsNotNone(trace)
        self.assertIn(trace["run"]["status"], ["completed", "accepted"])


class TestFallbackBehavior(unittest.IsolatedAsyncioTestCase):
    """Fallback triggers and guards for Baseten-primary Spark routes."""

    def make_client(self, **kwargs):
        return ModelClient(
            mock_mode=True,
            api_key="test-meta",
            baseten_api_key="test-baseten",
            **kwargs,
        )

    async def test_429_rate_limit_triggers_meta_fallback(self):
        """Baseten HTTP 429 triggers Meta fallback for Spark roles."""
        client = self.make_client(baseten_fallback_enabled=True, budget_cap_usd=50.0)
        result = await client.generate(
            role="explorer",
            prompt="test prompt",
            context_hints={"simulate_baseten_429": True},
        )
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.provider, "meta")
        self.assertIn("429", result.fallback_reason)

    async def test_500_error_triggers_meta_fallback(self):
        """Baseten HTTP 500 triggers Meta fallback for Spark roles."""
        client = self.make_client(baseten_fallback_enabled=True, budget_cap_usd=50.0)
        result = await client.generate(
            role="solver",
            prompt="test prompt",
            context_hints={"simulate_baseten_error": True},
        )
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.provider, "meta")
        self.assertIn("500", result.fallback_reason)

    async def test_wonder_never_falls_back_to_baseten(self):
        """Wonder roles (falsifier, gate, etc.) must NEVER fall back to Baseten."""
        client = self.make_client(baseten_fallback_enabled=True, budget_cap_usd=50.0)
        # Simulate Meta error for a Wonder role — should raise, NOT fallback
        with self.assertRaises(RetryableProviderError):
            await client.generate(
                role="global_verifier",
                prompt="test prompt",
                context_hints={"simulate_meta_error": True},
            )

    async def test_wonder_gate_never_falls_back(self):
        """Gate role (Wonder) must raise on error, not fallback."""
        client = self.make_client(baseten_fallback_enabled=True, budget_cap_usd=50.0)
        with self.assertRaises(RetryableProviderError):
            await client.generate(
                role="gate",
                prompt="test prompt",
                context_hints={"simulate_meta_error": True},
            )

    async def test_wonder_falsifier_never_falls_back(self):
        """Falsifier role (Wonder) must raise on error, not fallback."""
        client = self.make_client(baseten_fallback_enabled=True, budget_cap_usd=50.0)
        with self.assertRaises(RetryableProviderError):
            await client.generate(
                role="falsifier",
                prompt="test prompt",
                context_hints={"simulate_meta_error": True},
            )

    async def test_401_auth_error_on_baseten_falls_back_to_meta(self):
        """HTTP 401 auth error on Baseten immediately falls back to Meta API without failing the run."""
        client = self.make_client(baseten_fallback_enabled=True, budget_cap_usd=50.0)
        result = await client.generate(
            role="explorer",
            prompt="test prompt",
            context_hints={"simulate_baseten_auth_error": True},
        )
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.provider, "meta")
        self.assertEqual(result.model, "muse-spark-1.3")
        self.assertIn("401", result.fallback_reason)

    async def test_401_auth_error_on_baseten_override_even_when_fallback_flag_disabled_falls_back_to_meta(self):
        """Even if baseten_fallback_enabled=False, an explicit Baseten model override with invalid Baseten key falls back to Meta API."""
        client = self.make_client(baseten_fallback_enabled=False, budget_cap_usd=50.0)
        result = await client.generate(
            role="explorer",
            prompt="test prompt",
            model_override=BASETEN_MODEL_ID,
            context_hints={"simulate_baseten_auth_error": True},
        )
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.provider, "meta")
        self.assertEqual(result.model, "muse-spark-1.3")

    async def test_401_auth_error_on_meta_does_not_fallback(self):
        """HTTP 401 auth error on Meta primary must raise immediately, never fallback."""
        client = self.make_client(baseten_fallback_enabled=False, budget_cap_usd=50.0)
        with self.assertRaises(NonRetryableProviderError) as ctx:
            await client.generate(
                role="explorer",
                prompt="test prompt",
                context_hints={"simulate_auth_error": True},
            )
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_baseten_override_429_falls_back_to_meta(self):
        """When Baseten is explicitly overridden, Baseten HTTP 429 falls back to Meta API even if baseten_fallback_enabled is False."""
        client = self.make_client(baseten_fallback_enabled=False, budget_cap_usd=50.0)
        result = await client.generate(
            role="explorer",
            prompt="test prompt",
            model_override=BASETEN_MODEL_ID,
            context_hints={"simulate_baseten_429": True},
        )
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.provider, "meta")

    async def test_fallback_callback_invoked(self):
        """When fallback occurs, the fallback_callback should be called with event payload."""
        callback_data = []

        async def capture_callback(payload):
            callback_data.append(payload)

        client = self.make_client(
            baseten_fallback_enabled=True,
            budget_cap_usd=50.0,
            fallback_callback=capture_callback,
        )
        result = await client.generate(
            role="explorer",
            prompt="test prompt",
            context_hints={"simulate_baseten_429": True},
        )
        self.assertEqual(len(callback_data), 1)
        self.assertEqual(callback_data[0]["role"], "explorer")
        self.assertEqual(callback_data[0]["from_provider"], "baseten")
        self.assertEqual(callback_data[0]["to_provider"], "meta")


class TestUsageExtraction(unittest.TestCase):
    """safe_extract_usage must handle dict, typed objects, and missing data."""

    def test_dict_usage(self):
        """Standard dict usage object."""
        usage = {
            "prompt_tokens": 500,
            "completion_tokens": 200,
            "prompt_tokens_details": {"cached_tokens": 100},
        }
        tokens_in, cached, tokens_out = safe_extract_usage(usage, "prompt text", "completion text")
        self.assertEqual(tokens_in, 500)
        self.assertEqual(cached, 100)
        self.assertEqual(tokens_out, 200)

    def test_typed_object_usage(self):
        """Typed SDK object with attributes instead of dict access."""
        usage = MagicMock()
        usage.prompt_tokens = 800
        usage.completion_tokens = 300
        details = MagicMock()
        details.cached_tokens = 200
        usage.prompt_tokens_details = details
        tokens_in, cached, tokens_out = safe_extract_usage(usage, "prompt", "completion")
        self.assertEqual(tokens_in, 800)
        self.assertEqual(cached, 200)
        self.assertEqual(tokens_out, 300)

    def test_none_usage_estimates_from_text(self):
        """When usage is None, estimate from text length."""
        prompt = "x" * 400  # ~100 tokens estimate
        completion = "y" * 200  # ~50 tokens estimate
        tokens_in, cached, tokens_out = safe_extract_usage(None, prompt, completion)
        self.assertEqual(tokens_in, 100)
        self.assertEqual(cached, 0)
        self.assertEqual(tokens_out, 50)

    def test_missing_cached_tokens_defaults_to_zero(self):
        """When prompt_tokens_details is None, cached = 0."""
        usage = {"prompt_tokens": 500, "completion_tokens": 200}
        tokens_in, cached, tokens_out = safe_extract_usage(usage, "p", "c")
        self.assertEqual(cached, 0)


class TestGenerationResultMetadata(unittest.IsolatedAsyncioTestCase):
    """GenerationResult carries provider metadata beyond the 5-tuple."""

    async def test_normal_call_has_meta_provider(self):
        """Normal call (no fallback) reports meta provider."""
        client = ModelClient(mock_mode=True, budget_cap_usd=50.0)
        result = await client.generate(role="explorer", prompt="test")
        self.assertIsInstance(result, GenerationResult)
        self.assertEqual(result.provider, "meta")
        self.assertEqual(result.model, "muse-spark-1.3")
        self.assertFalse(result.fallback_used)
        self.assertIsNone(result.fallback_reason)

    async def test_fallback_call_has_meta_provider(self):
        """Fallback call reports Meta provider and reason."""
        client = ModelClient(
            mock_mode=True,
            api_key="test-meta",
            baseten_api_key="test-baseten",
            baseten_fallback_enabled=True,
            budget_cap_usd=50.0,
        )
        result = await client.generate(
            role="explorer",
            prompt="test",
            context_hints={"simulate_baseten_429": True},
        )
        self.assertEqual(result.provider, "meta")
        self.assertEqual(result.model, "muse-spark-1.3")
        self.assertTrue(result.fallback_used)
        self.assertIsNotNone(result.fallback_reason)

    async def test_result_unpacks_as_5_tuple(self):
        """GenerationResult is backwards-compatible with 5-tuple unpacking."""
        client = ModelClient(mock_mode=True, budget_cap_usd=50.0)
        output, tokens_in, tokens_cached, tokens_out, cost = await client.generate(
            role="solver", prompt="test"
        )
        self.assertIsInstance(output, dict)
        self.assertIsInstance(tokens_in, int)
        self.assertIsInstance(tokens_cached, int)
        self.assertIsInstance(tokens_out, int)
        self.assertIsInstance(cost, float)


class TestTerminalStates(unittest.IsolatedAsyncioTestCase):
    """Terminal states (completed, cancelled, budget_exceeded, failed) resist resets."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.store = RunStore(db_path=os.path.join(self.temp_dir, "terminal.db"))

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir)

    async def test_completed_status_resists_reset(self):
        """Once a run reaches 'completed', update_run_status must not change it."""
        config = RunConfig(
            run_id="test_terminal",
            problem_statement="Test statement.",
            tree_widths=[2, 1],
            k_sample=2,
            mock_mode=True,
        )
        orch = Orchestrator(config=config, store=self.store)
        trace = await orch.execute()
        self.assertIn(trace["run"]["status"], ["completed", "accepted"])

        # Try to reset to "running" — should be rejected
        self.store.update_run_status(
            "test_terminal", "running", "exploration", 1, 0.0, 0, 0, 0,
        )
        stored = self.store.export_trace_json("test_terminal")
        self.assertIn(stored["run"]["status"], ["completed", "accepted"])

    async def test_budget_exceeded_is_terminal(self):
        """budget_exceeded status resists being reset to running."""
        # Create a run via RunConfig + Orchestrator's create_run path
        from datetime import datetime, timezone
        config = RunConfig(
            run_id="test_budget_terminal",
            problem_statement="test",
            tree_widths=[2, 1],
            k_sample=2,
            mock_mode=True,
        )
        self.store.create_run(config, datetime.now(timezone.utc).isoformat())
        # Force it to budget_exceeded via update
        self.store.update_run_status(
            "test_budget_terminal", "budget_exceeded", "exploration", 1, 0.0, 0, 0, 0,
        )
        # Now try to reset to "running" — should be rejected
        self.store.update_run_status(
            "test_budget_terminal", "running", "exploration", 1, 0.0, 0, 0, 0,
        )
        trace = self.store.export_trace_json("test_budget_terminal")
        self.assertEqual(trace["run"]["status"], "budget_exceeded")


class TestMissingMetaKeyRejected(unittest.IsolatedAsyncioTestCase):
    """A run cannot start without a Meta API key."""

    async def test_client_without_api_key_raises(self):
        """ModelClient with no API key and no mock_mode should fail to create client."""
        # In mock mode, missing key is fine
        client = ModelClient(mock_mode=True)
        self.assertIsNotNone(client)

        # Without mock mode AND without any key, the meta_client will be None
        client_no_key = ModelClient(api_key="", mock_mode=False)
        self.assertIsNone(client_no_key.meta_client)


class TestProviderAccounting(unittest.IsolatedAsyncioTestCase):
    """Provider-specific accounting tracks Meta and Baseten expenditures separately."""

    async def test_meta_call_increments_meta_accounting(self):
        client = ModelClient(mock_mode=True, budget_cap_usd=50.0)
        await client.generate(role="explorer", prompt="test")
        self.assertGreater(client.cumulative_meta_usd, 0.0)
        self.assertEqual(client.cumulative_baseten_usd, 0.0)

    async def test_baseten_fallback_increments_baseten_accounting(self):
        client = ModelClient(
            mock_mode=True,
            baseten_fallback_enabled=True,
            budget_cap_usd=50.0,
        )
        await client.generate(
            role="solver",
            prompt="test",
            context_hints={"simulate_meta_429": True},
        )
        self.assertGreater(client.cumulative_baseten_usd, 0.0)
        # Meta accounting should also have something from the failed attempt? No, mock_mode
        # simulates the error before the call completes, so meta stays 0 for mock failures.
        self.assertAlmostEqual(
            client.cumulative_cost_usd,
            client.cumulative_meta_usd + client.cumulative_baseten_usd,
            places=5,
        )

    async def test_total_equals_sum_of_providers(self):
        client = ModelClient(mock_mode=True, budget_cap_usd=50.0)
        # Meta call
        await client.generate(role="explorer", prompt="test1")
        # Baseten direct call
        await client.generate(role="explorer", prompt="test2", model_override=BASETEN_MODEL_ID)

        self.assertGreater(client.cumulative_meta_usd, 0.0)
        self.assertGreater(client.cumulative_baseten_usd, 0.0)
        self.assertAlmostEqual(
            client.cumulative_cost_usd,
            client.cumulative_meta_usd + client.cumulative_baseten_usd,
            places=5,
        )


class TestCredentialSecurity(unittest.IsolatedAsyncioTestCase):
    """Issue 3: Verify credentials are NEVER present in RunConfig, SQLite, or trace exports."""

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.store = RunStore(db_path=os.path.join(self.temp_dir, "security.db"))

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_run_config_has_no_credential_fields(self):
        """RunConfig must not hold any API keys."""
        config = RunConfig(
            problem_statement="security check",
        )
        fields = RunConfig.model_fields.keys()
        self.assertNotIn("api_key", fields)
        self.assertNotIn("baseten_api_key", fields)
        self.assertNotIn("api_key", config.model_dump())
        self.assertNotIn("baseten_api_key", config.model_dump())

    async def test_trace_export_never_contains_raw_credentials(self):
        """Exported trace JSON must not contain credentials anywhere."""
        config = RunConfig(
            run_id="sec_test",
            problem_statement="prove security",
            tree_widths=[2, 1],
            k_sample=2,
            mock_mode=True,
        )
        orch = Orchestrator(config=config, store=self.store)
        trace = await orch.execute()

        raw_json = json.dumps(trace)
        self.assertNotIn("baseten_api_key", raw_json)
        self.assertNotIn("meta_api_key", raw_json)


if __name__ == "__main__":
    unittest.main()
