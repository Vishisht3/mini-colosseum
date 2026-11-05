## Handoff — Mini-Colosseum

### What this does

Mini-Colosseum is a local research workbench for running a multi-stage inference pipeline against Meta models, with optional Baseten/Fireworks providers that fall back to Meta on failure. Its promise for this problem is to produce a complete draft proving the best-known bounds for the Erdős unit-distance maximum, while rejecting fabricated or empty “proofs.”

Erdős unit-distance problem: For a finite set \(P\subset\mathbb R^2\) with \(|P|=n\), let \(U(P)\) be the number of pairs \(\{p_i,p_j\}\subset P\) with \(|p_i-p_j|=1\). What is \(U_{\max}(n)=\max_{|P|=n}U(P)\)?

Known useful answer target: There is no known exact closed form. The classical non-matching bounds are
\[
c\,n^{1+c/\log\log n} \le U_{\max}(n) \le C n^{4/3}
\quad\text{for large }n,
\]
with lattice/grid lower-bound ideas for the left inequality and point-circle incidence/crossing-lemma arguments for the right inequality.

### Current state

- The repo is `C:\Users\User\mini-colosseum`.
- This is a persistent workspace. Uncommitted working-tree changes are deliberate and should be preserved by continuing in this repo’s current checkout if available. Do **not** reset or clean it expecting a fresh tree.
- Current checkpoint branch: `unknown in handoff`.
- Run `76284825` was stopped at the user's request on 2026-11-05: it is saved as `cancelled`, final spend `$8.595`, and the app process on port `8771` (PID `13568`) was stopped. Its partial work is saved in the local run store (`%APPDATA%\Mini-Colosseum\mini_colosseum.db`) and can be viewed in Previous Runs; a fresh run is a new run, not a resumption of the cancelled task.
- No server is currently running. Start with `run.bat` (or `python -m backend.main 8765`) and open http://127.0.0.1:8765.

### Decisions already made

- Keep the full toolbar row — Run All / Step / Back / End / Pause / Stop / Re-explore — and remove duplicate buttons beside the statement bar.
- Keep one problem statement field; no separate conjecture field.
- Meta is the only fallback target. Baseten and Fireworks are optional and tried first only when enabled; failures fall back to Meta. Meta failures never fall back to Baseten or Fireworks.
- Startup asks for the Meta API key; Baseten and Fireworks are optional. Do not expose or reuse secrets in chat.
- Do not pre-fill problems, proofs, history, or mock data. No fabricated placeholder proof text. Verification data must be isolated so it does not pollute the real saved history.
- An empty plan must not be accepted; a proof with zero sections or zero text must be rejected, not marked complete.
- Obligations assigned to sections count as ready-with-obligations, not blocked, unless they are unassigned or the route is unusable.
- Keep the current layout unless a truly 1:1 replica is possible.

### Fixes already applied

- Fireworks provider added with Meta fallback; startup and settings were wired for optional Baseten/Fireworks.
- No pre-selected problems or pre-filled statement/value inputs in the UI; inspector placeholder content was neutralized.
- The statement bar was merged into a single problem statement field. Plain-English/readable rendering was added for math, superscripts, subscripts, and symbols in the proof preview.
- Duplicate buttons beside the statement bar were removed; the full toolbar row was restored as the single command set. The rightmost slider/resizer was wired. Inspector tabs were fixed so labels do not split mid-word; status widths were corrected.
- `preserved_critiques` as a single sentence is accepted and wrapped as a claim. The earlier hard failure on that shape was retested and passed.
- The global verifier cannot accept an empty proof. Decomposition gets one repair attempt and then fails honestly if it still produces no sections.
- The checker standard was corrected so assigned obligations pass to decomposition rather than blocking readiness.
- Aggregator and explorer output caps were raised.
- The readiness-gate wording was corrected so assigned obligations and standard-theorem steps are treated as work for the writing stage rather than a complete-proof demand at strategy stage.

### Verification evidence already gathered

- Latest full test run before this handoff: `21 passed` in the backend pytest suite.
- Earlier `py_compile` checks passed for `backend/models.py`, `backend/pipeline/decomposition.py`, and `backend/pipeline/verification.py`.
- A single decomposer/planner call succeeded and returned 9 sections after the cap and empty-completion fixes.
- Direct live run evidence in this session:
  - Run `fff6f579` initially failed in exploration on `preserved_critiques` being returned as a string.
  - The schema failure was fixed and the test suite passed.
  - A later full attempt `cd8863f4` was marked `unresolved` after multiple exploration rounds and cost about `$4.012`.
  - The currently live run `76284825` later passed the readiness gate in round 1 and entered solving.
- No honest claim should be made that the full pipeline has been proven end-to-end for this Erdős problem yet. The live solving result is the thing to recover first.

### Next steps

1. Re-check whether the port `8771` server/process is still alive before touching anything.
2. Recover run `76284825` first: read its current saved state and the latest sections before trying any rerun.
3. If the run died, inspect it exactly as saved; do not start a replacement run until the current draft state is known.
4. If a fresh run is truly needed, isolate any test data so the real saved history is not polluted.

### Honest gaps

- The live run may have finished, failed, or been interrupted after the last snapshot.
- The exact full-run outcome for this problem has not yet been honestly proven in the evidence collected here.
- The draft quality, section bodies, exact quotes, and final verification state still need direct inspection once the live/saved run is recovered.
- Cost against the `$100` budget should be re-summed from the saved run state before any further spend.

### How to resume

- Continue inside `C:\Users\User\mini-colosseum`; the current working tree already contains the deliberate fixes.
- Preserve this repo’s current checkout; do not reset, clean, or start over.
- If the checkpoint branch matters, verify it from the repo before starting new work; do not assume a branch name.
- Before any new run, check the live server state and recover run `76284825` from saved state first.
- From a fresh session, use `muse resume 01a1aad3-cb19-7142-b70b-94856950fcfb`, or start a new session in this workspace and open `handoff-mini-colosseum.md` plus `RESUME_CHECKPOINT.md` if present.
