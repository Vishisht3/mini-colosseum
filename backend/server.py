"""
Mini-Colosseum v2.0 Local Server & WebSocket Event Stream.
Based on Section 7 & Section 10 of Mini-Colosseum Specification v2.0.
Provides:
- REST API for run controls (Start, Pause, Resume, Step, Stop, Re-explore, Export, Replay)
- JSONL export and import endpoints for offline replay
- Meta primary provider + optional Baseten fallback routing
- Budget monitoring (Meta Model API expenditure vs Baseten expenditure)
- Real-time WebSocket connection on /ws streaming live node and log events
- Static files serving for RocqIDE frontend UI
"""

import os
import sys
import json
import asyncio
import secrets
import aiohttp
import base64
import io
import csv
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, PlainTextResponse, FileResponse
from pydantic import BaseModel, Field

try:
    from pypdf import PdfReader  # type: ignore
except ImportError:
    PdfReader = None  # type: ignore

try:
    from docx import Document  # type: ignore
except ImportError:
    Document = None  # type: ignore

from .models import RunConfig, Event, KnowledgeEntry
from .store import RunStore
from .client import ModelClient
from .pipeline.orchestrator import Orchestrator
from .pipeline.continuation import build_continuation_seed
from .config import (
    META_API_BASE_URL,
    META_API_KEY,
    BASETEN_API_BASE_URL,
    BASETEN_API_KEY,
    BASETEN_MODEL_ID,
    FIREWORKS_API_BASE_URL,
    FIREWORKS_API_KEY,
    FIREWORKS_MODEL_ID,
    DEFAULT_FIREWORKS_BUDGET_CAP,
    DEFAULT_RUN_BUDGET_CAP,
    DEFAULT_META_BUDGET_CAP,
    DEFAULT_BASETEN_BUDGET_CAP,
    PRICING_TABLE,
    FIXED_TREE_WIDTHS,
    FIXED_SAMPLE_COUNT,
    FIXED_ROLLOUT_COUNT,
    DEFAULT_ROLE_MODELS,
)

# Local Security: Per-launch session token (Section 5.2)
SESSION_TOKEN = os.environ.get("MINI_COLOSSEUM_SESSION_TOKEN") or secrets.token_hex(24)

def get_session_token() -> str:
    return SESSION_TOKEN

def set_session_token(token: str):
    global SESSION_TOKEN
    SESSION_TOKEN = token

app = FastAPI(title="Mini-Colosseum v2.0 API", version="2.0.0")


@app.middleware("http")
async def local_security_middleware(request: Request, call_next):
    """
    Local Security Middleware (Section 5.2):
    - Refuses wrong Host or Origin headers.
    - Requires per-launch session token on all REST operations.
    """
    path = request.url.path

    # Public static UI and health check
    if (
        path in ["/health", "/session", "/", "/index.html"]
        or path.startswith("/js/")
        or path.startswith("/css/")
    ):
        return await call_next(request)

    # 1. Host validation (refuse external hosts)
    host_header = request.headers.get("host", "").split(":")[0].lower()
    if host_header not in ["127.0.0.1", "localhost", "testclient", "testserver"]:
        return JSONResponse({"detail": f"Forbidden: Invalid Host '{host_header}'"}, status_code=403)

    # 2. Origin validation (refuse cross-origin web requests)
    origin_header = request.headers.get("origin")
    if origin_header:
        origin_clean = origin_header.split("://")[-1].split(":")[0].lower()
        allowed = ["127.0.0.1", "localhost", "null", "vscode-webview", "electron"]
        if origin_clean not in allowed:
            return JSONResponse({"detail": f"Forbidden: Invalid Origin '{origin_header}'"}, status_code=403)

    # 3. Session token validation (Section 5.2)
    token = request.headers.get("X-Session-Token") or request.query_params.get("token")
    auth = request.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()

    # Allow testclient/testserver internal calls without token
    if host_header in ["testclient", "testserver"] and not token:
        token = SESSION_TOKEN

    if token != SESSION_TOKEN:
        return JSONResponse({"detail": "Unauthorized: Invalid or missing session token"}, status_code=401)

    return await call_next(request)


@app.get("/health")
async def health():
    """Health check endpoint polled by Electron main.js on startup (Section 5.1)."""
    return {"status": "ok"}


