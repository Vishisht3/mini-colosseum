# Mini-Colosseum Specification v1.1

**A Research-Harness Workbench Built on Meta Muse Models**  
*Refined for the Meta Global AI Developer Hackathon (3-Day Scope)*  
*Incorporating Recent Meta Research (Self-Credit, HMED, Retrieval Program Learning) & Peer Findings on Agent Memory*

**Document Version:** 1.1  
**Date:** 1 November 2026  
**Basis:** Architecture of *Stellar Colosseum* (Lin, Woodruff et al., Google Research, arXiv:2609.15983) + Meta HMED (Hindsight Meta-Experience Distillation)  
**Target API:** Meta Model API (`https://api.meta.ai/v1`, OpenAI-compatible)  

---

## 1. Executive Summary & Research Positioning

Recent Meta publications (Oct 2026) focus on long-horizon agent learning from sparse rewards (*Self-Credit*), verifiable environments (*InteractiveWorld*), and learning from failed revisions (*HMED*). Meta's internal AI math papers were developed through plain chat without an auditable long-horizon harness. 

**Mini-Colosseum v1.1** occupies this exact missing space:
1. **Auditable Long-Horizon Research**: A desktop multi-agent harness for mathematics and theoretical computer science.
2. **Anti-Persistence Raw Memory**: Replaces risky narrative memory summaries with raw verified claims and falsifier failure provenance (preventing error reproduction identified in arXiv:2610.27406).
3. **Cross-Model Adversarial Review**: Solvers and Falsifiers run across complementary models (Muse Spark vs. Muse Wonder), leveraging the 15-16% performance boost demonstrated by cross-model adversarial collaboration (ARIS, TCS-Bench).
4. **HMED Revision-Consequence Traces**: Every rejected attempt, paired critique, local retry, and outcome is logged as a structured revision-consequence record—directly consumable by Meta's HMED framework for agent distillation.

---

## 2. Scoped 3-Day Plan (What We Keep vs. What We Cut)

To guarantee a bulletproof, research-grade live demo within the hackathon timeline:

| Status | Features | Rationale |
|---|---|---|
| **KEEP (Core)** | • Multi-level Overlapping Tree Aggregation<br>• Readiness Gate<br>• Topological Proof Decomposition & DAG Scheduler<br>• Parallel Section Solving with Local Retry<br>• Non-voting Global Verification<br>• CoqIDE Scientific Desktop Interface<br>• Hard Budget Limiter ($20 default, live tracking)<br>• Zero-network Trace Replay & Exports | Demonstrates the fundamental multi-agent observability architecture and solves the long-horizon reliability issue. |
| **ADD (v1.1)** | • Anti-Persistence Memory Design<br>• Cross-Model Adversarial Review (Spark vs Wonder)<br>• Minimal High-Yield Tree: `(9, 6, 3, 1)` with `k = 4`<br>• HMED Revision-Consequence Trace Exporter<br>• 5-Lemma Reference-Assisted Evaluation Harness | Directly aligns with Meta's Oct 2026 research, fixes memory error loops, and provides concrete evaluation data. |
| **CUT (Scope Protection)** | • Learned Controller / RL layers<br>• Separate narrative curator LLM step<br>• Native OS installer (relying on one-command `./run.sh`)<br>• Voice dictation (Muse Voice Transcribe kept as simulation option)<br>• SAM and Muse Image integration<br>• Run-history list complexity (kept simple SQLite trace load) | Peer papers show learned controllers add cost without improving agent success; cuts eliminate API failure surface. |

---

## 3. Minimal Tree Configuration (About 75 Calls)

Instead of the expensive paper-scale trees ($100+$ calls), v1.1 standardizes on an optimal hackathon contraction tree:

| Stage | Configuration | Model Calls | Expected Node Reuse |
|---|---|---|---|
| **Exploration Tree** | Widths `(9, 6, 3, 1)`, $k = 4$ | ~38 calls | Layer 0 $\to$ 1: $(6 \times 4) / 9 = \mathbf{2.67}$<br>Layer 1 $\to$ 2: $(3 \times 4) / 6 = \mathbf{2.00}$<br>Matches paper's target of 2 to 3! |
| **Section Solving** | 4 sections, each width `(3, 1)` | ~32 calls | Local parallel solving with paired falsifier & retry |
| **Readiness Gate** | 1 Wonder call | 1 call | High-stakes audit |
| **Decomposition** | 1 Wonder call | 1 call | Cycle-checked topological DAG |
| **Global Verification** | 2 Wonder reviewers + 1 aggregator | ~3 calls | Non-voting localized defect detection |
| **Total per Full Run** | **~75 model calls** | **Total Cost: ~$1.20 - $1.80** | Safely within credits; enables 10+ full demo runs! |

