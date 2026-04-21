#!/bin/bash
# VOP Module:   deploy_rgb_fix.sh
# Version:      1.0.0
# Description:  Automates the systemd setup for HDMI Full RGB enforcement.
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


# Define paths for clarity
FIX_SCRIPT="/home/$USER/VOP/CaliTools/FullRGBFix/force_full_rgb.sh"
SERVICE_FILE="/etc/systemd/system/vop-rgb-fix.service"

echo "--- VOP RGB Fix Deployment v1.0.0 ---"

# 1. Ensure the fix script is executable
if [ -f "$FIX_SCRIPT" ]; then
    chmod +x "$FIX_SCRIPT"
    echo "[1/3] Script permissions set."
else
    echo "ERROR: Fix script not found at $FIX_SCRIPT"
    exit 1
fi

# 2. Create the systemd service file
# Note: We add 'Before=vop.service' to ensure the order is correct.
sudo tee "$SERVICE_FILE" > /dev/null <<EOF
[Unit]
Description=VOP Monitor Full RGB Calibration
# This ensures the fix happens BEFORE the VOP engine starts
Before=vop.service
After=multi-user.target

[Service]
Type=oneshot
ExecStart=$FIX_SCRIPT
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
echo "[2/3] systemd service created with VOP ordering."

# 3. Reload and Enable
sudo systemctl daemon-reload
sudo systemctl enable vop-rgb-fix.service
echo "[3/3] Service enabled for boot."

# 4. Immediate execution (Requires stopping VOP temporarily)
echo "Applying fix now (restarting services)..."
sudo systemctl stop vop
sudo systemctl start vop-rgb-fix.service
sudo systemctl start vop

echo "Done. Black levels should now be correct."