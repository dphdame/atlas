#!/usr/bin/env bash
# ==============================================================================
# ATLAS - Automated Text-to-Ledger Actuarial Synthesis
# Local desktop launcher for macOS / Linux
#
# Usage:
#   ./run.command               provision .venv if needed, verify, launch ATLAS
#   ./run.command --check-only  provision .venv if needed, verify, exit 0 (no launch)
#   ATLAS_NO_LAUNCH=1 ./run.command   same as --check-only
#
# Dependencies are (re)installed whenever .venv is missing or the SHA-256 of
# requirements.txt differs from .venv/.atlas_deps.sha256. The marker is written
# only after pip succeeds; a failed install removes the incomplete .venv.
# If the core-import check fails (damaged packages that pip still reports as
# satisfied), .venv is deleted and rebuilt once; a second failure removes it.
# ==============================================================================

set -u

# Change to the script's directory
cd "$(dirname "$0")" || exit 1

CHECK_ONLY=0
for arg in "$@"; do
    if [ "$arg" = "--check-only" ]; then
        CHECK_ONLY=1
    fi
done
if [ "${ATLAS_NO_LAUNCH:-}" = "1" ]; then
    CHECK_ONLY=1
fi

VENV_PY=".venv/bin/python"
MARKER=".venv/.atlas_deps.sha256"
IMPORT_CHECK="import streamlit, pandas, yaml, openpyxl, sklearn, altair, docx, pyarrow"

fail() {
    echo "ERROR: $1" >&2
    if [ "$CHECK_ONLY" -eq 0 ] && [ -t 0 ]; then
        read -r -p "Press [Enter] to exit..." _
    fi
    exit 1
}

echo "=================================================================="
echo " ATLAS - Automated Text-to-Ledger Actuarial Synthesis"
echo " Local qualitative coding and auditable frequency workbench"
echo "=================================================================="

# Check for Python 3.10+
if ! command -v python3 > /dev/null 2>&1; then
    fail "Python 3 was not found on your system. Install Python 3.10 or higher from https://www.python.org/downloads/"
fi

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    fail "ATLAS requires Python 3.10+, but found Python $PYTHON_VERSION. Update from https://www.python.org/downloads/"
fi

REQ_HASH=$(python3 -c 'import hashlib; print(hashlib.sha256(open("requirements.txt", "rb").read()).hexdigest())') \
    || fail "Could not read requirements.txt"

OLD_HASH=""
if [ -f "$MARKER" ]; then
    OLD_HASH=$(tr -d '[:space:]' < "$MARKER")
fi

provision() {
    # An interpreter that exists but cannot run (damaged or not a program) is rebuilt, never handed to pip.
    if ! "$VENV_PY" -c "import sys" > /dev/null 2>&1; then
        if [ -e "$VENV_PY" ]; then
            echo "--> Existing .venv interpreter is unusable; rebuilding it..."
        fi
        rm -rf .venv
        echo "--> Creating local isolated environment (.venv)..."
        if ! python3 -m venv .venv; then
            rm -rf .venv
            fail "Could not create the .venv virtual environment."
        fi
    fi
    echo "--> Installing dependencies into local environment..."
    if ! "$VENV_PY" -m pip install --disable-pip-version-check -r requirements.txt --quiet; then
        rm -rf .venv
        fail "Dependency installation failed; the incomplete .venv was removed. Check your connection and run again."
    fi
    echo "$REQ_HASH" > "$MARKER"
    echo "--> Environment ready."
}

if [ ! -x "$VENV_PY" ] || [ "$OLD_HASH" != "$REQ_HASH" ]; then
    provision
fi

if ! "$VENV_PY" -c "$IMPORT_CHECK"; then
    echo "--> Core imports failed in .venv; rebuilding it from scratch (one attempt)..."
    rm -rf .venv
    provision
    if ! "$VENV_PY" -c "$IMPORT_CHECK"; then
        rm -rf .venv
        fail "Core imports still fail after rebuilding .venv; it was removed. Check your Python installation and run again."
    fi
fi
echo "--> Environment verified (Python, .venv, core imports)."

if [ "$CHECK_ONLY" -eq 1 ]; then
    echo "ATLAS check-only: OK (application not launched)."
    exit 0
fi

# Launch the Streamlit application
echo "--> Launching ATLAS Desktop Interface in your browser..."
echo "--> Press Ctrl+C in this terminal window to stop the application."
echo "=================================================================="

exec "$VENV_PY" -m streamlit run app.py --server.headless=false --server.address="localhost" --browser.serverAddress="localhost" --browser.gatherUsageStats=false
