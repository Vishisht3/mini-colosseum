"""
Configuration and model routing for Mini-Colosseum v2.0.

Primary Provider (Required):
- Meta Model API (https://api.meta.ai/v1)
- Muse Spark 1.3 (Drafting, Exploration, Solving, Aggregation, Curating)
- Muse Wonder 1.0 (Verification, Critiques, Gating, Decomposition, Falsification)

Fallback Provider (Optional):
- Baseten (https://inference.baseten.co/v1)
- Muse Spark Open (meta-models/muse-spark-open-1026)
- Used ONLY as fallback for eligible Meta Spark requests when configured and enabled.
- Wonder never falls back to Baseten.
"""

import os
from dataclasses import dataclass
from typing import Dict, Any, Optional

# Meta Model API Base URL (OpenAI-compatible)
META_API_BASE_URL = os.environ.get("META_API_BASE_URL", "https://api.meta.ai/v1")
META_API_KEY = os.environ.get("META_API_KEY") or os.environ.get("MODEL_API_KEY") or ""

# Baseten Provider Base URL (OpenAI-compatible)
BASETEN_API_BASE_URL = os.environ.get("BASETEN_API_BASE_URL", "https://inference.baseten.co/v1")
BASETEN_API_KEY = os.environ.get("BASETEN_API_KEY", "")
BASETEN_MODEL_ID = "meta-models/muse-spark-open-1026"

# User-Configured Spending Caps & Budgets (USD)
DEFAULT_RUN_BUDGET_CAP = 7.00
DEFAULT_META_BUDGET_CAP = 150.00
DEFAULT_BASETEN_BUDGET_CAP = 100.00

# Retained aliases for backward compatibility with existing telemetry consumers
META_CREDIT_POOL = DEFAULT_META_BUDGET_CAP
BASETEN_CREDIT_POOL = DEFAULT_BASETEN_BUDGET_CAP

# Pricing table per 1,000,000 tokens (USD)
PRICING_TABLE: Dict[str, Dict[str, Any]] = {
    "muse-wonder-1.0": {
        "input": 4.00,
        "cached_input": 0.20,
        "output": 20.00,
        "provider": "meta",
    },
    "muse-spark-1.3": {
        "input": 1.25,
        "cached_input": 0.15,
        "output": 4.25,
        "provider": "meta",
    },
    "meta-models/muse-spark-open-1026": {
        "input": 0.50,
        "cached_input": 0.05,
        "output": 1.50,
        "provider": "baseten",
    },
    "muse-spark-1.3-contributor": {
        "input": 0.10,
        "cached_input": 0.002,
        "output": 0.20,
        "provider": "meta",
    },
}

def get_model_pricing(model: str, provider: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve pricing info by model and optional provider context."""
    if model in PRICING_TABLE:
        return PRICING_TABLE[model]
    if provider == "baseten":
        return PRICING_TABLE.get(BASETEN_MODEL_ID, {
            "input": 0.50, "cached_input": 0.05, "output": 1.50, "provider": "baseten"
        })
    return PRICING_TABLE.get("muse-spark-1.3", {
        "input": 1.25, "cached_input": 0.15, "output": 4.25, "provider": "meta"
    })

# Rate limits (requests per minute)
RATE_LIMITS: Dict[str, int] = {
    "muse-wonder-1.0": 3000,
    "meta-models/muse-spark-open-1026": 3000,
    "muse-spark-1.3": 3000,
    "muse-spark-1.3-contributor": 150,
}

@dataclass(frozen=True)
class RouteTarget:
    provider: str  # "meta" or "baseten"
    model: str

@dataclass(frozen=True)
class RoleRoute:
    primary: RouteTarget
    fallback: Optional[RouteTarget] = None

# Explicit typed routing table for all 9 pipeline roles
MODEL_ROUTES: Dict[str, RoleRoute] = {
    "explorer": RoleRoute(
        primary=RouteTarget(provider="meta", model="muse-spark-1.3"),
        fallback=RouteTarget(provider="baseten", model=BASETEN_MODEL_ID),
    ),
    "aggregator": RoleRoute(
        primary=RouteTarget(provider="meta", model="muse-spark-1.3"),
        fallback=RouteTarget(provider="baseten", model=BASETEN_MODEL_ID),
    ),
    "solver": RoleRoute(
        primary=RouteTarget(provider="meta", model="muse-spark-1.3"),
        fallback=RouteTarget(provider="baseten", model=BASETEN_MODEL_ID),
    ),
    "curator": RoleRoute(
        primary=RouteTarget(provider="meta", model="muse-spark-1.3"),
        fallback=RouteTarget(provider="baseten", model=BASETEN_MODEL_ID),
    ),
    "falsifier": RoleRoute(
        primary=RouteTarget(provider="meta", model="muse-wonder-1.0"),
        fallback=None,
    ),
    "gate": RoleRoute(
        primary=RouteTarget(provider="meta", model="muse-wonder-1.0"),
        fallback=None,
    ),
    "decomposer": RoleRoute(
        primary=RouteTarget(provider="meta", model="muse-wonder-1.0"),
        fallback=None,
    ),
    "section_falsifier": RoleRoute(
        primary=RouteTarget(provider="meta", model="muse-wonder-1.0"),
        fallback=None,
    ),
    "global_verifier": RoleRoute(
        primary=RouteTarget(provider="meta", model="muse-wonder-1.0"),
        fallback=None,
    ),
}

# Default role models mapping (primary models)
DEFAULT_ROLE_MODELS: Dict[str, str] = {
    role: route.primary.model for role, route in MODEL_ROUTES.items()
}

FIXED_TREE_WIDTHS = [9, 6, 3, 1]
FIXED_SAMPLE_COUNT = 4
FIXED_ROLLOUT_COUNT = 4

# Provider request output caps by role (hard guardrail for per-call spend).
ROLE_OUTPUT_TOKEN_CAPS: Dict[str, int] = {
    "explorer": 1800,
    "aggregator": 1800,
    "solver": 2200,
    "curator": 1200,
    "falsifier": 1400,
    "gate": 1100,
    "decomposer": 1800,
    "section_falsifier": 1400,
    "global_verifier": 1800,
}
