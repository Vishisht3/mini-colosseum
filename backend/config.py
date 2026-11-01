"""
Configuration and pricing table for Mini-Colosseum.
Based on Section 8 & Section 9 of Mini-Colosseum Specification v1.0
"""

import os
from typing import Dict, Any

# Meta Model API Base URL (OpenAI-compatible)
META_API_BASE_URL = os.environ.get("META_API_BASE_URL", "https://api.meta.ai/v1")
META_API_KEY = os.environ.get("META_API_KEY", "")

# Pricing table per 1,000,000 tokens (USD)
PRICING_TABLE: Dict[str, Dict[str, float]] = {
    "muse-wonder-1.0": {
        "input": 4.00,
        "cached_input": 0.20,
        "output": 20.00,
    },
    "muse-spark-1.3": {
        "input": 1.25,
        "cached_input": 0.15,
        "output": 4.25,
    },
    "muse-spark-1.3-contributor": {
        "input": 0.10,
        "cached_input": 0.002,
        "output": 0.20,
    },
}

# Rate limits (requests per minute)
RATE_LIMITS: Dict[str, int] = {
    "muse-wonder-1.0": 3000,
    "muse-spark-1.3": 3000,
    "muse-spark-1.3-contributor": 150,
}

# Default role mappings
DEFAULT_ROLE_MODELS = {
    "explorer": "muse-spark-1.3-contributor",
    "falsifier": "muse-spark-1.3-contributor",
    "aggregator": "muse-spark-1.3-contributor",
    "gate": "muse-wonder-1.0",
    "decomposer": "muse-wonder-1.0",
    "solver": "muse-spark-1.3-contributor",
    "section_falsifier": "muse-spark-1.3-contributor",
    "global_verifier": "muse-wonder-1.0",
    "curator": "muse-spark-1.3-contributor",
}

# Standard demo problems and 5-lemma evaluation benchmark
DEMO_PROBLEMS = [
    {
        "id": "erdos_szekeres",
        "title": "Erdős-Szekeres Theorem on Monotonic Subsequences",
        "statement": "Prove that every sequence of n^2 + 1 distinct real numbers contains a monotonic subsequence of length n + 1 (either strictly increasing or strictly decreasing).",
        "known_route": "Pigeonhole principle on length of longest increasing subsequence ending at each element x_i.",
    },
    {
        "id": "oddtown",
        "title": "The Oddtown Theorem (Berlekamp 1969)",
        "statement": "In a town with n residents, a collection of clubs is formed such that every club has an odd number of members, and every two distinct clubs share an even number of members. Prove that the total number of clubs cannot exceed n.",
        "known_route": "Incidence vectors in F_2^n. Distinct club intersections modulo 2 yield identity Gram matrix over F_2, proving linear independence and dimension bound m <= n.",
    },
    {
        "id": "ramsey_k6",
        "title": "Ramsey Number R(3, 3) = 6",
        "statement": "Prove that in any 2-coloring of the edges of a complete graph K_6 with colors Red and Blue, there exists at least one monochromatic triangle.",
        "known_route": "Select arbitrary vertex v. By Pigeonhole Principle, at least 3 of its 5 incident edges have the same color. If any edge between those 3 endpoints has that color, a triangle is formed; otherwise the 3 endpoints form an opposite monochromatic triangle.",
    },
    {
        "id": "mantel",
        "title": "Mantel's Theorem on Triangle-Free Graphs",
        "statement": "Prove that every triangle-free graph on n vertices contains at most floor(n^2 / 4) edges, and that this bound is achieved by the complete bipartite graph K_{floor(n/2), ceil(n/2)}.",
        "known_route": "Sum of degrees across endpoints of each edge uv satisfies d(u) + d(v) <= n since N(u) and N(v) are disjoint. Summing over all edges gives sum d(v)^2 <= n * e; by Cauchy-Schwarz e <= n^2/4.",
    },
    {
        "id": "girth5_indset",
        "title": "Independent Sets in Planar Graphs of Girth >= 5",
        "statement": "Prove that every planar graph G with n vertices and girth at least 5 has an independent set of size at least n / 3.",
        "known_route": "Euler's formula gives 2e >= 5f and e = n + f - 2 => e <= (5/3)n - 10/3. By Caro-Wei or Turán bound, alpha(G) >= sum(1 / (d(v) + 1)) >= n / (avg_deg + 1) >= n / 3.",
    },
]

# Preset configurations
SIZE_PRESETS = {
    "Hackathon-v1.1": {
        "widths": [9, 6, 3, 1],
        "k": 4,
    },
    "Small": {
        "widths": [4, 2, 1],
        "k": 3,
    },
    "Medium": {
        "widths": [8, 4, 2, 1],
        "k": 3,
    },
    "Paper": {
        "widths": [16, 8, 4, 2, 1],
        "k": 5,
    },
}
