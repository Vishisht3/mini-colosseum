"""
Model Client for Mini-Colosseum v2.0
Handles:
- Primary Provider: Meta Model API (muse-spark-1.3, muse-wonder-1.0)
- Fallback Provider: Baseten (meta-models/muse-spark-open-1026) for eligible Spark roles
- Strict fallback policy:
  - 429 rate limit / quota exhaustion -> retry, then fallback
  - 500-599 server errors -> retry, then fallback
  - Network / timeout failures -> retry, then fallback
  - 401 auth / 403 / invalid key on non-Meta primary (e.g. Baseten) -> immediate fallback to Meta API without retries
  - 400 bad request / 404 model not found on non-Meta primary -> fallback to Meta API if available
  - Wonder 1.0 never falls back to Baseten
- Accurate provider-specific accounting (Meta expenditure vs Baseten expenditure)
- Atomic in-flight budget reservations
- Robust token extraction and structured JSON validation
"""

import json
import time
import asyncio
import random
import logging
from typing import Dict, Any, Optional, Tuple, Type, Callable, Awaitable, List
from pydantic import BaseModel
from .config import (
    PRICING_TABLE,
    RATE_LIMITS,
    META_API_BASE_URL,
    META_API_KEY,
    BASETEN_API_BASE_URL,
    BASETEN_API_KEY,
    BASETEN_MODEL_ID,
    DEFAULT_RUN_BUDGET_CAP,
    DEFAULT_META_BUDGET_CAP,
    DEFAULT_BASETEN_BUDGET_CAP,
    MODEL_ROUTES,
    RoleRoute,
    RouteTarget,
    get_model_pricing,
    ROLE_OUTPUT_TOKEN_CAPS,
)

logger = logging.getLogger("mini_colosseum.client")


class BudgetExceededError(Exception):
    """Raised when the cumulative spend or reservation exceeds a configured cap."""
    pass


