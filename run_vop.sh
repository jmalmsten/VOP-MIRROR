#!/bin/bash
# VOP Launcher Script
# This script bypasses manual venv activation by calling the local python binary directly.

# 1. Determine the absolute path of the directory containing this script.
# This prevents path errors if you run the script from your home folder or root.
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)

# 2. Define the path to the Python interpreter inside the virtual environment.
# Executing this binary specifically loads the venv's site-packages.
PYTHON_BIN="$SCRIPT_DIR/venv/bin/python"

# 3. Define the path to the main application script.
APP_SCRIPT="$SCRIPT_DIR/vop.py"

# 4. Check if the python binary exists before trying to run it.
if [ ! -f "$PYTHON_BIN" ]; then
    echo "Error: Virtual environment not found at $PYTHON_BIN"
    exit 1
fi

# 5. Launch the application.
# 'exec' replaces the shell process with the Python process.
# "$@" passes any arguments from this script (like --debug) into vop.py.
echo "Starting VOP Server..."
exec "$PYTHON_BIN" "$APP_SCRIPT" "$@"
