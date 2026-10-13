#!/usr/bin/env bash
# ==============================================================================
# From Spoken Words to Countable Data: Meet ATLAS
# A fast, private way to organize transcripts, count patterns, and trace every quote right on your laptop.
# 1-Click Desktop Launcher for macOS • 100% Local & Offline
# ==============================================================================

set -e

# Change to the script's directory
cd "$(dirname "$0")"

echo "=================================================================="
echo " From Spoken Words to Countable Data: Meet ATLAS"
echo " A fast, private way to organize transcripts, count patterns, and trace every quote right on your laptop."
echo " 100% Local Processing • Zero External Network Traffic"
echo "=================================================================="

# Check for Python 3.10+
if ! command -v python3 &> /dev/null; then
    echo "ERROR: Python 3 was not found on your system."
    echo "Please download and install Python 3.10 or higher from:"
    echo "https://www.python.org/downloads/"
    read -p "Press [Enter] to exit..."
    exit 1
fi

# Ensure Python version is >= 3.10
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(python3 -c 'import sys; print(sys.version_info.major)')
PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info.minor)')

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]); then
    echo "ERROR: ATLAS requires Python 3.10+, but found Python $PYTHON_VERSION."
    echo "Please update your Python installation from https://www.python.org/downloads/"
    read -p "Press [Enter] to exit..."
    exit 1
fi

# Create local virtual environment if not present
if [ ! -d ".venv" ]; then
    echo "--> Creating local isolated environment (.venv)..."
    python3 -m venv .venv
    echo "--> Installing dependencies into local environment..."
    .venv/bin/pip install --upgrade pip --quiet
    .venv/bin/pip install -r requirements.txt --quiet
    echo "--> Environment ready."
fi

# Launch the Streamlit application
echo "--> Launching ATLAS Desktop Interface in your browser..."
echo "--> Press Ctrl+C in this terminal window to stop the application."
echo "=================================================================="

.venv/bin/streamlit run app.py --server.headless=false --browser.serverAddress="localhost"
