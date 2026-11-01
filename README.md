# Mini-Colosseum

**A Research-Harness Workbench Built on Meta Muse Models**  
*Implementing the architecture of "Stellar Colosseum" (Lin, Woodruff et al., Google Research, arXiv:2609.15983)*

---

## 1. Overview

**Mini-Colosseum** is an installable desktop research harness and observability workbench for long-horizon mathematics and theoretical computer science. Language models can write plausible short proofs, but easily derail over long chains of uncertain, interdependent decisions. Mini-Colosseum addresses this with explicit multi-stage workflow control, adversarial review ("falsifiers"), and overlapping reduction trees.

Unlike a conversational chatbot, Mini-Colosseum treats mathematical research as an **inspectable, replayable, and measurable multi-agent process**:
- **Research Tree**: Live visualization of competing research routes, paired adversarial falsifier critiques, and random-sample tree aggregation exhibiting **overlapping reuse** (candidates consumed across multiple synthesis nodes).
- **Proof DAG**: Top-down dependency graph of decomposed subproblems solved in parallel, featuring **local section retries** where a rejected section visibly reruns on its own node while completed work elsewhere stays untouched.
- **Assembled Document**: Live assembled LaTeX proof rendered with status tinting (reminiscent of the green processed region in CoqIDE) and margin defect annotations.
- **Node Inspector**: CoqIDE-style subgoal dividers (`1/4 Input`, `2/4 Output`, `3/4 Falsifier Report`, `4/4 Unresolved Objections`).
- **Zero-Network Trace Replay**: Every run is stored in an SQLite database and can be reopened, inspected, and stepped through offline without invoking any models.

---

## 2. The 5-Stage Workflow

```
                        [ Problem Statement ]
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│ STAGE 1: STRATEGY EXPLORATION                                    │
│  Leaf Candidates (S1, S2, ..., Sn) paired with Falsifiers        │
│  Overlapping reduction tree: Aggregators sample k inputs from    │
│  level below (independent across nodes -> overlapping reuse)     │
└─────────────────────────────────┬────────────────────────────────┘
                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│ STAGE 2: READINESS GATE                                          │
│  Audits fatal bridge claims, cited hypotheses, and obligations   │
│  Verdicts: Ready, Conditional, Further Exploration, or Reject    │
└─────────────────────────────────┬────────────────────────────────┘
                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│ STAGE 3: PROOF DECOMPOSITION                                     │
│  Builds topological subproblem DAG with cycle check              │
│  Produces master LaTeX document skeleton with placeholders       │
└─────────────────────────────────┬────────────────────────────────┘
                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│ STAGE 4: SUBPROBLEM SOLVING (Proof DAG)                          │
│  Runs eligible independent sections in parallel                  │
│  Local falsifier audits each candidate solution                  │
│  On rejection: only that section retries with critique           │
└─────────────────────────────────┬────────────────────────────────┘
                                  ▼
┌──────────────────────────────────────────────────────────────────┐
│ STAGE 5: GLOBAL VERIFICATION & REVISION                          │
│  Independent verifiers audit full assembled document             │
│  Non-voting aggregation: one single concrete defect rejects!     │
└─────────────────────────────────┬────────────────────────────────┘
                                  ▼
             [ Fully Assembled & Verified LaTeX Proof ]
```

---

## 3. Meta Muse Models & Pricing

Mini-Colosseum uses the OpenAI-compatible Meta Model API (`https://api.meta.ai/v1`):

| Role in Product | Model | Pricing (Input / Cached / Output per 1M) | Rate Limit |
|---|---|---|---|
| Explorers, falsifiers, section solvers | `muse-spark-1.3` (`muse-spark-1.3-contributor` for dev) | Standard: $1.25 / $0.15 / $4.25<br>Contributor: $0.10 / $0.002 / $0.20 | 3,000 / min (Standard)<br>150 / min (Contributor) |
| Readiness gate, decomposer, global verifiers, root aggregators | `muse-wonder-1.0` | $4.00 / $0.20 / $20.00 | 3,000 / min |
| Voice dictation | `muse-voice-transcribe-1.0` | $0.18 / hr of audio | - |

- **Hard Budget Limiter**: Enforces a configurable cap (default $20.00) in real time. When reached, in-flight calls complete and new calls halt immediately with clear UI banners.
- **High-Fidelity Offline Simulator Mode**: Enabled automatically when no API key is set, providing realistic mathematical proofs, falsifier attacks, DAG retries, and verifications without burning credits.

---

## 4. CoqIDE Desktop Aesthetic

Following Section 6 of the Technical Specification:
- **Design Principle**: Information density and clarity over decorative styling.
- **Typography**: Monospace for mathematics, logs, code, and JSON; clean neutral system font for menus and chrome.
- **Palette**: Cream/white background (`#f4f4f0` / `#ffffff`), near-black text, 1px grey borders (`#c4c4be`), square corners, zero dropshadows/gradients.
- **Status Conventions**: Always paired with a glyph:
  - `[-] PENDING`: Grey
  - `[~] RUNNING`: Blue
  - `[OK] ACCEPTED`: Green
  - `[?] CONDITIONAL`: Amber
  - `[X] REJECTED`: Red
  - `[!] ERROR`: Dark red

---

## 5. Quickstart & One-Command Launch

Launch the complete application with a single command:

```bash
./run.sh
```

Or via npm:

```bash
npm start
```

This starts the Python backend orchestrator on `http://127.0.0.1:8765`, loads all pre-recorded fixtures, and launches the desktop app window.

### Running Test Suite

Mini-Colosseum includes a 12-test suite verifying all acceptance criteria and pipeline contracts:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

---

## 6. Pre-Recorded Benchmark Fixtures

Three pre-recorded traces are bundled in `backend/fixtures/` and can be loaded directly from the **File** menu or via the API:

1. **`fixture_clean_success.json`**: End-to-end 5-stage proof of the Erdős-Szekeres Theorem on monotonic subsequences.
2. **`fixture_section_retry.json`**: Proves Ramsey Number $R(3, 3) = 6$ with Section 2 visibly failing initial review and automatically retrying locally to success.
3. **`fixture_re_exploration.json`**: Independent sets in planar graphs of girth $\ge 5$, illustrating Gate rejection in Round 1 and automatic Round 2 re-exploration with collapsed Round 1.

---

## 7. Acceptance Criteria Verification (Section 13.2)

- [x] **One-command launcher**: `./run.sh` initializes backend and opens desktop window.
- [x] **Autonomous end-to-end run**: Finishes without manual intervention.
- [x] **Live Research Tree & Proof DAG**: Real-time WebSocket streaming of node creations, updates, and edges.
- [x] **Overlapping reuse**: Clear directed edges where candidate leaves feed multiple aggregators.
- [x] **Complete traceability**: Every node inspects prompt inputs, outputs, models, tokens, cost, and attached falsifier reports.
- [x] **Local section retry**: Rejected sections visibly retry on their own node while other sections stay untouched.
- [x] **Non-voting global verification**: Rejection on a single concrete defect localized to section or claim.
- [x] **Spending & budget cap**: Live display and hard stop on budget exhaustion.
- [x] **Replayable traces**: Every run stored in SQLite; reloadable offline with zero network calls.
- [x] **Artifact exports**: Proof as LaTeX (`.tex`), trace as JSON, objections as Markdown (`.md`), knowledge as JSON.
- [x] **CoqIDE scientific UI**: High information density, square corners, status colors always paired with glyphs.