class RetryableProviderError(Exception):
    """Exception indicating that an API call failed with a retryable or fallback-eligible error."""
    def __init__(self, message: str, status_code: Optional[int] = None, is_quota: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.is_quota = is_quota


class NonRetryableProviderError(Exception):
    """Exception indicating that an API call failed with a fatal, non-fallback error (401, 400, 404)."""
    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class GenerationResult(tuple):
    """
    5-tuple subclass returning (output, tokens_in, tokens_cached, tokens_out, cost)
    while also exposing metadata attributes: provider, model, fallback_used, fallback_reason.
    """
    def __new__(
        cls,
        output: Dict[str, Any],
        tokens_in: int,
        tokens_cached: int,
        tokens_out: int,
        cost: float,
        provider: str = "meta",
        model: str = "",
        fallback_used: bool = False,
        fallback_reason: Optional[str] = None,
    ):
        instance = super().__new__(cls, (output, tokens_in, tokens_cached, tokens_out, cost))
        instance.output = output
        instance.tokens_in = tokens_in
        instance.tokens_cached = tokens_cached
        instance.tokens_out = tokens_out
        instance.cost = cost
        instance.provider = provider
        instance.model = model
        instance.fallback_used = fallback_used
        instance.fallback_reason = fallback_reason
        return instance


def safe_extract_usage(usage: Any, prompt_text: str, completion_text: str) -> Tuple[int, int, int]:
    """Safely extract prompt, cached, and completion tokens from dict or typed SDK object."""
    if usage is None:
        return max(1, len(prompt_text) // 4), 0, max(1, len(completion_text) // 4)

    tokens_in = getattr(usage, "prompt_tokens", None)
    if tokens_in is None and isinstance(usage, dict):
        tokens_in = usage.get("prompt_tokens")
    if tokens_in is None:
        tokens_in = max(1, len(prompt_text) // 4)

    tokens_out = getattr(usage, "completion_tokens", None)
    if tokens_out is None and isinstance(usage, dict):
        tokens_out = usage.get("completion_tokens")
    if tokens_out is None:
        tokens_out = max(1, len(completion_text) // 4)

    tokens_cached = 0
    prompt_details = getattr(usage, "prompt_tokens_details", None)
    if prompt_details is None and isinstance(usage, dict):
        prompt_details = usage.get("prompt_tokens_details")
    if isinstance(prompt_details, dict):
        tokens_cached = prompt_details.get("cached_tokens", 0) or 0
    elif prompt_details is not None:
        tokens_cached = getattr(prompt_details, "cached_tokens", 0) or 0

    return int(tokens_in), int(tokens_cached), int(tokens_out)


class ModelClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        baseten_api_key: Optional[str] = None,
        baseten_base_url: Optional[str] = None,
        baseten_fallback_enabled: bool = False,
        budget_cap_usd: float = DEFAULT_RUN_BUDGET_CAP,
        budget_cap_meta_usd: float = DEFAULT_META_BUDGET_CAP,
        budget_cap_baseten_usd: float = DEFAULT_BASETEN_BUDGET_CAP,
        mock_mode: bool = False,
        fallback_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        **kwargs,  # Accept unused legacy parameters safely
    ):
        self.api_key = api_key or META_API_KEY
        self.base_url = base_url or META_API_BASE_URL
        self.baseten_api_key = baseten_api_key or BASETEN_API_KEY
        self.baseten_base_url = baseten_base_url or BASETEN_API_BASE_URL
        self.baseten_fallback_enabled = baseten_fallback_enabled

        self.budget_cap_usd = budget_cap_usd
        self.budget_cap_meta_usd = budget_cap_meta_usd
        self.budget_cap_baseten_usd = budget_cap_baseten_usd

        self.mock_mode = mock_mode
        self.fallback_callback = fallback_callback

        # Aggregate accounting
        self.cumulative_cost_usd = 0.0
        self.total_tokens_in = 0
        self.total_tokens_cached = 0
        self.total_tokens_out = 0
        self.total_calls = 0

        # Provider-specific accounting (Meta API vs Baseten)
        self.cumulative_meta_usd = 0.0
        self.cumulative_baseten_usd = 0.0
        self.total_meta_tokens_in = 0
        self.total_meta_tokens_cached = 0
        self.total_meta_tokens_out = 0
        self.total_baseten_tokens_in = 0
        self.total_baseten_tokens_cached = 0
        self.total_baseten_tokens_out = 0

        # Concurrency-safe in-flight budget reservations
        self.reserved_cost_usd = 0.0
        self.reserved_meta_usd = 0.0
        self.reserved_baseten_usd = 0.0
        self.warned_80_percent = False

        self._lock = None

        # Two independent clients
        self.meta_client = None
        self.baseten_client = None

        if not self.mock_mode:
            try:
                from openai import AsyncOpenAI
                if self.api_key:
                    self.meta_client = AsyncOpenAI(
                        api_key=self.api_key,
                        base_url=self.base_url,
                    )
                if self.baseten_api_key:
                    self.baseten_client = AsyncOpenAI(
                        api_key=self.baseten_api_key,
                        base_url=self.baseten_base_url,
                    )
            except Exception as e:
                raise RuntimeError(f"Failed to initialize OpenAI client(s): {e}") from e

    @property
    def lock(self) -> asyncio.Lock:
        """Lazy event-loop safe lock."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if self._lock is None or (loop and getattr(self._lock, "_loop", None) not in (loop, None)):
            self._lock = asyncio.Lock()
        return self._lock

    def get_route(self, role: str, model_override: Optional[str] = None) -> RoleRoute:
        """Get typed route configuration for role or explicit model override."""
        base_route = MODEL_ROUTES.get(role)
        if base_route is None:
            # Default to Meta spark with baseten fallback if unknown drafting role
            base_route = RoleRoute(
                primary=RouteTarget(provider="meta", model="muse-spark-1.3"),
                fallback=RouteTarget(provider="baseten", model=BASETEN_MODEL_ID),
            )

        if not model_override:
            if (
                base_route.fallback is not None
                and base_route.fallback.provider == "baseten"
                and self.baseten_fallback_enabled
                and self.baseten_api_key
            ):
                return RoleRoute(
                    primary=base_route.fallback,
                    fallback=RouteTarget(provider="meta", model=base_route.primary.model)
                    if self._provider_available("meta")
                    else None,
                )
            return RoleRoute(
                primary=base_route.primary,
                fallback=base_route.fallback
                if (
                    self.baseten_fallback_enabled
                    and base_route.fallback is not None
                    and self._provider_available(base_route.fallback.provider)
                )
                else None,
            )

        # Handle explicit model override while preserving Wonder constraint
        if "wonder" in model_override:
            return RoleRoute(
                primary=RouteTarget(provider="meta", model=model_override),
                fallback=None,
            )
        if "spark-open" in model_override or model_override == BASETEN_MODEL_ID or model_override.startswith("meta-models/"):
            return RoleRoute(
                primary=RouteTarget(provider="baseten", model=BASETEN_MODEL_ID if model_override == "spark-open" else model_override),
                fallback=RouteTarget(provider="meta", model=base_route.primary.model if "spark" in base_route.primary.model else "muse-spark-1.3")
                if self._provider_available("meta")
                else None,
            )
        if "spark" in model_override:
            return RoleRoute(
                primary=RouteTarget(provider="meta", model=model_override),
                fallback=RouteTarget(provider="baseten", model=BASETEN_MODEL_ID)
                if (self.baseten_fallback_enabled and self._provider_available("baseten"))
                else None,
            )

        # Fallback generic: if primary is non-Meta, fallback to Meta API if available
        primary_prov = self.get_provider(model_override)
        return RoleRoute(
            primary=RouteTarget(provider=primary_prov, model=model_override),
            fallback=RouteTarget(provider="meta", model=base_route.primary.model)
            if (primary_prov != "meta" and self._provider_available("meta"))
            else None,
        )

    def get_provider(self, model: str) -> str:
        """Determine routing provider: 'baseten' for Spark Open, 'meta' for Spark 1.3 / Wonder."""
        if "spark-open" in model or model == BASETEN_MODEL_ID or model.startswith("meta-models/"):
            return "baseten"
        return "meta"

    def _provider_available(self, provider: str) -> bool:
        if self.mock_mode:
            return True
        return (self.meta_client if provider == "meta" else self.baseten_client) is not None

    def _provider_budget(self, provider: str) -> tuple[float, float]:
        if provider == "baseten":
            return self.cumulative_baseten_usd, self.reserved_baseten_usd
        return self.cumulative_meta_usd, self.reserved_meta_usd

    def _reserve_provider_budget(self, provider: str, amount: float) -> None:
        if provider == "baseten":
            self.reserved_baseten_usd += amount
        else:
            self.reserved_meta_usd += amount

    def _release_provider_budget(self, provider: str, amount: float) -> None:
        if provider == "baseten":
            self.reserved_baseten_usd = max(0.0, self.reserved_baseten_usd - amount)
        else:
            self.reserved_meta_usd = max(0.0, self.reserved_meta_usd - amount)

    def compute_cost(
        self,
        model: str,
        tokens_in: int,
        tokens_cached: int,
        tokens_out: int,
        provider: Optional[str] = None,
    ) -> float:
        """Compute estimated cost according to pricing table per million tokens."""
        pricing = get_model_pricing(model, provider=provider)
        uncached_in = max(0, tokens_in - tokens_cached)
        cost = (
            (uncached_in / 1_000_000.0) * pricing["input"]
            + (tokens_cached / 1_000_000.0) * pricing["cached_input"]
            + (tokens_out / 1_000_000.0) * pricing["output"]
        )
        return round(cost, 6)

    def estimate_call_cost(self, model: str, prompt: str, role: str, provider: Optional[str] = None) -> float:
        """Pre-call cost estimation."""
        est_in = max(100, len(prompt) // 4)
        base_est_out = 800 if role in ["solver", "explorer", "decomposer"] else 400
        est_out = min(base_est_out, ROLE_OUTPUT_TOKEN_CAPS.get(role, base_est_out))
        return self.compute_cost(model, est_in, 0, est_out, provider=provider)

    async def generate(
        self,
        role: str,
        prompt: str,
        schema: Optional[Type[BaseModel]] = None,
        model_override: Optional[str] = None,
        stable_prefix: str = "",
        reasoning_effort: str = "medium",
        context_hints: Optional[Dict[str, Any]] = None,
    ) -> GenerationResult:
        """Central inference method implementing primary Meta execution with eligible Baseten fallback."""
        route = self.get_route(role, model_override=model_override)
        full_prompt = (
            f"=== STABLE PREFIX (CACHED) ===\n{stable_prefix}\n\n"
            f"=== DYNAMIC PROMPT ===\n{prompt}"
            if stable_prefix
            else prompt
        )

        # 1. Check reservation against Primary
        primary_est_cost = self.estimate_call_cost(route.primary.model, full_prompt, role, provider=route.primary.provider)

        async with self.lock:
            projected = self.cumulative_cost_usd + self.reserved_cost_usd + primary_est_cost
            if projected >= 0.8 * self.budget_cap_usd and not self.warned_80_percent:
                self.warned_80_percent = True
                logger.warning(
                    f"[Budget Warning 80%] Projected spend (${projected:.4f}) reached 80% of cap (${self.budget_cap_usd:.2f})"
                )

            if projected > self.budget_cap_usd:
                raise BudgetExceededError(
                    f"Estimated upcoming call cost (${primary_est_cost:.4f}) would exceed run budget cap (${self.budget_cap_usd:.2f}). "
                    f"Current spend: ${self.cumulative_cost_usd:.4f}, in-flight: ${self.reserved_cost_usd:.4f}"
                )

            if route.primary.provider == "meta":
                if (self.cumulative_meta_usd + self.reserved_meta_usd + primary_est_cost) > self.budget_cap_meta_usd:
                    raise BudgetExceededError(
                        f"Estimated call would exceed Meta spending cap (${self.budget_cap_meta_usd:.2f})"
                    )
            elif route.primary.provider == "baseten":
                if (self.cumulative_baseten_usd + self.reserved_baseten_usd + primary_est_cost) > self.budget_cap_baseten_usd:
                    raise BudgetExceededError(
                        f"Estimated call would exceed Baseten spending cap (${self.budget_cap_baseten_usd:.2f})"
                    )

            # Reserve primary
            self.reserved_cost_usd += primary_est_cost
            if route.primary.provider == "baseten":
                self.reserved_baseten_usd += primary_est_cost
            else:
                self.reserved_meta_usd += primary_est_cost

        # Try Primary Execution
        try:
            if self.mock_mode:
                return await self._mock_call(role, full_prompt, route.primary.model, schema, context_hints, provider=route.primary.provider)
            else:
                return await self._execute_provider_with_retry(
                    provider=route.primary.provider,
                    model=route.primary.model,
                    role=role,
                    full_prompt=full_prompt,
                    schema=schema,
                    reasoning_effort=reasoning_effort,
                    max_attempts=3,  # Initial attempt + 2 retries
                )
        except (RetryableProviderError, NonRetryableProviderError, RuntimeError) as exc:
            # Check if fallback is eligible:
            # - Retryable errors can fall back to any configured fallback provider (Meta -> Baseten, or Baseten -> Meta)
            # - Non-retryable / auth / key / client-missing errors on a non-Meta provider can fall back to Meta API
            logger.warning(f"Primary call ({route.primary.provider}/{route.primary.model}) encountered failure: {exc}")
            is_retryable = isinstance(exc, RetryableProviderError)
            fallback_to_meta_on_key_failure = (
                route.primary.provider != "meta"
                and route.fallback is not None
                and route.fallback.provider == "meta"
            )
            can_fallback = (
                route.fallback is not None
                and self._provider_available(route.fallback.provider)
                and (
                    (is_retryable and (self.baseten_fallback_enabled or route.fallback.provider == "meta"))
                    or fallback_to_meta_on_key_failure
                )
            )

            if not can_fallback:
                logger.error(f"Fallback ineligible or disabled. Re-raising: {exc}")
                raise

            # Release primary reservation and check fallback provider budget.
            fallback_est_cost = self.estimate_call_cost(route.fallback.model, full_prompt, role, provider=route.fallback.provider)
            async with self.lock:
                self.reserved_cost_usd = max(0.0, self.reserved_cost_usd - primary_est_cost)
                self._release_provider_budget(route.primary.provider, primary_est_cost)

                if (self.cumulative_cost_usd + self.reserved_cost_usd + fallback_est_cost) > self.budget_cap_usd:
                    raise BudgetExceededError(
                        f"Fallback call cost (${fallback_est_cost:.4f}) would exceed run budget cap (${self.budget_cap_usd:.2f})"
                    )
                fallback_cumulative, fallback_reserved = self._provider_budget(route.fallback.provider)
                fallback_cap = (
                    self.budget_cap_baseten_usd
                    if route.fallback.provider == "baseten"
                    else self.budget_cap_meta_usd
                )
                if (fallback_cumulative + fallback_reserved + fallback_est_cost) > fallback_cap:
                    raise BudgetExceededError(
                        f"Fallback call cost (${fallback_est_cost:.4f}) would exceed {route.fallback.provider.title()} spending cap (${fallback_cap:.2f})"
                    )

                self.reserved_cost_usd += fallback_est_cost
                self._reserve_provider_budget(route.fallback.provider, fallback_est_cost)

            # Record / emit fallback event
            fallback_payload = {
                "role": role,
                "from_provider": route.primary.provider,
                "from_model": route.primary.model,
                "to_provider": route.fallback.provider,
                "to_model": route.fallback.model,
                "reason": str(exc),
            }
            logger.info(f"Triggering provider fallback: {fallback_payload}")
            if self.fallback_callback:
                try:
                    await self.fallback_callback(fallback_payload)
                except Exception as fb_err:
                    logger.warning(f"Error calling fallback_callback: {fb_err}")

            # Execute Fallback (bounded 2 attempts on Baseten: initial + 1 retry)
            try:
                if self.mock_mode:
                    result = await self._mock_call(
                        role, full_prompt, route.fallback.model, schema, context_hints,
                        provider=route.fallback.provider, fallback_used=True, fallback_reason=str(exc)
                    )
                else:
                    result = await self._execute_provider_with_retry(
                        provider=route.fallback.provider,
                        model=route.fallback.model,
                        role=role,
                        full_prompt=full_prompt,
                        schema=schema,
                        reasoning_effort=reasoning_effort,
                        max_attempts=2,
                        fallback_used=True,
                        fallback_reason=str(exc),
                    )
                return result
            finally:
                async with self.lock:
                    self.reserved_cost_usd = max(0.0, self.reserved_cost_usd - fallback_est_cost)
                    self._release_provider_budget(route.fallback.provider, fallback_est_cost)
        finally:
            async with self.lock:
                self.reserved_cost_usd = max(0.0, self.reserved_cost_usd - primary_est_cost)
                if route.primary.provider == "baseten":
                    self.reserved_baseten_usd = max(0.0, self.reserved_baseten_usd - primary_est_cost)
                else:
                    self.reserved_meta_usd = max(0.0, self.reserved_meta_usd - primary_est_cost)

    async def call(
        self,
        role: str,
        prompt: str,
        model: Optional[str] = None,
        schema: Optional[Type[BaseModel]] = None,
        stable_prefix: str = "",
        reasoning_effort: str = "medium",
        context_hints: Optional[Dict[str, Any]] = None,
    ) -> GenerationResult:
        """Direct call interface backwards-compatible with 5-tuple callers."""
        return await self.generate(
            role=role,
            prompt=prompt,
            schema=schema,
            model_override=model,
            stable_prefix=stable_prefix,
            reasoning_effort=reasoning_effort,
            context_hints=context_hints,
        )

    async def _execute_provider_with_retry(
        self,
        provider: str,
        model: str,
        role: str,
        full_prompt: str,
        schema: Optional[Type[BaseModel]],
        reasoning_effort: str,
        max_attempts: int,
        fallback_used: bool = False,
        fallback_reason: Optional[str] = None,
    ) -> GenerationResult:
        """Execute chat completion with typed OpenAI error handling, backoff, and usage parsing."""
        from openai import (
            RateLimitError,
            APIConnectionError,
            APITimeoutError,
            InternalServerError,
            APIStatusError,
            AuthenticationError,
            BadRequestError,
            NotFoundError,
        )

        client = self.baseten_client if provider == "baseten" else self.meta_client
        if client is None:
            raise RuntimeError(f"Client for provider '{provider}' is not configured.")

        system_instruction = (
            f"You are a Mini-Colosseum research agent acting as '{role}'. "
            "You must strictly return your answer as valid JSON matching the requested schema."
        )
        if "spark-open" in model or model == BASETEN_MODEL_ID:
            system_instruction += (
                " You must structure your output with a top-level '<analysis>' or 'analysis' block "
                "containing available_info, plan, and uncertainties before final proof content."
            )
        if role in ["global_verifier", "section_falsifier"]:
            system_instruction += (
                " For every reported defect or objection, you MUST include an 'exact_quote' field containing "
                "a verbatim substring from the source LaTeX text."
            )

        messages = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": full_prompt},
        ]

        kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.2 if role in ["gate", "global_verifier", "decomposer"] else 0.7,
            "max_tokens": ROLE_OUTPUT_TOKEN_CAPS.get(role, 1200),
        }
        if schema is not None:
            kwargs["response_format"] = {"type": "json_object"}
        if provider == "meta" and reasoning_effort and reasoning_effort in ["low", "medium", "high"]:
            kwargs["reasoning"] = {"effort": reasoning_effort}
            kwargs["reasoning_effort"] = reasoning_effort

        last_error = None
        base_delay = 1.0

        for attempt in range(max_attempts):
            response = None
            try:
                response = await client.chat.completions.create(**kwargs)
            except AuthenticationError as e:
                logger.error(f"Authentication failed on {provider}: {e}")
                raise NonRetryableProviderError(f"Authentication failed on {provider}: {e}", status_code=401) from e
            except BadRequestError as e:
                err_text = str(e).lower()
                if (
                    ("reasoning_effort" in kwargs or "reasoning" in kwargs)
                    and ("reasoning_effort" in err_text or "reasoning" in err_text)
                ):
                    logger.warning(f"Provider {provider} does not support reasoning controls. Retrying without them...")
                    kwargs.pop("reasoning_effort", None)
                    kwargs.pop("reasoning", None)
                    continue
                logger.error(f"Bad request on {provider}: {e}")
                raise NonRetryableProviderError(f"Bad request on {provider}: {e}", status_code=400) from e
            except NotFoundError as e:
                logger.error(f"Model not found on {provider}: {e}")
                raise NonRetryableProviderError(f"Model '{model}' not found on {provider}: {e}", status_code=404) from e
            except RateLimitError as e:
                error_msg = str(e).lower()
                is_quota = "quota" in error_msg or "insufficient" in error_msg or "balance" in error_msg
                last_error = RetryableProviderError(f"Rate limit exceeded on {provider}: {e}", status_code=429, is_quota=is_quota)
                if is_quota or attempt == max_attempts - 1:
                    raise last_error

                # Exponential backoff with jitter
                delay = base_delay * (2 ** attempt) + random.uniform(0.1, 0.5)
                # Check for Retry-After header if available
                retry_after = getattr(e, "response", None) and getattr(e.response, "headers", {}).get("retry-after")
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except (ValueError, TypeError):
                        pass
                logger.warning(f"HTTP 429 on {provider} ({model}). Retrying in {delay:.2f}s (attempt {attempt+1}/{max_attempts})...")
                await asyncio.sleep(delay)
                continue
            except (InternalServerError, APIConnectionError, APITimeoutError) as e:
                status_code = getattr(e, "status_code", 500)
                last_error = RetryableProviderError(f"Transient error on {provider}: {e}", status_code=status_code)
                if attempt == max_attempts - 1:
                    raise last_error
                delay = base_delay * (2 ** attempt) + random.uniform(0.1, 0.4)
                logger.warning(f"Transient error ({type(e).__name__}) on {provider}. Retrying in {delay:.2f}s...")
                await asyncio.sleep(delay)
                continue
            except APIStatusError as e:
                if 500 <= e.status_code <= 599:
                    last_error = RetryableProviderError(f"Server status {e.status_code} on {provider}: {e}", status_code=e.status_code)
                    if attempt == max_attempts - 1:
                        raise last_error
                    await asyncio.sleep(base_delay * (2 ** attempt) + random.uniform(0.1, 0.3))
                    continue
                else:
                    raise NonRetryableProviderError(f"API status error {e.status_code} on {provider}: {e}", status_code=e.status_code) from e
            except Exception as e:
                raise NonRetryableProviderError(f"Unexpected non-retryable error on {provider}: {e}") from e

            # Network call succeeded: extract content safely outside retry loop
            if response is not None:
                message = response.choices[0].message
                raw_text = message.content or ""
                if not raw_text.strip() and hasattr(message, "reasoning_content") and message.reasoning_content:
                    raw_text = message.reasoning_content

                tokens_in, tokens_cached, tokens_out = safe_extract_usage(response.usage, full_prompt, raw_text)
                cost = self.compute_cost(model, tokens_in, tokens_cached, tokens_out, provider=provider)

                async with self.lock:
                    self.cumulative_cost_usd += cost
                    self.total_tokens_in += tokens_in
                    self.total_tokens_cached += tokens_cached
                    self.total_tokens_out += tokens_out
                    self.total_calls += 1

                    if provider == "baseten":
                        self.cumulative_baseten_usd += cost
                        self.total_baseten_tokens_in += tokens_in
                        self.total_baseten_tokens_cached += tokens_cached
                        self.total_baseten_tokens_out += tokens_out
                    else:
                        self.cumulative_meta_usd += cost
                        self.total_meta_tokens_in += tokens_in
                        self.total_meta_tokens_cached += tokens_cached
                        self.total_meta_tokens_out += tokens_out

                parsed = self._extract_json(raw_text)
                if schema is not None:
                    parsed = self._validate_or_repair_schema(parsed, schema, role, raw_text)

                return GenerationResult(
                    parsed,
                    tokens_in,
                    tokens_cached,
                    tokens_out,
                    cost,
                    provider=provider,
                    model=model,
                    fallback_used=fallback_used,
                    fallback_reason=fallback_reason,
                )

        if last_error:
            raise last_error
        raise RuntimeError(f"Model call failed on provider '{provider}' after all retries.")

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """Extract and parse valid JSON from model completion text, removing markdown fences."""
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    pass
            return {"raw": text}

    def _validate_or_repair_schema(
        self, parsed: Dict[str, Any], schema: Type[BaseModel], role: str, raw_text: str
    ) -> Dict[str, Any]:
        """Strictly validate model output against schema with controlled unwrapping repair."""
        # 1. Direct validation
        try:
            return schema.model_validate(parsed).model_dump()
        except Exception:
            pass

        # 2. Check common nesting wrappers models produce (e.g. {"output": {...}}, {"result": {...}})
        if isinstance(parsed, dict):
            for key in ["output", "data", "result", role, "response", "content"]:
                if key in parsed and isinstance(parsed[key], dict):
                    try:
                        return schema.model_validate(parsed[key]).model_dump()
                    except Exception:
                        pass

        # 3. If validation fails and cannot be repaired, raise ValueError rather than returning malformed data
        try:
            return schema.model_validate(parsed).model_dump()
        except Exception as exc:
            logger.error(f"Schema validation strictly failed for role '{role}': {exc}")
            raise ValueError(f"Model response for role '{role}' failed schema validation: {exc}") from exc

    async def _mock_call(
        self,
        role: str,
        full_prompt: str,
        model: str,
        schema: Optional[Type[BaseModel]],
        context: Optional[Dict[str, Any]] = None,
        provider: str = "meta",
        fallback_used: bool = False,
        fallback_reason: Optional[str] = None,
    ) -> GenerationResult:
        """Deterministic simulation for local testing and offline verification."""
        ctx = context or {}

        # Allow tests to simulate primary rate limit failure to test fallback
        if ctx.get("simulate_meta_429") and provider == "meta":
            raise RetryableProviderError("Simulated HTTP 429 Rate Limit on Meta Spark", status_code=429)

        if ctx.get("simulate_meta_error") and provider == "meta":
            raise RetryableProviderError("Simulated HTTP 500 Internal Server Error on Meta", status_code=500)

        if ctx.get("simulate_baseten_429") and provider == "baseten":
            raise RetryableProviderError("Simulated HTTP 429 Rate Limit on Baseten", status_code=429)

        if ctx.get("simulate_baseten_error") and provider == "baseten":
            raise RetryableProviderError("Simulated HTTP 500 Internal Server Error on Baseten", status_code=500)

        if ctx.get("simulate_baseten_auth_error") and provider == "baseten":
            raise NonRetryableProviderError("Simulated HTTP 401 Invalid Key on Baseten", status_code=401)

        if ctx.get("simulate_auth_error"):
            raise NonRetryableProviderError(f"Simulated HTTP 401 Invalid Key on {provider.title()}", status_code=401)

        await asyncio.sleep(random.uniform(0.01, 0.04))
        problem = ctx.get("problem", "mathematical theorem")
        node_id = ctx.get("node_id", "NODE")

        tokens_in = random.randint(450, 1100)
        tokens_cached = int(tokens_in * random.uniform(0.6, 0.85))
        tokens_out = random.randint(280, 680)
        cost = self.compute_cost(model, tokens_in, tokens_cached, tokens_out, provider=provider)

        async with self.lock:
            self.cumulative_cost_usd += cost
            self.total_tokens_in += tokens_in
            self.total_tokens_cached += tokens_cached
            self.total_tokens_out += tokens_out
            self.total_calls += 1

            if provider == "baseten":
                self.cumulative_baseten_usd += cost
                self.total_baseten_tokens_in += tokens_in
                self.total_baseten_tokens_cached += tokens_cached
                self.total_baseten_tokens_out += tokens_out
            else:
                self.cumulative_meta_usd += cost
                self.total_meta_tokens_in += tokens_in
                self.total_meta_tokens_cached += tokens_cached
                self.total_meta_tokens_out += tokens_out

        output: Dict[str, Any] = {}

        if role == "explorer":
            output = {
                "analysis": {
                    "available_info": f"Problem target: {problem[:70]}... Constraints: n distinct elements, strict ordering.",
                    "plan": "Construct dual monotonic length label map i -> (a_i, b_i) and derive injectivity via trichotomy.",
                    "uncertainties": [
                        "Boundary preservation at n=1 (sequence length 2)",
                        "Symmetric extension when x_i > x_j",
                    ],
                },
                "normalized_problem": f"Establish formal proof for: {problem[:80]}...",
                "primary_route": f"Route via combinatorial pigeonhole principle on sequences with coordinate invariants (Candidate {node_id}).",
                "backup_routes": [
                    "Induction on sequence length using extremal prefix argument",
                    "Translation to Dilworth's poset decomposition theorem",
                ],
                "risky_lemmas": [
                    f"Lemma L1_{node_id}: Every poset of size n^2+1 has either an antichain of size n+1 or a chain of size n+1.",
                    f"Lemma L2_{node_id}: Monotonic order mapping preserves strict inequality.",
                ],
                "first_hard_obstruction": "Handling duplicate sequence elements or degeneracy at boundary bounds.",
                "active_obligations": [
                    "Verify strict inequality preservation",
                    "Check base case for n=1",
                ],
                "concrete_next_task": "Decompose into pigeonhole label definition and poset representation.",
                "readiness_assessment": "Concrete candidate with high likelihood of valid decomposition.",
            }

        elif role == "falsifier":
            severity_roll = random.random()
            if severity_roll > 0.8:
                verdict = "needs_repair"
                objections = [
                    {
                        "id": f"OBJ-{node_id}-1",
                        "severity": "major",
                        "claim": "poset chain partition assumes strict distinctness without explicit injection",
                        "repair": "Explicitly state hypothesis: all real numbers in sequence are distinct",
                        "exact_quote": "distinct real numbers",
                    }
                ]
            else:
                verdict = "survives"
                objections = []

            output = {
                "verdict": verdict,
                "assessment": f"Wonder 1.0 audited candidate {node_id}. Core inductive steps are sound. Boundary conditions verified.",
                "weakest_lemmas": [f"Lemma L1_{node_id} (poset chain bounds)"],
                "hidden_assumptions": ["Strict distinctness of input elements"],
                "boundary_cases": ["Sequence of length 2 (n=1)", "Alternating sequences"],
                "theorem_misuse": [],
                "categorized_objections": objections,
                "decisive_tests": ["Test with sequence [2, 1, 4, 3, 5]"],
                "unresolved_objections": [obj["claim"] for obj in objections],
            }

        elif role == "aggregator":
            parents = ctx.get("parents", [])
            output = {
                "analysis": {
                    "available_info": f"Synthesizing {len(parents)} parent strategies with attached Wonder 1.0 falsifier critiques.",
                    "plan": "Merge strongest invariants into a unified coordinate injection route while resolving preserved objections.",
                    "uncertainties": ["Ensure all parent boundary objections are explicitly addressed."],
                },
                "normalized_problem": f"Synthesized research strategy for: {problem[:80]}",
                "primary_route": f"Consolidated route merging strongest aspects of inputs ({', '.join(parents)}): Dilworth/Pigeonhole dual coordinates (t_i, s_i).",
                "backup_routes": [
                    "Poset chain decomposition via Greene-Kleitman invariants",
                ],
                "risky_lemmas": [
                    "Synthesized Lemma S1: The mapping from indices i to pairs (inc_len_i, dec_len_i) is strictly injective.",
                ],
                "first_hard_obstruction": "Injectivity proof under equality of distinct coordinate pairs.",
                "active_obligations": [
                    "Prove that if i < j and x_i < x_j, then inc_len_j >= inc_len_i + 1",
                    "Prove that if i < j and x_i > x_j, then dec_len_j >= dec_len_i + 1",
                ],
                "concrete_next_task": "Pass to readiness gate for structural audit.",
                "readiness_assessment": "High confidence; ready for decomposition.",
                "preserved_critiques": ctx.get("preserved_critiques", []),
            }

        elif role == "gate":
            output = {
                "verdict": "ready for decomposition",
                "fatal_bridge_claims": [],
                "cited_theorems": ["Pigeonhole Principle", "Transitivity of strict inequality in R"],
                "target_equivalence": "Exact match with problem statement",
                "hidden_hard_steps": "None identified in primary route",
                "unresolved_falsifier_objections": [],
                "obligation_severity": "minor",
                "explanation": "Wonder 1.0 evaluated the strategy: proof route is concrete, uses validated machinery, and provides explicit subproblem targets.",
            }

        elif role == "decomposer":
            output = {
                "latex_skeleton": r"""\documentclass{article}
\usepackage{amsmath,amssymb,amsthm}
\newtheorem{theorem}{Theorem}
\newtheorem{lemma}{Lemma}
\begin{document}
\title{Formal Derivation of Monotonic Subsequence Bound}
\maketitle
\begin{abstract}
We present a rigorous combinatorial proof utilizing coordinate pair labeling.
\end{abstract}
\section{Definitions and Coordinate Assignment}
%% SECTION_BODY_1 %%
\section{Strict Invariant and Injectivity}
%% SECTION_BODY_2 %%
\section{Pigeonhole Dimension Contradiction and Conclusion}
%% SECTION_BODY_3 %%
\end{document}""",
                "subproblems": [
                    {
                        "id": "SEC_1",
                        "index": 1,
                        "title": "Definitions and Coordinate Assignment",
                        "target_claim": "Assign to each element x_i in the sequence a pair (a_i, b_i), where a_i is length of longest increasing subsequence ending at x_i, and b_i is length of longest decreasing subsequence ending at x_i.",
                        "dependencies": [],
                    },
                    {
                        "id": "SEC_2",
                        "index": 2,
                        "title": "Strict Invariant and Injectivity",
                        "target_claim": "Prove that for any two distinct indices i < j, the pairs (a_i, b_i) and (a_j, b_j) are distinct.",
                        "dependencies": [1],
                    },
                    {
                        "id": "SEC_3",
                        "index": 3,
                        "title": "Pigeonhole Dimension Contradiction and Conclusion",
                        "target_claim": "Deduce that if no monotonic subsequence has length n+1, all pairs (a_i, b_i) satisfy 1 <= a_i, b_i <= n, giving at most n^2 distinct pairs, contradicting that there are n^2+1 elements.",
                        "dependencies": [1, 2],
                    },
                ],
            }

        elif role == "solver":
            sec_idx = ctx.get("section_index", 1)
            retry_count = ctx.get("retry_count", 0)
            rollout_num = ctx.get("rollout_num", 1)

            if sec_idx == 1:
                body = (
                    r"Let $S = (x_1, x_2, \dots, x_{n^2+1})$ be a sequence of distinct real numbers. "
                    r"For each index $i \in \{1, 2, \dots, n^2+1\}$, we define $a_i \ge 1$ to be the length of the longest "
                    r"increasing subsequence of $S$ that terminates at $x_i$, and $b_i \ge 1$ to be the length of the "
                    r"longest decreasing subsequence of $S$ that terminates at $x_i$. "
                    r"Since the single-element sequence $(x_i)$ is both trivially increasing and decreasing, we immediately have $a_i \ge 1$ and $b_i \ge 1$ for all $i$."
                )
                output = {
                    "analysis": {
                        "available_info": "Sequence of distinct real numbers S. Target: assign non-zero coordinate labels.",
                        "plan": "Define length functions for increasing and decreasing chains terminating at index i.",
                        "uncertainties": ["Ensure single-element base cases are well-defined."],
                    },
                    "claimed_result": "Well-defined coordinate map i -> (a_i, b_i) with a_i, b_i >= 1.",
                    "solution_body": body,
                    "bridge_claims": ["Existence of finite longest sub-chains"],
                    "unproved_obligations": [],
                    "status": "solved",
                    "rollout_index": rollout_num,
                }
            elif sec_idx == 2:
                if ctx.get("force_retry", False) and retry_count == 0:
                    body = (
                        r"Consider distinct indices $i < j$. If $x_i < x_j$, then any increasing subsequence terminating at $x_i$ "
                        r"can be extended by appending $x_j$, yielding a longer increasing subsequence of length at least $a_i + 1$. "
                        r"Thus $a_j \ge a_i + 1$. [Note: argument for the case $x_i > x_j$ was omitted in this attempt]."
                    )
                    output = {
                        "analysis": {
                            "available_info": "Established definitions a_i, b_i from Section 1.",
                            "plan": "Demonstrate that either a_j > a_i or b_j > b_i for any i < j.",
                            "uncertainties": ["Decreasing order case requires separate branch."],
                        },
                        "claimed_result": "Partial proof of injectivity (decreasing case missing).",
                        "solution_body": body,
                        "bridge_claims": ["Extension of chain"],
                        "unproved_obligations": ["Case x_i > x_j requires symmetric verification"],
                        "status": "partial",
                        "rollout_index": rollout_num,
                    }
                else:
                    body = (
                        r"Let $1 \le i < j \le n^2+1$. Since all elements in $S$ are distinct by hypothesis, we have either $x_i < x_j$ or $x_i > x_j$.\n\n"
                        r"\textbf{Case 1 ($x_i < x_j$):} Any increasing subsequence terminating at $x_i$ can be extended by appending $x_j$, "
                        r"yielding an increasing subsequence terminating at $x_j$ of length $a_i + 1$. Consequently, $a_j \ge a_i + 1 > a_i$.\n\n"
                        r"\textbf{Case 2 ($x_i > x_j$):} By identical symmetric reasoning, any decreasing subsequence terminating at $x_i$ can be extended "
                        r"by appending $x_j$, yielding a decreasing subsequence terminating at $x_j$ of length $b_i + 1$. Thus $b_j \ge b_i + 1 > b_i$.\n\n"
                        r"In either case, at least one coordinate strictly increases, which guarantees that $(a_i, b_i) \neq (a_j, b_j)$. Hence the mapping $i \mapsto (a_i, b_i)$ is strictly injective."
                    )
                    output = {
                        "analysis": {
                            "available_info": "Complete distinctness trichotomy x_i < x_j or x_i > x_j.",
                            "plan": "Prove that either coordinate strictly increases, guaranteeing injectivity.",
                            "uncertainties": [],
                        },
                        "claimed_result": "Injective mapping i -> (a_i, b_i) for all distinct i, j.",
                        "solution_body": body,
                        "bridge_claims": ["Case trichotomy over distinct real numbers"],
                        "unproved_obligations": [],
                        "status": "solved",
                        "rollout_index": rollout_num,
                    }
            else:
                body = (
                    r"Suppose, for the sake of contradiction, that $S$ contains no increasing subsequence of length $n+1$ "
                    r"and no decreasing subsequence of length $n+1$. "
                    r"Then for every $i \in \{1, 2, \dots, n^2+1\}$, we must have $1 \le a_i \le n$ and $1 \le b_i \le n$. "
                    r"The set of all possible coordinate pairs is therefore a subset of the Cartesian product $\{1, 2, \dots, n\} \times \{1, 2, \dots, n\}$, "
                    r"which contains exactly $n \cdot n = n^2$ distinct elements.\n\n"
                    r"However, by Lemma 2, the mapping $i \mapsto (a_i, b_i)$ is strictly injective, meaning each of the $n^2+1$ elements of $S$ is mapped to a unique pair. "
                    r"By the Pigeonhole Principle, $n^2+1$ distinct elements cannot be injectively mapped into a set of size $n^2$. "
                    r"This contradiction completes the proof: $S$ must contain at least one monotonic subsequence of length $n+1$."
                )
                output = {
                    "analysis": {
                        "available_info": "Injective coordinate map i -> (a_i, b_i) from Section 2; bound n^2+1 points.",
                        "plan": "Assume length <= n contradiction; bound size of image by n^2; apply Pigeonhole Principle.",
                        "uncertainties": [],
                    },
                    "claimed_result": "Complete contradiction and conclusion of theorem.",
                    "solution_body": body,
                    "bridge_claims": ["Pigeonhole Principle over finite set of size n^2"],
                    "unproved_obligations": [],
                    "status": "solved",
                    "rollout_index": rollout_num,
                }

        elif role == "section_falsifier":
            sec_idx = ctx.get("section_index", 1)
            retry_count = ctx.get("retry_count", 0)
            if ctx.get("force_retry", False) and sec_idx == 2 and retry_count == 0:
                output = {
                    "verdict": "rejected",
                    "fatal_objections": [
                        "Section 2 omitted the symmetric case x_i > x_j. Injectivity is unproved when elements decrease."
                    ],
                    "assessment": "Fatal gap: proof cannot proceed without establishing injectivity in both order directions.",
                    "suggested_repair": "Supply symmetric argument for decreasing subsequences when x_i > x_j.",
                    "exact_quote": "argument for the case $x_i > x_j$ was omitted",
                }
            else:
                output = {
                    "verdict": "ready",
                    "fatal_objections": [],
                    "assessment": f"Section {sec_idx} proof is rigorous and completely satisfies its claimed target.",
                    "suggested_repair": "None needed.",
                    "exact_quote": "",
                }

        elif role == "global_verifier":
            defects = ctx.get("simulated_defects", [])
            output = {
                "verdict": "rejected" if defects else "accepted",
                "defects": defects,
                "summary": "All sections are mutually consistent, the dependency chain is sound, and the contradiction via pigeonhole principle is fully justified." if not defects else "Defects detected during global review.",
                "unresolved_objections_preserved": [],
            }

        elif role == "curator":
            output = {
                "theorems_and_lemmas": [
                    {
                        "title": "Coordinate Injectivity Invariant",
                        "contents": "For distinct elements in a sequence, index mapping to (inc_len, dec_len) is strictly injective.",
                        "source": "Mini-Colosseum Section 2",
                        "caveats": "Requires distinctness of sequence entries.",
                    }
                ],
                "failed_approaches": [
                    {
                        "title": "Poset chain partitioning without injectivity",
                        "contents": "Attempted direct Dilworth decomposition without explicit pair mapping.",
                        "source": "Exploration Round 1",
                        "caveats": "More complex than coordinate pigeonhole argument.",
                    }
                ],
                "references": [
                    {
                        "title": "Erdős & Szekeres (1935)",
                        "contents": "A combinatorial problem in geometry. Compositio Math. 2, 463-470.",
                        "source": "Literature",
                        "caveats": "",
                    }
                ],
                "observations": [
                    {
                        "title": "Bound tight for n^2 elements",
                        "contents": "Sequence composed of n decreasing blocks of length n has no monotonic subsequence of length n+1.",
                        "source": "Extremal analysis",
                        "caveats": "Exact bound verified.",
                    }
                ],
            }

        if schema:
            try:
                validated = schema.model_validate(output)
                output = validated.model_dump()
            except Exception as e:
                logger.warning(f"Mock validation notice for {role}: {e}")

        return GenerationResult(
            output,
            tokens_in,
            tokens_cached,
            tokens_out,
            cost,
            provider=provider,
            model=model,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
        )