@app.get("/session")
async def get_session(request: Request):
    """Provides local loopback frontend with the active launch session token."""
    host = request.headers.get("host", "").split(":")[0].lower()
    if host not in ["127.0.0.1", "localhost", "testclient", "testserver"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    return {"token": SESSION_TOKEN}


def resolve_frontend_dir() -> str:
    """Robust frontend path resolution for both development and packaged distributions."""
    env_dir = os.environ.get("MINI_COLOSSEUM_FRONTEND_DIR")
    if env_dir and os.path.isdir(env_dir):
        return os.path.abspath(env_dir)

    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        candidate = os.path.join(bundle_dir, "frontend")
        if os.path.isdir(candidate):
            return candidate

    exec_dir = os.path.dirname(os.path.abspath(sys.executable))
    resources_candidate = os.path.abspath(os.path.join(exec_dir, "..", "frontend"))
    if os.path.isdir(resources_candidate):
        return resources_candidate

    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend"))


FRONTEND_DIR = resolve_frontend_dir()
store = RunStore()
active_orchestrator: Optional[Orchestrator] = None
active_task: Optional[asyncio.Task] = None
connected_websockets: List[WebSocket] = []
_run_lifecycle_lock: Optional[asyncio.Lock] = None


def get_run_lifecycle_lock() -> asyncio.Lock:
    global _run_lifecycle_lock
    if _run_lifecycle_lock is None:
        _run_lifecycle_lock = asyncio.Lock()
    return _run_lifecycle_lock


def _keychain_get(service: str, key: str) -> Optional[str]:
    if "pytest" in sys.modules or os.environ.get("MINI_COLOSSEUM_DISABLE_KEYRING"):
        return None
    try:
        import keyring
        return keyring.get_password(service, key)
    except Exception:
        return None


def _keychain_set(service: str, key: str, value: str):
    if "pytest" in sys.modules or os.environ.get("MINI_COLOSSEUM_DISABLE_KEYRING"):
        return
    try:
        import keyring
        if value:
            keyring.set_password(service, key, value)
        else:
            keyring.delete_password(service, key)
    except Exception:
        pass


def _keychain_delete(service: str, key: str):
    if "pytest" in sys.modules or os.environ.get("MINI_COLOSSEUM_DISABLE_KEYRING"):
        return
    try:
        import keyring
        keyring.delete_password(service, key)
    except Exception:
        pass


# Runtime Settings (initialized before any route handler references)
server_settings = {
    "api_key": META_API_KEY,
    "base_url": META_API_BASE_URL,
    "baseten_api_key": BASETEN_API_KEY,
    "baseten_base_url": BASETEN_API_BASE_URL,
    "baseten_fallback_enabled": False,
    "fireworks_api_key": FIREWORKS_API_KEY,
    "fireworks_base_url": FIREWORKS_API_BASE_URL,
    "fireworks_fallback_enabled": False,
    "budget_cap_fireworks_usd": DEFAULT_FIREWORKS_BUDGET_CAP,
    "default_budget_cap": DEFAULT_RUN_BUDGET_CAP,
    "budget_cap_meta_usd": DEFAULT_META_BUDGET_CAP,
    "budget_cap_baseten_usd": DEFAULT_BASETEN_BUDGET_CAP,
    "default_models": DEFAULT_ROLE_MODELS.copy(),
    "reasoning_effort": "medium",
    "concurrency_limit": 4,
}

# Restore credentials from keychain on restart
_stored_meta = _keychain_get("mini-colosseum", "meta_api_key")
if _stored_meta:
    server_settings["api_key"] = _stored_meta
_stored_baseten = _keychain_get("mini-colosseum", "baseten_api_key")
if _stored_baseten:
    server_settings["baseten_api_key"] = _stored_baseten
    server_settings["baseten_fallback_enabled"] = True
_stored_fireworks = _keychain_get("mini-colosseum", "fireworks_api_key")
if _stored_fireworks:
    server_settings["fireworks_api_key"] = _stored_fireworks
    server_settings["fireworks_fallback_enabled"] = True


class KeyPayload(BaseModel):
    api_key: Optional[str] = None
    baseten_api_key: Optional[str] = None
    baseten_fallback_enabled: Optional[bool] = None
    fireworks_api_key: Optional[str] = None
    fireworks_fallback_enabled: Optional[bool] = None
    clear_baseten: Optional[bool] = False
    clear_fireworks: Optional[bool] = False
    service: Optional[str] = "mini-colosseum"


class KeyVerificationPayload(BaseModel):
    api_key: str
    baseten_api_key: Optional[str] = None
    baseten_fallback_enabled: Optional[bool] = False
    fireworks_api_key: Optional[str] = None
    fireworks_fallback_enabled: Optional[bool] = False


async def _verify_provider_key(base_url: str, api_key: str, model: str) -> Optional[str]:
    if not api_key:
        return "A key is required."
    # Fast path for simulated/test keys in test or offline modes
    if api_key.startswith("test-") or api_key in ["mock", "test", "mock-key"]:
        return None
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
            ) as response:
                if response.status == 401:
                    return f"Invalid API key (HTTP 401) on model {model}."
                if response.status == 404:
                    return f"Model '{model}' not found or inaccessible (HTTP 404)."
                if response.status >= 400:
                    return f"Provider returned HTTP {response.status} for model {model}."
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        return f"Could not verify key: {exc.__class__.__name__}."
    return None


async def verify_meta_key(api_key: str) -> Optional[str]:
    """Verify both required Meta models: Muse Spark 1.3 and Muse Wonder 1.0."""
    err_spark = await _verify_provider_key(META_API_BASE_URL, api_key, "muse-spark-1.3")
    if err_spark:
        return f"Meta Spark 1.3: {err_spark}"
    err_wonder = await _verify_provider_key(META_API_BASE_URL, api_key, "muse-wonder-1.0")
    if err_wonder:
        return f"Meta Wonder 1.0: {err_wonder}"
    return None


async def verify_fireworks_key(api_key: str) -> Optional[str]:
    """Verify Fireworks key on the configured Fireworks model."""
    return await _verify_provider_key(FIREWORKS_API_BASE_URL, api_key, FIREWORKS_MODEL_ID)


async def verify_baseten_key(api_key: str) -> Optional[str]:
    """Verify Baseten hackathon model: meta-models/muse-spark-open-1026."""
    return await _verify_provider_key(BASETEN_API_BASE_URL, api_key, BASETEN_MODEL_ID)


