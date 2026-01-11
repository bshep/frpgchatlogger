#!/bin/bash
# set -euo pipefail

echo "Starting development servers..."

# --- Backend Server ---
echo "Starting backend development server..."
(
    cd backend
    if [ ! -d "venv" ]; then
        echo "Creating backend virtual environment..."
        python3 -m venv venv
    fi
    source venv/bin/activate
    pip install -r requirements.txt
    uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
    BACKEND_PID=$!
    echo "Backend server started with PID: $BACKEND_PID"
) &

# --- Frontend Server ---
echo "Starting frontend development server..."
(
    cd frontend
    npm install
    npm run dev &
    FRONTEND_PID=$!
    echo "Frontend server started with PID: $FRONTEND_PID"
) &

# Store PIDs of background processes
PIDS=($BACKEND_PID $FRONTEND_PID)

# Wait for both processes to start (give them a moment)
sleep 5

echo "Development servers started. Press Ctrl+C to stop both."

# Function to kill background processes on exit
cleanup() {
    echo "Stopping development servers..."
    for pid in "${PIDS[@]}"; do
        if kill "$pid" 2>/dev/null; then
            echo "Killed process $pid"
        fi
    done
    wait # Wait for all background jobs to finish
    echo "Development servers stopped."
}

# Trap Ctrl+C (SIGINT) and call cleanup function
trap cleanup SIGINT SIGTERM

# Keep the script running until interrupted
wait "${PIDS[@]}"

cleanup
