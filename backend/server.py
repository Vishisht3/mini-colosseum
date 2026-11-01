"""
Mini-Colosseum Local Server & WebSocket Event Stream.
Based on Section 7 & Section 10 of Mini-Colosseum Specification v1.0.
Provides:
- REST API for run controls (Start, Pause, Resume, Step, Stop, Re-explore, Export, Replay)
- Real-time WebSocket connection on /ws streaming live node and log events
- Static files serving for the frontend UI
"""

import os
import json
import asyncio
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, PlainTextResponse, FileResponse
from pydantic import BaseModel

from .models import RunConfig, Event
from .store import RunStore
from .client import ModelClient
from .pipeline.orchestrator import Orchestrator
from .config import (
    META_API_BASE_URL, META_API_KEY, PRICING_TABLE,
    DEMO_PROBLEMS, SIZE_PRESETS, DEFAULT_ROLE_MODELS
)

app = FastAPI(title="Mini-Colosseum API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))
FIXTURES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "fixtures"))

store = RunStore()
active_orchestrator: Optional[Orchestrator] = None
active_task: Optional[asyncio.Task] = None
connected_websockets: List[WebSocket] = []

# Runtime Settings
server_settings = {
    "api_key": META_API_KEY,
    "base_url": META_API_BASE_URL,
    "default_budget_cap": 20.0,
    "default_models": DEFAULT_ROLE_MODELS.copy(),
    "mock_mode": not bool(META_API_KEY),
}


async def broadcast_event(event: Event):
    dead_sockets = []
    data_str = json.dumps({
        "event_type": event.event_type,
        "seq": event.seq,
        "run_id": event.run_id,
        "timestamp": event.timestamp,
        "payload": event.payload,
    })
    for ws in connected_websockets:
        try:
            await ws.send_text(data_str)
        except Exception:
            dead_sockets.append(ws)
    for ws in dead_sockets:
        if ws in connected_websockets:
            connected_websockets.remove(ws)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_websockets.append(websocket)
    try:
        while True:
            # Keep alive and listen for client commands if needed
            msg = await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in connected_websockets:
            connected_websockets.remove(websocket)


class StartRunRequest(BaseModel):
    problem_statement: str
    size_preset: str = "Hackathon-v1.1"
    tree_widths: Optional[List[int]] = None
    k_sample: Optional[int] = None
    budget_cap_usd: float = 20.0
    max_rounds: int = 2
    mock_mode: Optional[bool] = None
    cross_model_review: bool = True
    force_section_retry: bool = False


@app.post("/api/runs/start")
async def start_run(req: StartRunRequest):
    global active_orchestrator, active_task

    if active_task and not active_task.done():
        if active_orchestrator:
            active_orchestrator.stop()

    preset_cfg = SIZE_PRESETS.get(req.size_preset, SIZE_PRESETS["Hackathon-v1.1"])
    widths = req.tree_widths or preset_cfg.get("widths", [9, 6, 3, 1])
    k = req.k_sample or preset_cfg.get("k", 4)
    mock = req.mock_mode if req.mock_mode is not None else server_settings["mock_mode"]

    config = RunConfig(
        problem_statement=req.problem_statement,
        size_preset=req.size_preset,  # type: ignore
        tree_widths=widths,
        k_sample=k,
        cross_model_review=req.cross_model_review,
        models_per_role=server_settings["default_models"],
        budget_cap_usd=req.budget_cap_usd,
        max_rounds=req.max_rounds,
        mock_mode=mock,
    )

    client = ModelClient(
        api_key=server_settings["api_key"],
        base_url=server_settings["base_url"],
        budget_cap_usd=req.budget_cap_usd,
        mock_mode=mock,
    )

    active_orchestrator = Orchestrator(
        config=config,
        store=store,
        client=client,
        event_callback=broadcast_event,
    )

    active_task = asyncio.create_task(
        active_orchestrator.execute(force_section2_retry=req.force_section_retry)
    )

    return {
        "status": "started",
        "run_id": config.run_id,
        "config": config.model_dump(),
    }


@app.post("/api/runs/pause")
async def pause_run():
    if active_orchestrator:
        active_orchestrator.pause()
        return {"status": "paused"}
    return {"status": "no_active_run"}


@app.post("/api/runs/resume")
async def resume_run():
    if active_orchestrator:
        active_orchestrator.resume()
        return {"status": "resumed"}
    return {"status": "no_active_run"}


@app.post("/api/runs/step")
async def step_run():
    if active_orchestrator:
        active_orchestrator.step()
        return {"status": "stepped"}
    return {"status": "no_active_run"}


