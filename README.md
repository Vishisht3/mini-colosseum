# Mini-Colosseum

Mini-Colosseum is a local research workbench for running a multi-stage inference pipeline against Meta models, with optional Baseten fallback routing and a desktop/browser UI for interactive runs, exports, and replay.

It is designed for theorem-style and proof-oriented workflows: a user supplies a problem, the system explores possible strategies, decomposes the task, solves subproblems, verifies claims, and emits structured outputs and provenance.

## Architecture overview

The project has four main layers:

1. Desktop/browser client
   - Electron shell in [electron/main.js](electron/main.js)
   - Static UI served from [frontend/index.html](frontend/index.html) and [frontend/js](frontend/js)
   - The front end renders the run tree, events, settings, and export/replay actions

2. FastAPI backend
   - Entry point: [backend/main.py](backend/main.py)
   - API and WebSocket server: [backend/server.py](backend/server.py)
   - Stores runs and event history in SQLite via [backend/store.py](backend/store.py)
   - Provides health checks, session validation, runtime configuration, and provider verification endpoints

3. Inference and routing layer
   - Provider abstractions and retry logic: [backend/client.py](backend/client.py)
   - Model URLs, provider configuration, and pricing caps: [backend/config.py](backend/config.py)
   - Shared data models and run schemas: [backend/models.py](backend/models.py)

4. Research/pipeline engine
   - Main orchestration and lifecycle: [backend/pipeline/orchestrator.py](backend/pipeline/orchestrator.py)
   - Stages include exploration, gate checking, decomposition, solving, verification, and curation:
     - [backend/pipeline/exploration.py](backend/pipeline/exploration.py)
     - [backend/pipeline/gate.py](backend/pipeline/gate.py)
     - [backend/pipeline/decomposition.py](backend/pipeline/decomposition.py)
     - [backend/pipeline/solving.py](backend/pipeline/solving.py)
     - [backend/pipeline/verification.py](backend/pipeline/verification.py)
     - [backend/pipeline/curator.py](backend/pipeline/curator.py)

### Runtime flow

1. The user launches the app or local backend.
2. The backend starts a FastAPI server on 127.0.0.1 with a session token.
3. The frontend connects to the WebSocket and submits a run request.
4. The orchestrator creates a run record and executes the pipeline stages.
5. Each stage emits events such as node creation, route selection, budget usage, and verification status.
6. The run can stop when reaching a budget cap, fail a validation gate, or complete successfully.
7. The UI can replay saved runs and export proofs, reports, traces, and ledger data.

## Directory layout

- [backend](backend): API server, store, client, models, pipelines, and orchestration
- [frontend](frontend): static HTML/CSS/JS for the web UI
- [electron](electron): Electron shell for packaged desktop usage
- [tests](tests): backend acceptance, routing, and HTTP integration tests
- [run.bat](run.bat): Windows one-click launcher
- [run.sh](run.sh): POSIX launcher for macOS/Linux
- [package.json](package.json): Node scripts and Electron packaging config
- [requirements.txt](requirements.txt): Python backend dependencies

## Prerequisites

- **Python 3.10+** (Python 3.10, 3.11, 3.12, 3.13, or 3.14)
- **Meta API Key** (required: `META_API_KEY` or `MODEL_API_KEY` for Muse Spark 1.3 & Muse Wonder 1.0)
- **Optional Baseten API Key** (for automatic fallback routing on Spark roles)
- *Optional:* **Node.js & npm** (only needed if using the Electron desktop wrapper or editing frontend bundle)

---

## How to Run the Software

Mini-Colosseum can be run in **Browser Mode** (recommended, zero-Node required) or **Desktop Electron Mode**.

### 1) Install Python Dependencies

Before the first run, install the required Python packages:

```bash
# On Windows:
py -m pip install -r requirements.txt

# On macOS / Linux:
python3 -m pip install -r requirements.txt
```

---

### Option 1: Windows One-Click (Recommended for Windows)

