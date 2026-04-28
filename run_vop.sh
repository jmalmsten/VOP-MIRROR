#!/bin/bash
# VOP Launcher Script
# This script bypasses manual venv activation by calling the local python binary directly.

#
###########################################################################
#
#                                   VOP
#                       Copyright (C) 2025  jmalmsten
#
#     This program is free software: you can redistribute it and/or modify 
#     it under the terms of the GNU Affero General Public License as 
#     published by the Free Software Foundation, either version 3 of the 
#     License, or (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful, but 
#     WITHOUT ANY WARRANTY; without even the implied warranty of 
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU 
#     Affero General Public License for more details.
#
#     You should have received a copy of the GNU Affero General Public 
#     License along with this program.  If not, see 
#     <http://www.gnu.org/licenses/>.
#
#     Source code for this application can be found at 
#     https://codeberg.org/jmalmsten-com/VOP
#
###########################################################################

# 0. Clear the terminal of junk
clear

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
