#!/bin/bash
set -e

# --- Configuration ---
SESSION_NAME="frpg-dev"

# --- Pre-checks ---
if ! command -v tmux &> /dev/null; then
    echo "tmux is not installed. Please install it to use this script."
    echo "On Debian/Ubuntu: sudo apt-get install tmux"
    echo "On macOS (with Homebrew): brew install tmux"
    exit 1
fi

if tmux has-session -t "$SESSION_NAME" 2>/dev/null; then
    echo "A tmux session named '$SESSION_NAME' is already running."
    read -p "Attach to it? (y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        tmux attach-session -t "$SESSION_NAME"
    else
        echo "To kill the existing session, run: tmux kill-session -t $SESSION_NAME"
    fi
    exit 0
fi

# --- Pre-run setup ---
echo "Ensuring backend virtual environment and dependencies are set up..."
(
    cd backend
    if [ ! -d "venv" ]; then
        echo "Creating backend virtual environment..."
        python3 -m venv venv
    fi
    source venv/bin/activate
    pip install -r requirements.txt
)

echo "Ensuring frontend dependencies are set up..."
(
    cd frontend
    npm install
)

# --- Create and configure tmux session ---
echo "Creating new tmux session: $SESSION_NAME"

# Start a new detached session and name the first window
tmux new-session -d -s "$SESSION_NAME" -n "Backend"

# Send the backend command to the first pane (window 0, pane 0)
tmux send-keys -t "$SESSION_NAME:0.0" "echo '--- Starting Backend Server ---'; cd backend && source venv/bin/activate && export ENCRYPTION_KEY="T-XKIzPJkqPyFMWPlokCnq5msDRZHtKkcmuKPj9XdOI=" && export DEV_MODE_BYPASS_AUTH="true" && uvicorn main:app --reload --host 0.0.0.0 --port 8000" C-m

# Split the window vertically to create a new pane
tmux split-window -v

# Send the frontend command to the new pane (window 0, pane 1)
tmux send-keys -t "$SESSION_NAME:0.1" "echo '--- Starting Frontend Server ---'; cd frontend && npm run dev" C-m

# Split the window horizontally to create a new pane
tmux split-window -h

# Send the scheduler command to the new pane (window 0, pane 1)
tmux send-keys -t "$SESSION_NAME:0.2" "echo '--- Starting Scheduler ---'; cd backend && source venv/bin/activate && export ENCRYPTION_KEY="T-XKIzPJkqPyFMWPlokCnq5msDRZHtKkcmuKPj9XdOI=" && python3 scheduler.py" C-m


# Set a more balanced layout
tmux select-layout even-vertical

# Select the top pane to start
tmux select-pane -t "$SESSION_NAME:0.0"

echo "tmux session '$SESSION_NAME' created with a split-screen layout."
echo "Attaching to session now... (To detach: Ctrl+B, then D)"
echo "To kill all servers, run: tmux kill-session -t $SESSION_NAME"
sleep 1

# Attach to the session
tmux attach-session -t "$SESSION_NAME"

echo
echo "tmux session has ended."