Simply double-click or run from cmd/terminal:
```cmd
run.bat
```
This launcher:
- Resolves your local Python executable (`py`, `python`, or local app paths)
- Automatically clears any stale background processes on port `8765`
- Bypasses PowerShell script execution restrictions safely
- Starts the FastAPI orchestrator and opens the RocqIDE UI in your default browser at `http://127.0.0.1:8765`

### Option 2: Windows PowerShell

If running directly from a PowerShell console, execute with execution policy bypass:
```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

### Option 3: macOS / Linux (Bash / Zsh)

Make the script executable and run:
```bash
chmod +x run.sh
./run.sh
```

### Option 3: Direct Python Terminal Command

You can run the backend directly without any wrapper scripts:
```bash
# Windows
py -m backend.main 8765

# macOS / Linux
python3 -m backend.main 8765
```
Then navigate to **http://127.0.0.1:8765** in any modern web browser.

### Option 4: Desktop Electron App

If you prefer running inside an isolated Electron desktop window:
```bash
# 1. Install Node dependencies (required for Electron)
npm install

# 2. Launch the desktop app
npm start
```

---

## Platform Launchers Summary

| Launcher | OS | How to Run | Notes |
| :--- | :--- | :--- | :--- |
| **`run.bat`** | Windows | Double-click or `run.bat` | Simplest Windows path; avoids PowerShell execution policy roadblocks |
| **`run.ps1`** | Windows | `powershell -ExecutionPolicy Bypass -File .\run.ps1` | Native PowerShell runner with automatic port release |
| **`run.sh`** | macOS / Linux | `./run.sh` | POSIX shell script with automatic readiness check |
| **Direct CLI** | All | `python -m backend.main 8765` | Direct Python command for browser mode (no wrappers) |
| **`npm start`** | All | `npm start` | Launches Electron desktop window (requires `npm install` first) |

---

## Configuration and Provider Setup

When you first launch Mini-Colosseum, the onboarding modal will prompt you for your API credentials:

1. **Meta API Key**: Required. Mini-Colosseum validates access to `muse-spark-1.3` (exploration and drafting) and `muse-wonder-1.0` (falsification, gate, and verification).
2. **Baseten API Key**: Optional. When configured, any rate limits (`429`), timeouts, or transient server failures on Spark roles automatically fail over to Baseten's `meta-models/muse-spark-open-1026`. Wonder roles always stay on Meta. If a Baseten key is missing or revoked, calls automatically fall back to Meta API.
3. **Keychain Security**: Valid keys are saved into your local operating system keychain or environment variables. Raw keys are never stored in SQLite run traces, logs, or exports.

---

## Running Tests

To verify the test suite:

```bash
# Run all backend unit, routing, and HTTP integration tests (61 tests)
python -m pytest

# Run frontend state reducer unit tests
node frontend/js/reducer.test.js
```

---

## Problem input and output

The app accepts human-readable problem statements and can ingest files such as:

- plain text
- Markdown
- LaTeX
- PDF, DOC, DOCX, and TEX attachments

Runs also support:

- replay of prior execution history
- export of proofs, reports, CSV ledgers, and JSON traces
- budget-aware stopping based on configured caps

## Security model

Mini-Colosseum keeps local execution constrained to loopback interfaces and validates a per-launch session token for app traffic. This protects the local UI and backend from cross-origin or external misuse while still allowing the browser or Electron app to connect to the same machine.

## Notes for contributors

- The pipeline uses fixed internal sampling and rollout constants, which are intentionally not exposed as user-facing runtime settings.
- Provider routing is explicit and model-aware; output tokens and reasoning parameters are capped and normalized per role.
- The project expects the backend and frontend to run in a local, loopback-only environment rather than as a public multi-user service.

## Summary

Mini-Colosseum is a local, desktop-first research harness that combines:

- a FastAPI backend for orchestration and telemetry
- a multi-stage solver pipeline for exploration, decomposition, verification, and curation
- provider-aware model routing with Meta primary and optional Baseten fallback
- a browser and Electron UI for interactive use and report export
