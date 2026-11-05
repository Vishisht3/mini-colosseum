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
- [tests](tests): backend acceptance and routing tests
- [run.sh](run.sh): POSIX launcher for macOS/Linux
- [run.ps1](run.ps1): Windows launcher
- [package.json](package.json): Node scripts and Electron packaging config

## Prerequisites

- Python 3.10+
- Node.js and npm
- Access to a valid Meta API key
- Optional Baseten API key for fallback routing and budget shielding

## Quick start

### 1) Install dependencies

```bash
python -m pip install -r requirements.txt
npm install
```

### 2) Start the app in browser mode

This is the simplest local-development path and runs the backend directly without the Electron wrapper:

```bash
python -m backend.main 8765
```

Or use the npm shortcut:

```bash
npm run start:browser
```

Then open:

- http://127.0.0.1:8765

### 3) Start the desktop Electron app

```bash
npm start
```

This launches the Electron shell, which starts the backend process and points the app at the local loopback server. This is the intended end-user desktop experience.

## Platform launchers: why both run.sh and run.ps1?

Both scripts are thin convenience launchers for the same application. They exist because the project supports two native operating environments with different shell conventions:

- [run.sh](run.sh): for macOS and Linux users running Bash/Zsh
- [run.ps1](run.ps1): for Windows PowerShell users

They both do the same core job:

- locate Python
- start the backend with the local research harness
- wait until the health endpoint responds
- open the app in the default browser
- keep the backend process alive until the user exits

The difference is only in shell syntax and platform conventions. In other words, these are not competing implementations; they are equivalent startup entrypoints for the same runtime.

### Example

On macOS/Linux:

```bash
./run.sh
```

On Windows PowerShell:

```powershell
./run.ps1
```

## Configuration and provider setup

The first launch requires valid provider keys. These are verified against the provider endpoints and can be stored via the OS keychain when available.

Key behavior is intentionally local and loopback-scoped:

- Meta is the primary provider path
- Baseten may be enabled as an optional fallback route
- Sensitive credentials are not exposed in run configs or exported traces
- The app validates host, origin, and session token headers before accepting API traffic

## Running tests

```bash
python -m unittest discover -s tests -p "test_*.py"
```

```bash
npm run test:frontend
```

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

The shell scripts are simply the easiest way to start the same system on macOS/Linux or Windows without needing to remember the exact backend command sequence.
