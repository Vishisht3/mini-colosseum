"""
Model Client for Meta Muse Models (and High-Fidelity Simulator)
Handles:
- OpenAI-compatible endpoint calls (https://api.meta.ai/v1)
- Exponential backoff & jitter on HTTP 429
- Token accounting and exact cost tracking against pricing table
- Hard budget cap enforcement
- Prompt caching optimization
- Robust structured output validation & repair
"""

import json
import time
import asyncio
import random
import logging
from typing import Dict, Any, Optional, Tuple, Type
from pydantic import BaseModel
from .config import PRICING_TABLE, RATE_LIMITS, META_API_BASE_URL, META_API_KEY

logger = logging.getLogger("mini_colosseum.client")


class BudgetExceededError(Exception):
    """Raised when the cumulative spend exceeds the configured cap."""
    pass


class ModelClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        budget_cap_usd: float = 20.0,
        mock_mode: bool = False,
    ):
        self.api_key = api_key or META_API_KEY
        self.base_url = base_url or META_API_BASE_URL
        self.budget_cap_usd = budget_cap_usd
        # If no API key is provided, default to high-fidelity mock mode
        self.mock_mode = mock_mode or not bool(self.api_key)

        self.cumulative_cost_usd = 0.0
        self.total_tokens_in = 0
        self.total_tokens_cached = 0
        self.total_tokens_out = 0
        self.total_calls = 0
        self.lock = asyncio.Lock()

        # Simulated or real client
        self._openai_client = None
        if not self.mock_mode and self.api_key:
            try:
                from openai import AsyncOpenAI
                self._openai_client = AsyncOpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                )
            except Exception as e:
                logger.warning(f"Failed to initialize AsyncOpenAI client: {e}. Falling back to mock mode.")
                self.mock_mode = True

    def compute_cost(
        self,
        model: str,
        tokens_in: int,
        tokens_cached: int,
        tokens_out: int,
    ) -> float:
        """Compute cost according to the pricing table per million tokens."""
        pricing = PRICING_TABLE.get(model, PRICING_TABLE["muse-spark-1.3"])
        # Standard input is non-cached input
        uncached_in = max(0, tokens_in - tokens_cached)
        cost = (
            (uncached_in / 1_000_000.0) * pricing["input"]
            + (tokens_cached / 1_000_000.0) * pricing["cached_input"]
            + (tokens_out / 1_000_000.0) * pricing["output"]
        )
        return round(cost, 6)

    async def call(
        self,
        role: str,
        prompt: str,
        model: str,
        schema: Optional[Type[BaseModel]] = None,
        stable_prefix: str = "",
        reasoning_effort: str = "medium",
        context_hints: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], int, int, int, float]:
        """
        Execute model call with budget check, retry with backoff, token tracking, and structured validation.
        Returns: (parsed_json_output, tokens_in, tokens_cached, tokens_out, cost_usd)
        """
        async with self.lock:
            if self.cumulative_cost_usd >= self.budget_cap_usd:
                raise BudgetExceededError(
                    f"Cumulative cost (${self.cumulative_cost_usd:.4f}) exceeded budget cap (${self.budget_cap_usd:.2f})"
                )

        full_prompt = (
            f"=== STABLE PREFIX (CACHED) ===\n{stable_prefix}\n\n"
            f"=== DYNAMIC PROMPT ===\n{prompt}"
            if stable_prefix
            else prompt
        )

        if self.mock_mode:
            return await self._mock_call(role, full_prompt, model, schema, context_hints)

        # Real Meta Model API call via OpenAI SDK
        return await self._real_call(role, full_prompt, model, schema, reasoning_effort)

    async def _real_call(
        self,
        role: str,
        full_prompt: str,
        model: str,
        schema: Optional[Type[BaseModel]],
        reasoning_effort: str,
    ) -> Tuple[Dict[str, Any], int, int, int, float]:
        max_retries = 5
        base_delay = 1.0

        for attempt in range(max_retries):
            try:
                messages = [
                    {
                        "role": "system",
                        "content": (
                            f"You are a Mini-Colosseum research agent acting as '{role}'. "
                            "You must strictly return your answer as valid JSON matching the requested schema."
                        ),
                    },
                    {"role": "user", "content": full_prompt},
                ]

                kwargs: Dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0.2 if role in ["gate", "global_verifier", "decomposer"] else 0.7,
                }

                if schema is not None:
                    # Request JSON response format
                    kwargs["response_format"] = {"type": "json_object"}

                response = await self._openai_client.chat.completions.create(**kwargs)
                raw_text = response.choices[0].message.content or "{}"
                
                # Usage extraction
                usage = response.usage
                tokens_in = usage.prompt_tokens if usage else len(full_prompt) // 4
                tokens_out = usage.completion_tokens if usage else len(raw_text) // 4
                tokens_cached = getattr(usage, "prompt_tokens_details", {}).get("cached_tokens", 0) if usage else 0

                cost = self.compute_cost(model, tokens_in, tokens_cached, tokens_out)

                async with self.lock:
                    self.cumulative_cost_usd += cost
                    self.total_tokens_in += tokens_in
                    self.total_tokens_cached += tokens_cached
                    self.total_tokens_out += tokens_out
                    self.total_calls += 1

                # Parse and validate JSON
                parsed = self._extract_json(raw_text)
                if schema:
                    validated = schema.model_validate(parsed)
                    return validated.model_dump(), tokens_in, tokens_cached, tokens_out, cost
                return parsed, tokens_in, tokens_cached, tokens_out, cost

            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate limit" in error_str.lower():
                    delay = base_delay * (2 ** attempt) + random.uniform(0.1, 0.5)
                    logger.warning(f"HTTP 429 Rate limit on {model}. Retrying in {delay:.2f}s (attempt {attempt+1}/{max_retries})...")
                    await asyncio.sleep(delay)
                elif attempt < max_retries - 1:
                    await asyncio.sleep(1.0)
                else:
                    logger.error(f"Call failed after {max_retries} retries: {e}")
                    raise

        raise RuntimeError("Model call failed after all retries.")

    def _extract_json(self, text: str) -> Dict[str, Any]:
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
            # Fallback repair: find outermost braces
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                return json.loads(text[start : end + 1])
            return {"raw": text}

    async def _mock_call(
        self,
        role: str,
        full_prompt: str,
        model: str,
        schema: Optional[Type[BaseModel]],
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Any], int, int, int, float]:
        """Realistic mathematical simulation for reproducible local execution."""
        await asyncio.sleep(random.uniform(0.08, 0.22))
        ctx = context or {}
        problem = ctx.get("problem", "mathematical problem")
        node_id = ctx.get("node_id", "NODE")
        round_num = ctx.get("round", 1)

        tokens_in = random.randint(450, 1200)
        tokens_cached = int(tokens_in * random.uniform(0.6, 0.85))
        tokens_out = random.randint(300, 750)
        cost = self.compute_cost(model, tokens_in, tokens_cached, tokens_out)

        async with self.lock:
            self.cumulative_cost_usd += cost
            self.total_tokens_in += tokens_in
            self.total_tokens_cached += tokens_cached
            self.total_tokens_out += tokens_out
            self.total_calls += 1

        output: Dict[str, Any] = {}

        if role == "explorer":
            output = {
                "normalized_problem": f"Establish proof for: {problem[:80]}...",
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
            # Some falsifiers find repairable objections, rarely fatal
            severity_roll = random.random()
            if severity_roll > 0.8:
                verdict = "needs_repair"
                objections = [
                    {
                        "id": f"OBJ-{node_id}-1",
                        "severity": "major",
                        "claim": "poset chain partition assumes strict distinctness without explicit injection",
                        "repair": "Explicitly state hypothesis: all real numbers in sequence are distinct",
                    }
                ]
            else:
                verdict = "survives"
                objections = []

            output = {
                "verdict": verdict,
                "assessment": f"Audited candidate {node_id}. Core inductive steps are sound. Boundary conditions verified.",
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
                "merged_objections_addressed": f"Addressed all objections from parents {parents}: incorporated explicit distinctness requirement.",
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
                "explanation": "Strategy is concrete, uses standard validated machinery, and provides explicit subproblem targets.",
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

            if sec_idx == 1:
                body = (
                    r"Let $S = (x_1, x_2, \dots, x_{n^2+1})$ be a sequence of distinct real numbers. "
                    r"For each index $i \in \{1, 2, \dots, n^2+1\}$, we define $a_i \ge 1$ to be the length of the longest "
                    r"increasing subsequence of $S$ that terminates at $x_i$, and $b_i \ge 1$ to be the length of the "
                    r"longest decreasing subsequence of $S$ that terminates at $x_i$. "
                    r"Since the single-element sequence $(x_i)$ is both trivially increasing and decreasing, we immediately have $a_i \ge 1$ and $b_i \ge 1$ for all $i$."
                )
                output = {
                    "claimed_result": "Well-defined coordinate map i -> (a_i, b_i) with a_i, b_i >= 1.",
                    "solution_body": body,
                    "bridge_claims": ["Existence of finite longest sub-chains"],
                    "unproved_obligations": [],
                    "status": "solved",
                }
            elif sec_idx == 2:
                # If retry_count == 0 and we want to demo section retry, we can simulate an initial conditional/retry
                if ctx.get("force_retry", False) and retry_count == 0:
                    body = (
                        r"Consider distinct indices $i < j$. If $x_i < x_j$, then any increasing subsequence terminating at $x_i$ "
                        r"can be extended by appending $x_j$, yielding a longer increasing subsequence of length at least $a_i + 1$. "
                        r"Thus $a_j \ge a_i + 1$. [Note: argument for the case $x_i > x_j$ was omitted in this attempt]."
                    )
                    output = {
                        "claimed_result": "Partial proof of injectivity (decreasing case missing).",
                        "solution_body": body,
                        "bridge_claims": ["Extension of chain"],
                        "unproved_obligations": ["Case x_i > x_j requires symmetric verification"],
                        "status": "partial",
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
                        "claimed_result": "Injective mapping i -> (a_i, b_i) for all distinct i, j.",
                        "solution_body": body,
                        "bridge_claims": ["Case trichotomy over distinct real numbers"],
                        "unproved_obligations": [],
                        "status": "solved",
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
                    "claimed_result": "Complete contradiction and conclusion of theorem.",
                    "solution_body": body,
                    "bridge_claims": ["Pigeonhole Principle over finite set of size n^2"],
                    "unproved_obligations": [],
                    "status": "solved",
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
                }
            else:
                output = {
                    "verdict": "ready",
                    "fatal_objections": [],
                    "assessment": f"Section {sec_idx} proof is rigorous and completely satisfies its claimed target.",
                    "suggested_repair": "None needed.",
                }

        elif role == "global_verifier":
            output = {
                "verdict": "accepted",
                "defects": [],
                "summary": "All sections are mutually consistent, the dependency chain is sound, and the contradiction via pigeonhole principle is fully justified.",
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
                return validated.model_dump(), tokens_in, tokens_cached, tokens_out, cost
            except Exception as e:
                logger.warning(f"Mock validation fallback for {role}: {e}")

        return output, tokens_in, tokens_cached, tokens_out, cost
