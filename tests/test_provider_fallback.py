"""Focused tests: optional Baseten/Fireworks keys fall back to Meta."""
import asyncio

from backend.client import ModelClient
from backend import server


def _run(coro):
    return asyncio.run(coro)


def test_fireworks_auth_failure_falls_back_to_meta():
    client = ModelClient(
        api_key="test-meta",
        baseten_api_key="",
        fireworks_api_key="test-fireworks",
        fireworks_fallback_enabled=True,
        mock_mode=True,
    )
    result = _run(client.generate(
        role="explorer", prompt="prove it",
        context_hints={"simulate_fireworks_auth_error": True},
    ))
    output, *_rest, cost = result
    assert result.provider == "meta"
    assert result.fallback_used is True


def test_baseten_auth_failure_falls_back_to_meta():
    client = ModelClient(
        api_key="test-meta",
        baseten_api_key="test-baseten",
        baseten_fallback_enabled=True,
        mock_mode=True,
    )
    result = _run(client.generate(
        role="explorer", prompt="prove it",
        context_hints={"simulate_baseten_auth_error": True},
    ))
    assert result.provider == "meta"
    assert result.fallback_used is True


def test_fireworks_verify_failure_warns_and_falls_back_to_meta(monkeypatch):
    async def fake_meta(key):
        return None

    async def fake_fireworks(key):
        return "Invalid API key (HTTP 401)."

    async def fake_baseten(key):
        return None

    monkeypatch.setattr(server, "verify_meta_key", fake_meta)
    monkeypatch.setattr(server, "verify_fireworks_key", fake_fireworks)
    monkeypatch.setattr(server, "verify_baseten_key", fake_baseten)
    payload = server.KeyVerificationPayload(
        api_key="test-meta", fireworks_api_key="bad-key",
        fireworks_fallback_enabled=True,
    )
    resp = _run(server.verify_keys(payload))
    body = resp.body if hasattr(resp, "body") else None
    if body is not None:
        import json
        data = json.loads(body)
        assert resp.status_code == 200 or "fireworks" in str(data)
    else:
        assert resp["fireworks"]["fallback_to_meta"] is True
        assert resp["warnings"]["fireworks"]


def test_meta_failure_never_falls_back_to_baseten_or_fireworks():
    import pytest
    from backend.client import RetryableProviderError
    client = ModelClient(
        api_key="test-meta",
        baseten_api_key="test-baseten",
        baseten_fallback_enabled=True,
        fireworks_api_key="test-fireworks",
        fireworks_fallback_enabled=True,
        mock_mode=True,
    )
    # Explicit Meta Spark model: Meta is the final provider, no optional fallback.
    route = client.get_route("explorer", model_override="muse-spark-1.3")
    assert route.primary.provider == "meta"
    assert route.fallback is None
    with pytest.raises(RetryableProviderError):
        _run(client.generate(
            role="explorer", prompt="prove it", model_override="muse-spark-1.3",
            context_hints={"simulate_meta_429": True},
        ))


def test_optional_provider_is_primary_and_meta_is_the_only_fallback():
    client = ModelClient(
        api_key="test-meta",
        baseten_api_key="test-baseten",
        baseten_fallback_enabled=True,
        fireworks_api_key="test-fireworks",
        fireworks_fallback_enabled=True,
        mock_mode=True,
    )
    route = client.get_route("explorer")
    assert route.primary.provider in ("baseten", "fireworks")
    assert route.fallback is not None and route.fallback.provider == "meta"


def test_real_meta_call_sends_only_supported_kwargs():
    from types import SimpleNamespace

    seen = {}

    class FakeCompletions:
        async def create(self, **kwargs):
            seen.update(kwargs)
            if "reasoning" in kwargs:
                raise TypeError("Completions.create() got an unexpected keyword argument 'reasoning'")
            msg = SimpleNamespace(content='{"verdict": "survives"}', reasoning_content=None)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=msg)],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None),
            )

    client = ModelClient(api_key="test-meta", mock_mode=False)
    client.meta_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    result = _run(client.generate(role="falsifier", prompt="check this"))
    assert result.provider == "meta"
    assert "reasoning" not in seen
    assert seen.get("reasoning_effort") == "medium"


def test_empty_completion_retries_with_larger_allowance():
    from types import SimpleNamespace

    calls = []

    class FakeCompletions:
        async def create(self, **kwargs):
            calls.append(kwargs.get("max_tokens"))
            if len(calls) == 1:
                msg = SimpleNamespace(content="", reasoning_content=None)
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=msg, finish_reason="length")],
                    usage=SimpleNamespace(prompt_tokens=10, completion_tokens=3000, prompt_tokens_details=None),
                )
            msg = SimpleNamespace(content='{"verdict": "survives"}', reasoning_content=None)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, prompt_tokens_details=None),
            )

    client = ModelClient(api_key="test-meta", mock_mode=False)
    client.meta_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    result = _run(client.generate(role="falsifier", prompt="check this"))
    assert result.output.get("verdict") == "survives"
    assert len(calls) == 2
    assert calls[1] > calls[0]


def test_no_provider_keys_means_meta_is_required():
    client = ModelClient(api_key="test-meta", mock_mode=True)
    route = client.get_route("explorer")
    assert route.primary.provider == "meta"
    assert route.fallback is None
