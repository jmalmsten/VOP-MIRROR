#!/bin/bash
# VOP Module:   deploy_rgb_fix.sh
# Version:      1.0.0
# Description:  Automates the systemd setup for HDMI Full RGB enforcement.

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