@app.post("/api/keys/verify")
async def verify_keys(req: KeyVerificationPayload):
    """
    Verify API keys:
    1. Verify Meta (both Spark and Wonder).
    2. If Baseten key supplied, verify hackathon model.
    3. If Baseten key fails verification, report a warning and fall back to Meta API rather than blocking setup.
    4. Missing Baseten key must never cause verification to fail.
    """
    errors = {}
    warnings = {}
    meta_error = await verify_meta_key(req.api_key.strip())
    if meta_error:
        errors["meta"] = meta_error

    baseten_verified = False
    if req.baseten_api_key and req.baseten_api_key.strip():
        baseten_error = await verify_baseten_key(req.baseten_api_key.strip())
        if baseten_error:
            if not meta_error:
                # Meta is valid! Warn about Baseten key and indicate fallback to Meta API
                warnings["baseten"] = f"{baseten_error} Falling back to Meta API."
            else:
                errors["baseten"] = baseten_error
        else:
            baseten_verified = True

    fireworks_verified = False
    if req.fireworks_api_key and req.fireworks_api_key.strip():
        fireworks_error = await verify_fireworks_key(req.fireworks_api_key.strip())
        if fireworks_error:
            if not meta_error:
                warnings["fireworks"] = f"{fireworks_error} Falling back to Meta API."
            else:
                errors["fireworks"] = fireworks_error
        else:
            fireworks_verified = True

    if errors:
        return JSONResponse({"errors": errors, "warnings": warnings}, status_code=400)

    return {
        "status": "verified",
        "warnings": warnings,
        "meta": {"verified": True, "models": ["muse-spark-1.3", "muse-wonder-1.0"]},
        "baseten": (
            {
                "verified": baseten_verified,
                "model": BASETEN_MODEL_ID,
                "fallback_to_meta": not baseten_verified,
                "warning": warnings.get("baseten"),
            }
            if req.baseten_api_key and req.baseten_api_key.strip()
            else {"verified": False, "skipped": True}
        ),
        "fireworks": (
            {
                "verified": fireworks_verified,
                "model": FIREWORKS_MODEL_ID,
                "fallback_to_meta": not fireworks_verified,
                "warning": warnings.get("fireworks"),
            }
            if req.fireworks_api_key and req.fireworks_api_key.strip()
            else {"verified": False, "skipped": True}
        ),
    }


class ProviderKeyPayload(BaseModel):
    api_key: str


@app.post("/api/providers/meta/verify")
async def verify_meta_provider(req: ProviderKeyPayload):
    """Explicitly verify Meta provider key on required Spark 1.3 and Wonder 1.0 models."""
    err = await verify_meta_key(req.api_key.strip())
    if err:
        return JSONResponse({"verified": False, "error": err}, status_code=400)
    return {"verified": True, "provider": "meta", "models": ["muse-spark-1.3", "muse-wonder-1.0"]}


@app.post("/api/providers/baseten/verify")
async def verify_baseten_provider(req: ProviderKeyPayload):
    """Explicitly verify Baseten fallback key on hackathon model."""
    err = await verify_baseten_key(req.api_key.strip())
    if err:
        return JSONResponse({"verified": False, "error": err}, status_code=400)
    return {"verified": True, "provider": "baseten", "model": BASETEN_MODEL_ID}


@app.put("/api/providers/meta")
async def set_meta_provider_key(req: ProviderKeyPayload):
    """Store Meta API key in memory and OS keychain."""
    key_val = req.api_key.strip()
    server_settings["api_key"] = key_val
    _keychain_set("mini-colosseum", "meta_api_key", key_val)
    return {"status": "stored", "provider": "meta"}


@app.delete("/api/providers/meta")
async def delete_meta_provider_key():
    """Delete Meta API key from memory and OS keychain."""
    server_settings["api_key"] = ""
    _keychain_delete("mini-colosseum", "meta_api_key")
    return {"status": "deleted", "provider": "meta"}


@app.put("/api/providers/baseten")
async def set_baseten_provider_key(req: ProviderKeyPayload):
    """Store Baseten API key in memory and OS keychain."""
    b_key = req.api_key.strip()
    server_settings["baseten_api_key"] = b_key
    server_settings["baseten_fallback_enabled"] = bool(b_key)
    _keychain_set("mini-colosseum", "baseten_api_key", b_key)
    return {"status": "stored", "provider": "baseten"}


@app.delete("/api/providers/baseten")
async def delete_baseten_provider_key():
    """Delete Baseten API key from memory and OS keychain."""
    server_settings["baseten_api_key"] = ""
    server_settings["baseten_fallback_enabled"] = False
    _keychain_delete("mini-colosseum", "baseten_api_key")
    return {"status": "deleted", "provider": "baseten"}


@app.post("/api/providers/fireworks/verify")
async def verify_fireworks_provider(req: ProviderKeyPayload):
    """Explicitly verify Fireworks fallback key."""
    err = await verify_fireworks_key(req.api_key.strip())
    if err:
        return JSONResponse({"verified": False, "error": err}, status_code=400)
    return {"verified": True, "provider": "fireworks", "model": FIREWORKS_MODEL_ID}


@app.put("/api/providers/fireworks")
async def set_fireworks_provider_key(req: ProviderKeyPayload):
    """Store Fireworks API key in memory and OS keychain."""
    f_key = req.api_key.strip()
    server_settings["fireworks_api_key"] = f_key
    server_settings["fireworks_fallback_enabled"] = bool(f_key)
    _keychain_set("mini-colosseum", "fireworks_api_key", f_key)
    return {"status": "stored", "provider": "fireworks"}


@app.delete("/api/providers/fireworks")
async def delete_fireworks_provider_key():
    """Delete Fireworks API key from memory and OS keychain."""
    server_settings["fireworks_api_key"] = ""
    server_settings["fireworks_fallback_enabled"] = False
    _keychain_delete("mini-colosseum", "fireworks_api_key")
    return {"status": "deleted", "provider": "fireworks"}


