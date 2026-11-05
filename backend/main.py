"""
Mini-Colosseum Backend Entry Point.
Starts the FastAPI server with Uvicorn on localhost.
Implements Section 5.1:
- Binds to 127.0.0.1 on specified or free port
- Prints single JSON line to stdout: {"port": ..., "token": ..., "status": "ready"}
"""

import sys
import os
import json
import socket
import argparse
import uvicorn

# When PyInstaller launches this file as the application entry point, the
# backend package directory is not necessarily on sys.path.
if __package__ in (None, ""):
    bundle_root = getattr(sys, "_MEIPASS", None)
    source_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, bundle_root or source_root)

from backend.server import app, set_session_token, get_session_token


def find_free_port() -> int:
    """Find a random available loopback port (Section 5.1)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run_server(host: str = "127.0.0.1", port: int = 8765, token: str = None):
    if port == 0:
        port = find_free_port()
    if token:
        set_session_token(token)

    current_token = get_session_token()

    # Section 5.1: The backend prints the port as one JSON line
    ready_line = json.dumps({"port": port, "token": current_token, "status": "ready"})
    print(ready_line, flush=True)

    print(f"=======================================================", flush=True)
    print(f" MINI-COLOSSEUM RESEARCH HARNESS BACKEND", flush=True)
    print(f" Listening on http://{host}:{port}", flush=True)
    print(f" WebSocket Event Stream on ws://{host}:{port}/ws", flush=True)
    print(f" Session Token: {current_token[:6]}...{current_token[-6:]}", flush=True)
    print(f"=======================================================", flush=True)

    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Mini-Colosseum Backend")
    parser.add_argument("port", nargs="?", default="8765", help="Port number or 0 for random free port")
    parser.add_argument("--token", "-t", default=None, help="Session security token")
    parser.add_argument("--frontend-dir", default=None, help="Path to frontend static files directory")
    args = parser.parse_args()

    if args.frontend_dir:
        os.environ["MINI_COLOSSEUM_FRONTEND_DIR"] = args.frontend_dir

    port_num = int(args.port) if str(args.port).isdigit() else 8765
    run_server(host="127.0.0.1", port=port_num, token=args.token)