@app.post("/api/runs/stop")
async def stop_run():
    if active_orchestrator:
        active_orchestrator.stop()
        return {"status": "stopped"}
    return {"status": "no_active_run"}


@app.get("/api/runs")
async def list_runs():
    return store.list_runs()


@app.get("/api/runs/{run_id}")
async def get_run_trace(run_id: str):
    trace = store.export_trace_json(run_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Run not found")
    return trace


@app.get("/api/runs/{run_id}/export/latex")
async def export_latex(run_id: str):
    trace = store.export_trace_json(run_id)
    latex = trace.get("assembled_latex", "")
    return PlainTextResponse(latex, media_type="text/x-tex")


@app.get("/api/runs/{run_id}/export/objections")
async def export_objections(run_id: str):
    trace = store.export_trace_json(run_id)
    nodes = trace.get("nodes", [])
    lines = ["# Unresolved Objections Report\n"]
    for n in nodes:
        objs = n.get("objections", [])
        if objs:
            lines.append(f"## Node {n.get('label')} ({n.get('type')})")
            for o in objs:
                if isinstance(o, dict):
                    lines.append(f"- **{o.get('severity', 'claim').upper()}**: {o.get('claim', '')}")
                    if o.get("repair"):
                        lines.append(f"  *Suggested Repair*: {o.get('repair')}")
                else:
                    lines.append(f"- {o}")
            lines.append("")
    return PlainTextResponse("\n".join(lines), media_type="text/markdown")


@app.get("/api/runs/{run_id}/export/knowledge")
async def export_knowledge(run_id: str):
    trace = store.export_trace_json(run_id)
    return JSONResponse(trace.get("knowledge_directory", []))


@app.get("/api/runs/{run_id}/export/hmed")
async def export_hmed_records(run_id: str):
    """
    Export revision-consequence records in JSONL format for HMED (Meta Oct 2026).
    Enables direct consumption by offline distillation / RL pipelines.
    """
    trace = store.export_trace_json(run_id)
    records = trace.get("hmed_records", [])
    if not records:
        # If no local retry in this run, create benchmark example record
        records = store.export_hmed_records(run_id)
    jsonl_str = "\n".join(json.dumps(r) for r in records)
    return PlainTextResponse(jsonl_str, media_type="application/x-jsonlines")


@app.get("/api/eval/benchmark")
async def get_evaluation_benchmark():
    """
    Returns the 5-Lemma Evaluation Benchmark defined in SPEC v1.1.
    """
    return {
        "description": "5-Lemma reference-assisted evaluation benchmark (SPEC v1.1)",
        "protocol": "Direct frontier call vs. Mini-Colosseum (9,6,3,1) tree with cross-model falsification at matched compute cost",
        "lemmas": DEMO_PROBLEMS,
    }


@app.get("/api/fixtures/{fixture_name}")
async def load_fixture(fixture_name: str):
    filename = f"fixture_{fixture_name}.json"
    file_path = os.path.join(FIXTURES_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail=f"Fixture {fixture_name} not found")
    with open(file_path, "r") as f:
        data = json.load(f)
    # Also import into DB so it appears in run list and can be inspected
    store.import_trace_json(data)
    return data


@app.get("/api/problems")
async def get_demo_problems():
    return DEMO_PROBLEMS


@app.get("/api/settings")
async def get_settings():
    masked_key = ""
    if server_settings["api_key"]:
        masked_key = server_settings["api_key"][:4] + "..." + server_settings["api_key"][-4:]
    return {
        "api_key_set": bool(server_settings["api_key"]),
        "api_key_masked": masked_key,
        "base_url": server_settings["base_url"],
        "default_budget_cap": server_settings["default_budget_cap"],
        "default_models": server_settings["default_models"],
        "mock_mode": server_settings["mock_mode"],
        "pricing_table": PRICING_TABLE,
    }


class SettingsUpdateRequest(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    default_budget_cap: Optional[float] = None
    default_models: Optional[Dict[str, str]] = None
    mock_mode: Optional[bool] = None


@app.post("/api/settings")
async def update_settings(req: SettingsUpdateRequest):
    if req.api_key is not None:
        server_settings["api_key"] = req.api_key.strip()
        if req.api_key.strip():
            server_settings["mock_mode"] = False
    if req.base_url is not None:
        server_settings["base_url"] = req.base_url.strip()
    if req.default_budget_cap is not None:
        server_settings["default_budget_cap"] = req.default_budget_cap
    if req.default_models is not None:
        server_settings["default_models"].update(req.default_models)
    if req.mock_mode is not None:
        server_settings["mock_mode"] = req.mock_mode
    return {"status": "updated", "settings": await get_settings()}


# Serve frontend static files if present
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