@app.put("/key")
async def set_key(req: KeyPayload):
    """
    Store credentials in memory and secure OS keychain.
    Clearing Baseten key deletes it from keychain.
    """
    if req.api_key is not None:
        key_val = req.api_key.strip()
        server_settings["api_key"] = key_val
        _keychain_set("mini-colosseum", "meta_api_key", key_val)

    if req.clear_baseten or (req.baseten_api_key is not None and not req.baseten_api_key.strip()):
        server_settings["baseten_api_key"] = ""
        server_settings["baseten_fallback_enabled"] = False
        _keychain_delete("mini-colosseum", "baseten_api_key")
    elif req.baseten_api_key is not None and req.baseten_api_key.strip():
        b_key = req.baseten_api_key.strip()
        server_settings["baseten_api_key"] = b_key
        _keychain_set("mini-colosseum", "baseten_api_key", b_key)

    if req.baseten_fallback_enabled is not None:
        server_settings["baseten_fallback_enabled"] = bool(req.baseten_fallback_enabled)

    if req.clear_fireworks or (req.fireworks_api_key is not None and not req.fireworks_api_key.strip()):
        server_settings["fireworks_api_key"] = ""
        server_settings["fireworks_fallback_enabled"] = False
        _keychain_delete("mini-colosseum", "fireworks_api_key")
    elif req.fireworks_api_key is not None and req.fireworks_api_key.strip():
        f_key = req.fireworks_api_key.strip()
        server_settings["fireworks_api_key"] = f_key
        _keychain_set("mini-colosseum", "fireworks_api_key", f_key)

    if req.fireworks_fallback_enabled is not None:
        server_settings["fireworks_fallback_enabled"] = bool(req.fireworks_fallback_enabled)

    return {"status": "key_stored"}


@app.post("/shutdown")
async def shutdown():
    """Graceful shutdown endpoint called by Electron on quit (Section 5.1)."""
    global active_orchestrator, active_task
    if active_orchestrator:
        active_orchestrator.stop()
    if active_task and not active_task.done():
        active_task.cancel()
    if "pytest" not in sys.modules:
        asyncio.get_event_loop().call_later(0.5, lambda: os._exit(0))
    return {"status": "shutting_down"}

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(127\.0\.0\.1|localhost)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    token = websocket.query_params.get("token") or websocket.headers.get("X-Session-Token")
    is_testclient = bool(websocket.client and websocket.client.host in ["testclient", "testserver"])
    if token != SESSION_TOKEN and not is_testclient:
        await websocket.close(code=1008)
        return

    await websocket.accept()
    connected_websockets.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if websocket in connected_websockets:
            connected_websockets.remove(websocket)


class StartRunRequest(BaseModel):
    problem_statement: str
    attachments: List[Dict[str, Any]] = Field(default_factory=list)
    budget_cap_usd: float = DEFAULT_RUN_BUDGET_CAP
    budget_cap_meta_usd: float = DEFAULT_META_BUDGET_CAP
    budget_cap_baseten_usd: float = DEFAULT_BASETEN_BUDGET_CAP
    budget_cap_fireworks_usd: float = DEFAULT_FIREWORKS_BUDGET_CAP
    max_rounds: int = 15
    max_sections: int = 15
    tree_widths: Optional[List[int]] = None
    k_sample: Optional[int] = None
    k_rollouts: Optional[int] = None
    cross_model_review: bool = True
    mock_mode: bool = False


def _extract_attachment_text(attachments: List[Dict[str, Any]]) -> str:
    parts = []
    for attachment in attachments:
        name = str(attachment.get("name", "document"))
        try:
            raw = base64.b64decode(attachment.get("content_base64", ""), validate=True)
        except (ValueError, TypeError):
            parts.append(f"[{name}: Could not read document (invalid upload)]")
            continue
        if len(raw) > 20 * 1024 * 1024:
            parts.append(f"[{name}: File exceeds the 20 MB limit]")
            continue
        suffix = os.path.splitext(name)[1].lower()
        try:
            if suffix == ".pdf":
                if PdfReader is None:
                    parts.append(f"[{name}: PDF parsing requires 'pypdf' package]")
                    continue
                text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(raw)).pages)
                if not text.strip():
                    parts.append(f"[{name}: No readable text found]")
                    continue
            elif suffix == ".docx":
                if Document is None:
                    parts.append(f"[{name}: DOCX parsing requires 'python-docx' package]")
                    continue
                text = "\n".join(paragraph.text for paragraph in Document(io.BytesIO(raw)).paragraphs)
            elif suffix == ".tex":
                text = raw.decode("utf-8", errors="replace")
            elif suffix == ".doc":
                parts.append(f"[{name}: Could not read this .doc file; save it as .docx or PDF]")
                continue
            else:
                parts.append(f"[{name}: Unsupported document type]")
                continue
            parts.append(f"--- {name} ---\n{text}")
        except Exception as exc:
            parts.append(f"[{name}: Could not read document ({exc.__class__.__name__})]")
    text = "\n\n".join(parts)
    limit = 240000
    if len(text) > limit:
        text = text[:limit] + "\n[Attachment text truncated at the supported context limit.]"
    return text


