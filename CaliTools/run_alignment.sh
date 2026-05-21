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

# ---------------------------------------------------------
# CLEAR ZOMBIE ALIGNMENT PROCESSES
# ---------------------------------------------------------
# Previous runs may have left an alignment tool detached and running 
# (that's exactly what setsid+nohup do - survive their parent shell).
# If one is still alive it'll be holding both KMSDRM and the camera 
# lock, which makes the new instance fail in confusing ways:
#   - "Device or resource busy" from libcamera (camera taken)
#   - new pygame.set_mode() hangs or fails (KMSDRM taken)
#   - operator sees stale alignment targets on the screen and thinks 
#     the new tool started but is broken
# 
# Killing first makes this script safe to re-run without thinking 
# about cleanup. -9 (SIGKILL) is used rather than the polite SIGTERM 
# because we don't care about clean shutdown of the OLD instance - 
# its job is over - and a stuck signal handler shouldn't be able 
# to block the new instance from starting.
echo "Clearing any leftover alignment processes..."
sudo pkill -9 -f vop_setup_align 2>/dev/null
sudo pkill -9 -f rpicam-vid       2>/dev/null

# Give the kernel a moment to release the camera and KMSDRM after 
# the SIGKILL. Without this brief sleep, the new rpicam-vid can 
# start before the V4L2 device has fully released, and we hit 
# "Device or resource busy" all over again.
sleep 1

echo "Launching alignment tool detached from this SSH session..."
echo "  Log:   $LOG_FILE"
echo "  Quit:  press 'q' on the Pi's attached keyboard (NOT over SSH)"
echo ""
echo "Note: this SSH session will stay alive. The tool is running on VT7."
echo "After you quit the tool, restart the VOP service with:"
echo "  sudo systemctl start vop"

# We use plain nohup + & here, NOT setsid. Earlier versions of 
# this script used `setsid nohup ... &` to fully detach the new 
# process into its own session - but on some Pi OS / SDL combos 
# that disturbed the SSH pty's terminal flags (ONLCR specifically), 
# leaving the user's shell with newlines that no longer carriage-return. 
# Symptoms: text marches diagonally across the screen, input is 
# invisible, only `reset` recovers the terminal.
# 
# The session-detach we actually need (so SIGHUP from SSH disconnect 
# doesn't kill the alignment tool) is now done by the Python script 
# itself via os.setsid() before it does anything else. That way the 
# shell never touches its own session state, and the alignment tool 
# still ends up detached from the SSH pty.
nohup "$PYTHON_BIN" "$APP_SCRIPT" </dev/null >"$LOG_FILE" 2>&1 &

# Capture the PID and report it so the user can `kill` it from 
# SSH if they ever can't get to the physical keyboard.
ALIGN_PID=$!
echo ""
echo "Alignment tool PID: $ALIGN_PID"
echo "To kill from SSH:"
echo "  sudo kill $ALIGN_PID         # by PID - use 'kill', NOT 'pkill'"
echo "  sudo pkill -f vop_setup_align  # by pattern - safer if you forget the PID"