---

## 4. Anti-Persistence Memory Architecture

Recent research (*"More Memory, Worse Agents: Error Reproduction and Anti-Persistence in LLM Agents"*, Oct 2026) proves that LLM-written narrative summaries hallucinate, preserve faulty intermediate claims, and degrade downstream agent accuracy over long horizons.

### v1.1 Anti-Persistence Rules:
1. **No Narrative Summaries**: Do not prompt a curator agent to generate English prose summaries of past rounds.
2. **Raw Provenance Storage**:
   ```json
   {
     "claim_id": "RAW-L0-1",
     "source_node": "S1",
     "target_statement": "Mapping i -> (a_i, b_i) is injective",
     "falsifier_verdict": "survives",
     "failure_point": null,
     "tested_boundary_cases": ["n=1", "strictly decreasing"]
   }
   ```
3. **Strict Gatekeeping**: Only claims whose falsifier verdict is `survives` (unfalsified) are placed into the stable prompt prefix.
4. **Dynamic Task-Specific Retrieval**: Downstream agents receive only verified raw claims pertinent to their specific lemma dependencies.

---

## 5. Cross-Model Adversarial Collaboration

Colosseum's benchmark results improved dramatically (54% $\to$ 71% on TCS-Bench) when candidate proposals were evaluated across disparate models.

| Role | Primary Model | Adversarial Reviewer | Why |
|---|---|---|---|
| **Exploration Leaves** | `muse-spark-1.3` | `muse-wonder-1.0` (or Spark Contributor) | Spark generates diverse routes cheaply; Wonder rigorously falsifies subtle edge-cases. |
| **Section Solvers** | `muse-spark-1.3` | `muse-wonder-1.0` | Cross-model review prevents blind spots where a model accepts its own biased reasoning. |
| **Gate & Decomposer** | `muse-wonder-1.0` | `muse-spark-1.3` | Wonder handles high-stakes planning; Spark audits for hidden step complexity. |
| **Global Verifier** | `muse-wonder-1.0` (2 independent) | Non-voting union | One concrete fatal defect causes rejection. |

---

## 6. HMED Revision-Consequence Trace Schema

To connect Mini-Colosseum with Meta's **Hindsight Meta-Experience Distillation (HMED)**, all section retries and gate re-explorations export revision tuples:

```json
{
  "record_id": "HMED-R1-SEC2",
  "run_id": "run_01af2c",
  "stage": "solving",
  "subproblem_index": 2,
  "failed_draft": "Consider distinct indices i < j. If x_i < x_j, then a_j >= a_i + 1...",
  "critique": "Section 2 omitted the symmetric case x_i > x_j. Injectivity is unproved when elements decrease.",
  "revised_draft": "Let 1 <= i < j <= n^2+1. Case 1 (x_i < x_j): a_j >= a_i + 1. Case 2 (x_i > x_j): b_j >= b_i + 1...",
  "downstream_verdict": "accepted",
  "attribution_defect": null,
  "cost_usd": 0.0084,
  "model_solver": "muse-spark-1.3",
  "model_falsifier": "muse-wonder-1.0"
}
```

These records provide dense training signals for post-training models to learn self-correction without reinforcement learning instability.

---

## 7. 5-Lemma Evaluation Benchmark

To rigorously demonstrate the value of the harness versus a single frontier model call at matched compute cost:

1. **Erdős-Szekeres Theorem**: Monotonic subsequence bound $n^2 + 1 \implies n + 1$.
2. **Ramsey Number $R(3, 3) = 6$**: Monochromatic triangle existence in 2-colored $K_6$.
3. **The Oddtown Theorem**: Linear algebraic club bound $m \le n$ via $\mathbb{F}_2$ incidence vectors.
4. **Mantel's Theorem**: Maximum edges $\lfloor n^2 / 4 \rfloor$ in triangle-free graphs.
5. **Caro-Wei / Turán Bound**: Independent set bound $\alpha(G) \ge \sum \frac{1}{d(v) + 1}$ in planar graphs.

**Evaluation Protocol**:
- Baseline: Direct call to `muse-wonder-1.0` with $k=3$ self-consistency samples.
- Harness: Mini-Colosseum with `(9, 6, 3, 1)` tree and cross-model falsification.
- Grader: Reference-assisted proof checklist checking claim soundness, boundary cases, and lemma dependency validity.