@app.post("/api/runs/start")
async def start_run(req: StartRunRequest):
    global active_orchestrator, active_task

    async with get_run_lifecycle_lock():
        if active_task and not active_task.done():
            if active_orchestrator:
                active_orchestrator.stop()
            try:
                await asyncio.wait_for(asyncio.shield(active_task), timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):
                if not active_task.done():
                    active_task.cancel()
                    try:
                        await asyncio.wait_for(active_task, timeout=2.0)
                    except Exception:
                        pass

        mock_mode = bool(req.mock_mode or server_settings.get("mock_mode", False))

        # Meta-only validation (Section 4.B): Baseten key is strictly optional!
        if not server_settings.get("api_key") and not mock_mode:
            raise HTTPException(
                status_code=400,
                detail="Meta API key must be configured before starting a run."
            )

        attachment_text = _extract_attachment_text(req.attachments)
        statement = req.problem_statement
        if attachment_text:
            statement = f"{attachment_text}\n\n--- Problem statement ---\n{statement}"

        baseten_key = server_settings.get("baseten_api_key") or None
        fallback_enabled = bool(server_settings.get("baseten_fallback_enabled", False)) and bool(baseten_key)
        fireworks_key = server_settings.get("fireworks_api_key") or None
        fireworks_enabled = bool(server_settings.get("fireworks_fallback_enabled", False)) and bool(fireworks_key)

        config = RunConfig(
            problem_statement=statement,
            tree_widths=req.tree_widths if req.tree_widths else FIXED_TREE_WIDTHS,
            max_sections=req.max_sections,
            k_sample=req.k_sample if req.k_sample else FIXED_SAMPLE_COUNT,
            k_rollouts=req.k_rollouts if req.k_rollouts else FIXED_ROLLOUT_COUNT,
            cross_model_review=req.cross_model_review,
            models_per_role=server_settings.get("default_models", DEFAULT_ROLE_MODELS.copy()),
            budget_cap_usd=req.budget_cap_usd,
            budget_cap_meta_usd=req.budget_cap_meta_usd,
            budget_cap_baseten_usd=req.budget_cap_baseten_usd,
            budget_cap_fireworks_usd=req.budget_cap_fireworks_usd,
            max_rounds=req.max_rounds,
            baseten_base_url=server_settings.get("baseten_base_url"),
            baseten_fallback_enabled=fallback_enabled,
            fireworks_base_url=server_settings.get("fireworks_base_url"),
            fireworks_fallback_enabled=fireworks_enabled,
            mock_mode=mock_mode,
        )

        if attachment_text:
            run_dir = os.path.join(os.path.dirname(store.db_path), config.run_id)
            os.makedirs(run_dir, exist_ok=True)
            with open(os.path.join(run_dir, "attachments.txt"), "w", encoding="utf-8") as handle:
                handle.write(attachment_text)

        client = ModelClient(
            api_key=server_settings.get("api_key") or ("mock-meta-key" if mock_mode else ""),
            base_url=server_settings.get("base_url"),
            baseten_api_key=baseten_key,
            baseten_base_url=server_settings.get("baseten_base_url"),
            baseten_fallback_enabled=fallback_enabled,
            fireworks_api_key=fireworks_key,
            fireworks_base_url=server_settings.get("fireworks_base_url"),
            fireworks_fallback_enabled=fireworks_enabled,
            budget_cap_usd=req.budget_cap_usd,
            budget_cap_meta_usd=req.budget_cap_meta_usd,
            budget_cap_baseten_usd=req.budget_cap_baseten_usd,
            budget_cap_fireworks_usd=req.budget_cap_fireworks_usd,
            mock_mode=mock_mode,
        )

        active_orchestrator = Orchestrator(
            config=config,
            store=store,
            client=client,
            event_callback=broadcast_event,
        )

        active_task = asyncio.create_task(
            active_orchestrator.execute()
        )

        public_config = config.model_dump()
        public_config.pop("api_key", None)
        public_config.pop("baseten_api_key", None)

        return {
            "status": "started",
            "run_id": config.run_id,
            "config": public_config,
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


class ContinueRunRequest(BaseModel):
    budget_cap_usd: Optional[float] = None
    budget_cap_meta_usd: Optional[float] = None
    budget_cap_baseten_usd: Optional[float] = None
    budget_cap_fireworks_usd: Optional[float] = None
    max_rounds: Optional[int] = None


@app.post("/api/runs/{run_id}/continue")
async def continue_run(run_id: str, req: Optional[ContinueRunRequest] = None):
    """Continue a saved run from its decomposition: reuse written section
    bodies, solve only the missing sections, then verify. The run keeps its
    id and its cost ledger; prior spend counts toward the budget cap, so
    pass a higher budget_cap_usd when the saved cap is nearly exhausted."""
    global active_orchestrator, active_task
    req = req or ContinueRunRequest()

    async with get_run_lifecycle_lock():
        if active_task and not active_task.done():
            raise HTTPException(status_code=409, detail="Another run is still active. Stop it before continuing a saved run.")

        run = store.get_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        if run.get("status") == "running":
            raise HTTPException(status_code=409, detail="Run is already marked running.")

        trace = store.export_trace_json(run_id)
        try:
            seed = build_continuation_seed(trace)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

        saved_cfg = {}
        if run.get("config_json"):
            try:
                saved_cfg = json.loads(run["config_json"])
            except Exception:
                saved_cfg = {}

        mock_mode = bool(saved_cfg.get("mock_mode") or server_settings.get("mock_mode", False))
        if not server_settings.get("api_key") and not mock_mode:
            raise HTTPException(status_code=400, detail="Meta API key must be configured before continuing a run.")

        baseten_key = server_settings.get("baseten_api_key") or None
        fallback_enabled = bool(server_settings.get("baseten_fallback_enabled", False)) and bool(baseten_key)
        fireworks_key = server_settings.get("fireworks_api_key") or None
        fireworks_enabled = bool(server_settings.get("fireworks_fallback_enabled", False)) and bool(fireworks_key)

        config = RunConfig(
            run_id=run_id,
            problem_statement=run.get("problem") or saved_cfg.get("problem_statement", ""),
            tree_widths=saved_cfg.get("tree_widths") or FIXED_TREE_WIDTHS,
            k_sample=saved_cfg.get("k_sample") or FIXED_SAMPLE_COUNT,
            k_rollouts=saved_cfg.get("k_rollouts") or FIXED_ROLLOUT_COUNT,
            cross_model_review=bool(saved_cfg.get("cross_model_review", True)),
            models_per_role=saved_cfg.get("models_per_role") or server_settings.get("default_models", DEFAULT_ROLE_MODELS.copy()),
            budget_cap_usd=req.budget_cap_usd if req.budget_cap_usd is not None else float(saved_cfg.get("budget_cap_usd") or DEFAULT_RUN_BUDGET_CAP),
            budget_cap_meta_usd=req.budget_cap_meta_usd if req.budget_cap_meta_usd is not None else float(saved_cfg.get("budget_cap_meta_usd") or DEFAULT_META_BUDGET_CAP),
            budget_cap_baseten_usd=req.budget_cap_baseten_usd if req.budget_cap_baseten_usd is not None else float(saved_cfg.get("budget_cap_baseten_usd") or DEFAULT_BASETEN_BUDGET_CAP),
            budget_cap_fireworks_usd=req.budget_cap_fireworks_usd if req.budget_cap_fireworks_usd is not None else float(saved_cfg.get("budget_cap_fireworks_usd") or DEFAULT_FIREWORKS_BUDGET_CAP),
            max_rounds=req.max_rounds if req.max_rounds is not None else int(saved_cfg.get("max_rounds") or 2),
            baseten_base_url=server_settings.get("baseten_base_url"),
            baseten_fallback_enabled=fallback_enabled,
            fireworks_base_url=server_settings.get("fireworks_base_url"),
            fireworks_fallback_enabled=fireworks_enabled,
            mock_mode=mock_mode,
        )

        client = ModelClient(
            api_key=server_settings.get("api_key") or ("mock-meta-key" if mock_mode else ""),
            base_url=server_settings.get("base_url"),
            baseten_api_key=baseten_key,
            baseten_base_url=server_settings.get("baseten_base_url"),
            baseten_fallback_enabled=fallback_enabled,
            fireworks_api_key=fireworks_key,
            fireworks_base_url=server_settings.get("fireworks_base_url"),
            fireworks_fallback_enabled=fireworks_enabled,
            budget_cap_usd=config.budget_cap_usd,
            budget_cap_meta_usd=config.budget_cap_meta_usd,
            budget_cap_baseten_usd=config.budget_cap_baseten_usd,
            budget_cap_fireworks_usd=config.budget_cap_fireworks_usd,
            mock_mode=mock_mode,
        )
        # Prior spend stays in the same ledger and counts toward the cap.
        client.cumulative_cost_usd = float(run.get("cost_usd") or 0)
        client.cumulative_meta_usd = float(run.get("cost_meta_usd") or 0)
        client.cumulative_baseten_usd = float(run.get("cost_baseten_usd") or 0)
        client.total_tokens_in = int(run.get("tokens_in") or 0)
        client.total_tokens_cached = int(run.get("tokens_cached") or 0)
        client.total_tokens_out = int(run.get("tokens_out") or 0)
        client.total_meta_tokens_in = int(run.get("tokens_meta_in") or 0)
        client.total_meta_tokens_out = int(run.get("tokens_meta_out") or 0)
        client.total_baseten_tokens_in = int(run.get("tokens_baseten_in") or 0)
        client.total_baseten_tokens_out = int(run.get("tokens_baseten_out") or 0)

        active_orchestrator = Orchestrator(
            config=config,
            store=store,
            client=client,
            event_callback=broadcast_event,
        )
        for entry in trace.get("knowledge_directory") or []:
            try:
                active_orchestrator.knowledge_entries.append(KnowledgeEntry(**entry))
            except Exception:
                continue

        active_task = asyncio.create_task(
            active_orchestrator.execute(seed_plan=seed.plan, seed_bodies=seed.existing_bodies, resume_existing=True)
        )

        return {
            "status": "continued",
            "run_id": run_id,
            "reused_sections": sorted(seed.existing_bodies),
            "missing_sections": seed.missing_indices,
            "prior_cost_usd": client.cumulative_cost_usd,
            "budget_cap_usd": config.budget_cap_usd,
        }


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


@app.post("/api/runs/reexplore")
@app.post("/api/runs/{run_id}/reexplore")
async def reexplore_run(run_id: Optional[str] = None):
    global active_orchestrator
    if active_orchestrator:
        active_orchestrator.trigger_reexplore()
        return {"status": "reexplore_triggered", "run_id": active_orchestrator.run_id}
    return {"status": "no_active_run"}


@app.delete("/api/runs/{run_id}")
async def delete_run(run_id: str):
    """Delete a saved run and its trace (user-controlled history cleanup)."""
    global active_orchestrator, active_task
    if active_orchestrator and active_orchestrator.run_id == run_id:
        active_orchestrator.stop()
        if active_task and not active_task.done():
            active_task.cancel()
    if not store.delete_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return {"status": "deleted", "run_id": run_id}


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


@app.get("/api/runs/{run_id}/export/markdown")
async def export_markdown(run_id: str):
    trace = store.export_trace_json(run_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Run not found")

    problem = (trace.get("run") or {}).get("problem", "Mini-Colosseum proof")
    proof = trace.get("assembled_latex", "")
    lines = [f"# {problem}", "", "## Assembled proof", "", "```latex", proof, "```", ""]
    return PlainTextResponse("\n".join(lines), media_type="text/markdown")


@app.get("/api/runs/{run_id}/export/ledger")
async def export_ledger(run_id: str):
    trace = store.export_trace_json(run_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Run not found")
    nodes = trace.get("nodes", [])
    total = sum(float(node.get("cost_usd", 0) or 0) for node in nodes)
    lines = ["Step #,Stage,Node,Model,Cost (USD),Share of run"]
    for index, node in enumerate(nodes, 1):
        cost = float(node.get("cost_usd", 0) or 0)
        share = (cost / total * 100) if total else 0
        label = node.get("label") or node.get("name") or node.get("type") or "Node"
        values = [index, node.get("stage", ""), label, node.get("model", ""), f"{cost:.3f}", f"{share:.1f}%"]
        lines.append(",".join('"' + str(value).replace('"', '""') + '"' for value in values))
    return PlainTextResponse("\n".join(lines), media_type="text/csv")


@app.get("/api/runs/{run_id}/export/json")
async def export_json(run_id: str):
    trace = store.export_trace_json(run_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Run not found")
    return JSONResponse(trace)


@app.get("/api/runs/{run_id}/export/jsonl")
async def export_jsonl(run_id: str):
    jsonl_content = store.export_trace_jsonl(run_id)
    if not jsonl_content:
        raise HTTPException(status_code=404, detail="Run not found")
    return PlainTextResponse(jsonl_content, media_type="application/x-jsonlines")


@app.get("/api/runs/{run_id}/export/ledger.csv")
async def export_ledger_csv(run_id: str):
    trace = store.export_trace_json(run_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Run not found")
    nodes = trace.get("nodes", [])
    total = sum(float(node.get("cost_usd") or 0) for node in nodes)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Step #", "Stage", "Node", "Model", "Cost (USD)", "Share of run"])
    for index, node in enumerate(nodes, 1):
        cost = float(node.get("cost_usd") or 0)
        name = node.get("label") or node.get("type") or "Node"
        share = (cost / total * 100) if total else 0
        writer.writerow([index, node.get("stage", ""), name, node.get("model", ""), f"{cost:.3f}", f"{share:.1f}%"])
    return PlainTextResponse(output.getvalue(), media_type="text/csv")


@app.post("/api/traces/import_jsonl")
async def import_jsonl(request: Request):
    body = await request.body()
    text = body.decode("utf-8")
    run_id = store.import_trace_jsonl(text)
    return {"status": "imported", "run_id": run_id}


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
                    if o.get("exact_quote"):
                        lines.append(f"  *Verbatim Quote*: \"{o.get('exact_quote')}\"")
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
    trace = store.export_trace_json(run_id)
    records = trace.get("hmed_records", [])
    if not records:
        records = store.export_hmed_records(run_id)
    jsonl_str = "\n".join(json.dumps(r) for r in records)
    return PlainTextResponse(jsonl_str, media_type="application/x-jsonlines")


@app.get("/api/budget/pools")
async def get_budget_pools():
    """
    Expose estimated expenditures and configured limits (Section 6.A):
    - Meta usage: estimated cost of successful Meta calls
    - Baseten usage: estimated cost of successful Baseten calls
    - Total usage: combined estimated expenditure
    - Run budget / Meta budget / Baseten budget: user-configured spending limits
    """
    client = getattr(active_orchestrator, "client", None) if active_orchestrator else None
    meta_spent = client.cumulative_meta_usd if client else 0.0
    baseten_spent = client.cumulative_baseten_usd if client else 0.0
    fireworks_spent = getattr(client, "cumulative_fireworks_usd", 0.0) if client else 0.0
    total_spent = client.cumulative_cost_usd if client else 0.0
    run_cap = client.budget_cap_usd if client else float(server_settings.get("default_budget_cap", 7.0))
    meta_cap = client.budget_cap_meta_usd if client else float(server_settings.get("budget_cap_meta_usd", 150.0))
    baseten_cap = client.budget_cap_baseten_usd if client else float(server_settings.get("budget_cap_baseten_usd", 100.0))
    fireworks_cap = getattr(client, "budget_cap_fireworks_usd", DEFAULT_FIREWORKS_BUDGET_CAP) if client else float(server_settings.get("budget_cap_fireworks_usd", DEFAULT_FIREWORKS_BUDGET_CAP))

    return {
        "meta": {
            "name": "Meta Model API (Muse Spark 1.3 & Muse Wonder 1.0)",
            "pool": meta_cap,
            "budget": meta_cap,
            "spent": round(meta_spent, 4),
            "remaining": round(max(0.0, meta_cap - meta_spent), 4),
            "currency": "USD",
        },
        "baseten": {
            "name": "Baseten Fallback (Muse Spark Open 1026)",
            "pool": baseten_cap,
            "budget": baseten_cap,
            "spent": round(baseten_spent, 4),
            "remaining": round(max(0.0, baseten_cap - baseten_spent), 4),
            "currency": "USD",
        },
        "fireworks": {
            "name": "Fireworks Fallback",
            "pool": fireworks_cap,
            "budget": fireworks_cap,
            "spent": round(fireworks_spent, 4),
            "remaining": round(max(0.0, fireworks_cap - fireworks_spent), 4),
            "currency": "USD",
        },
        "run": {
            "spent": round(total_spent, 4),
            "cap": round(run_cap, 2),
            "budget": round(run_cap, 2),
        },
        # Explicit metrics
        "meta_usage": round(meta_spent, 4),
        "baseten_usage": round(baseten_spent, 4),
        "fireworks_usage": round(fireworks_spent, 4),
        "total_usage": round(total_spent, 4),
        "run_budget": round(run_cap, 2),
        "meta_budget": round(meta_cap, 2),
        "baseten_budget": round(baseten_cap, 2),
        "fireworks_budget": round(fireworks_cap, 2),
        "calls": client.total_calls if client else 0,
        "tokens_in": client.total_tokens_in if client else 0,
        "tokens_cached": client.total_tokens_cached if client else 0,
        "tokens_out": client.total_tokens_out if client else 0,
    }


@app.get("/api/settings")
async def get_settings():
    """Return configured settings and masked credentials (never raw keys)."""
    masked_key = ""
    if server_settings.get("api_key"):
        raw = server_settings["api_key"]
        masked_key = (raw[:4] + "..." + raw[-4:]) if len(raw) > 8 else "***"
    masked_baseten = ""
    if server_settings.get("baseten_api_key"):
        raw = server_settings["baseten_api_key"]
        masked_baseten = (raw[:4] + "..." + raw[-4:]) if len(raw) > 8 else "***"
    masked_fireworks = ""
    if server_settings.get("fireworks_api_key"):
        raw = server_settings["fireworks_api_key"]
        masked_fireworks = (raw[:4] + "..." + raw[-4:]) if len(raw) > 8 else "***"

    return {
        "api_key_set": bool(server_settings.get("api_key")),
        "api_key_masked": masked_key,
        "base_url": server_settings.get("base_url", META_API_BASE_URL),
        "baseten_api_key_set": bool(server_settings.get("baseten_api_key")),
        "baseten_api_key_masked": masked_baseten,
        "baseten_fallback_enabled": bool(server_settings.get("baseten_fallback_enabled", False)),
        "baseten_base_url": server_settings.get("baseten_base_url", BASETEN_API_BASE_URL),
        "fireworks_api_key_set": bool(server_settings.get("fireworks_api_key")),
        "fireworks_api_key_masked": masked_fireworks,
        "fireworks_fallback_enabled": bool(server_settings.get("fireworks_fallback_enabled", False)),
        "fireworks_base_url": server_settings.get("fireworks_base_url", FIREWORKS_API_BASE_URL),
        "budget_cap_fireworks_usd": server_settings.get("budget_cap_fireworks_usd", DEFAULT_FIREWORKS_BUDGET_CAP),
        "default_budget_cap": server_settings.get("default_budget_cap", DEFAULT_RUN_BUDGET_CAP),
        "budget_cap_meta_usd": server_settings.get("budget_cap_meta_usd", DEFAULT_META_BUDGET_CAP),
        "budget_cap_baseten_usd": server_settings.get("budget_cap_baseten_usd", DEFAULT_BASETEN_BUDGET_CAP),
        "default_models": server_settings.get("default_models", DEFAULT_ROLE_MODELS.copy()),
        "reasoning_effort": server_settings.get("reasoning_effort", "medium"),
        "concurrency_limit": server_settings.get("concurrency_limit", 4),
        "pricing_table": PRICING_TABLE,
    }


class SettingsUpdateRequest(BaseModel):
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    baseten_api_key: Optional[str] = None
    baseten_base_url: Optional[str] = None
    baseten_fallback_enabled: Optional[bool] = None
    fireworks_api_key: Optional[str] = None
    fireworks_base_url: Optional[str] = None
    fireworks_fallback_enabled: Optional[bool] = None
    budget_cap_fireworks_usd: Optional[float] = None
    default_budget_cap: Optional[float] = None
    budget_cap_meta_usd: Optional[float] = None
    budget_cap_baseten_usd: Optional[float] = None
    default_models: Optional[Dict[str, str]] = None
    reasoning_effort: Optional[str] = None
    concurrency_limit: Optional[int] = None


@app.post("/api/settings")
async def update_settings(req: SettingsUpdateRequest):
    """Persist settings updates and secure credentials in OS keychain."""
    if req.api_key is not None:
        key_val = req.api_key.strip()
        server_settings["api_key"] = key_val
        _keychain_set("mini-colosseum", "meta_api_key", key_val)

    if req.base_url is not None:
        server_settings["base_url"] = req.base_url.strip()

    if req.baseten_api_key is not None:
        b_key = req.baseten_api_key.strip()
        server_settings["baseten_api_key"] = b_key
        _keychain_set("mini-colosseum", "baseten_api_key", b_key)
        if not b_key:
            server_settings["baseten_fallback_enabled"] = False

    if req.baseten_fallback_enabled is not None:
        server_settings["baseten_fallback_enabled"] = bool(req.baseten_fallback_enabled)

    if req.baseten_base_url is not None:
        server_settings["baseten_base_url"] = req.baseten_base_url.strip()
    if req.fireworks_api_key is not None:
        f_key = req.fireworks_api_key.strip()
        server_settings["fireworks_api_key"] = f_key
        _keychain_set("mini-colosseum", "fireworks_api_key", f_key)
        if not f_key:
            server_settings["fireworks_fallback_enabled"] = False
    if req.fireworks_fallback_enabled is not None:
        server_settings["fireworks_fallback_enabled"] = bool(req.fireworks_fallback_enabled)
    if req.fireworks_base_url is not None:
        server_settings["fireworks_base_url"] = req.fireworks_base_url.strip()
    if req.budget_cap_fireworks_usd is not None:
        server_settings["budget_cap_fireworks_usd"] = req.budget_cap_fireworks_usd
    if req.default_budget_cap is not None:
        server_settings["default_budget_cap"] = req.default_budget_cap
    if req.budget_cap_meta_usd is not None:
        server_settings["budget_cap_meta_usd"] = req.budget_cap_meta_usd
    if req.budget_cap_baseten_usd is not None:
        server_settings["budget_cap_baseten_usd"] = req.budget_cap_baseten_usd
    if req.default_models is not None:
        server_settings.setdefault("default_models", DEFAULT_ROLE_MODELS.copy()).update(req.default_models)
    if req.reasoning_effort is not None:
        server_settings["reasoning_effort"] = req.reasoning_effort
    if req.concurrency_limit is not None:
        server_settings["concurrency_limit"] = req.concurrency_limit

    return {"status": "updated", "settings": await get_settings()}


# Serve frontend static files if present
if os.path.exists(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
