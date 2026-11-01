#!/usr/bin/env bash
# ==============================================================================
# Mini-Colosseum One-Command Launcher
# Launches the Python research orchestrator and opens the scientific desktop UI
# ==============================================================================

set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

echo "================================================================="
echo " MINI-COLOSSEUM: Research-Harness Workbench on Meta Muse Models"
echo " Implementing Stellar Colosseum (arXiv:2609.15983)"
echo "================================================================="

# Check Python3
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not found."
    exit 1
fi

PORT=8765
URL="http://127.0.0.1:${PORT}"

# Ensure fixtures exist
if [ ! -f "backend/fixtures/fixture_clean_success.json" ]; then
    echo "Generating benchmark fixtures..."
    python3 -m backend.generate_fixtures
fi

# Kill any existing process on port 8765
lsof -ti :$PORT | xargs kill -9 2>/dev/null || true

echo "Starting Python backend orchestrator on ${URL}..."
python3 -m backend.main $PORT &
BACKEND_PID=$!

# Trap signals for clean exit
cleanup() {
    echo ""
    echo "Shutting down Mini-Colosseum backend (PID: $BACKEND_PID)..."
    kill -TERM "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
    echo "Shutdown complete."
}
trap cleanup EXIT INT TERM

# Wait for server to become responsive
echo "Waiting for orchestrator..."
MAX_ATTEMPTS=25
COUNT=0
READY=0
while [ $COUNT -lt $MAX_ATTEMPTS ]; do
    if curl -s -f "${URL}/api/settings" >/dev/null 2>&1; then
        READY=1
        break
    fi
    sleep 0.4
    COUNT=$((COUNT+1))
done

if [ $READY -eq 1 ]; then
    echo "Backend is ready!"
    echo "Launching Mini-Colosseum Desktop Interface..."
    
    # Try launching in desktop app mode
    if [ "$(uname)" == "Darwin" ]; then
        if [ -d "/Applications/Google Chrome.app" ]; then
            open -na "Google Chrome" --args --app="${URL}" --window-size=1340,880
        else
            open "${URL}"
        fi
    elif [ "$(uname)" == "Linux" ]; then
        if command -v google-chrome &> /dev/null; then
            google-chrome --app="${URL}" &
        else
            xdg-open "${URL}" &
        fi
    else
        start "${URL}"
    fi

    echo ""
    echo "Mini-Colosseum is running. Press Ctrl+C in this terminal to stop."
    # Wait for the backend process
    wait $BACKEND_PID
else
    echo "Error: Orchestrator failed to initialize on ${URL}."
    exit 1
fi
