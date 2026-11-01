"""
Mini-Colosseum Backend Entry Point.
Starts the FastAPI server with Uvicorn on localhost:8765.
"""

import sys
import uvicorn
from backend.server import app

def run_server(host: str = "127.0.0.1", port: int = 8765):
    print(f"=======================================================")
    print(f" MINI-COLOSSEUM RESEARCH HARNESS BACKEND")
    print(f" Listening on http://{host}:{port}")
    print(f" WebSocket Event Stream on ws://{host}:{port}/ws")
    print(f"=======================================================")
    uvicorn.run(app, host=host, port=port, log_level="info")

if __name__ == "__main__":
    host = "127.0.0.1"
    port = 8765
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    run_server(host=host, port=port)
