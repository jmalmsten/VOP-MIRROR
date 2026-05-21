#!/bin/bash
# VOP Alignment Tool Launcher
#
# Runs CaliTools/vop_setup_align.py against the VOP's main venv 
# (which has pygame/moderngl/numpy already installed - no separate 
# CaliTools venv needed). 
#
# IMPORTANT: detaches the alignment tool from the calling shell so 
# that the tool's `sudo chvt 7` call (which is what gives it the 
# console for KMSDRM) doesn't yank the controlling VT out from under 
# an SSH session. Without this detachment, running the alignment tool 
# over SSH instantly kills the SSH connection mid-startup, leaving 
# the user with no way to send the 'q' quit key.

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
###########################################################################

# Resolve the directory this script lives in (CaliTools/) and the 
# VOP root one level up. Doing it this way means the script keeps 
# working if you move the whole VOP tree somewhere else, or if you 
# call it from a different working directory.
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)
VOP_ROOT=$(cd -- "$SCRIPT_DIR/.." &> /dev/null && pwd)

# The venv lives at VOP_ROOT/venv, not inside CaliTools. The main VOP 
# venv already has numpy/pygame/moderngl, so we just borrow it rather 
# than creating a duplicate environment for CaliTools.
PYTHON_BIN="$VOP_ROOT/venv/bin/python"
APP_SCRIPT="$SCRIPT_DIR/vop_setup_align.py"

# Log file: lives next to the script so it's easy to find. Truncated 
# on each launch (>) rather than appended (>>) so you only ever see 
# the current run's output - keeps it useful for debugging without 
# growing forever.
LOG_FILE="$SCRIPT_DIR/alignment.log"

# Sanity checks - friendlier failure than a stack trace.
if [ ! -f "$PYTHON_BIN" ]; then
    echo "Error: VOP venv not found at $PYTHON_BIN"
    echo "Did you run deploy_vop.sh on this Pi?"
    exit 1
fi
if [ ! -f "$APP_SCRIPT" ]; then
    echo "Error: alignment script not found at $APP_SCRIPT"
    exit 1
fi

echo "Stopping the main VOP service so KMSDRM is free..."
# The alignment tool needs exclusive KMSDRM access. The main VOP 
# engine daemon also holds KMSDRM whenever it's running, so the 
# two cannot coexist. Stop the service first; the user can start 
# it again afterwards with `sudo systemctl start vop`.
sudo systemctl stop vop

echo "Launching alignment tool detached from this SSH session..."
echo "  Log:   $LOG_FILE"
echo "  Quit:  press 'q' on the Pi's attached keyboard (NOT over SSH)"
echo ""
echo "Note: this SSH session will stay alive. The tool is running on VT7."
echo "After you quit the tool, restart the VOP service with:"
echo "  sudo systemctl start vop"

# The detachment recipe:
#   - setsid: starts the process in a new session, so it has no 
#     controlling terminal at all. This is what actually prevents 
#     the chvt-kicks-SSH problem - if the process has no controlling 
#     TTY, switching VTs can't kill an SSH session that doesn't 
#     share one with it.
#   - nohup: ignore SIGHUP, so if SSH does drop, the tool keeps 
#     running rather than dying with the parent shell.
#   - </dev/null: detach stdin so the process can't try to read 
#     from a TTY that's about to go away.
#   - >"$LOG_FILE" 2>&1: redirect both stdout and stderr to the log.
#   - &: background, so this script returns immediately and the 
#     SSH session gets its prompt back.
setsid nohup "$PYTHON_BIN" "$APP_SCRIPT" </dev/null >"$LOG_FILE" 2>&1 &

# Capture the PID and report it so the user can `kill` it from 
# SSH if they ever can't get to the physical keyboard.
ALIGN_PID=$!
echo ""
echo "Alignment tool PID: $ALIGN_PID"
echo "To kill from SSH:"
echo "  sudo kill $ALIGN_PID         # by PID - use 'kill', NOT 'pkill'"
echo "  sudo pkill -f vop_setup_align  # by pattern - safer if you forget the PID"