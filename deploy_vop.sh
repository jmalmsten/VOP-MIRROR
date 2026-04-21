#!/bin/bash
# VOP Automated Deployment Script
# Target: Raspberry Pi OS Lite
# Version: 1.3.0
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


#######################################################################################
#
#       Explaining why each thing is needed:
#
#   As the VOP is a system built around a Raspberry Pi running Pi OS Lite (64 bit)
#   and expects to be connected to an HDMI monitor to project graphics to and a 
#   Pi Camera HQ that's pointed at said monitor. A few things is needed to get it
#   to boot up. 
#
#   In the interest of transparency, I will try to justify them here. 
#   ___________________________________________________________________________________
#
#   First off, System dependencies:
#
#   - git                                   - To be able to clone things with git
#                                             into the VOP.
#   - python3-pip                           - The package installer required to fetch 
#                                             the Python dependencies later.
#   - python3-venv                          - Provides the module to create isolated 
#                                             Python environments, which is strictly 
#                                             enforced by modern Debian.
#   - python3-dev                           - Provides the C header files required to 
#                                             compile python packages from source.
#   - ffmpeg                                - Handles backend video encoding, decoding 
#                                             and media processing.
#   - libsdl2-2.0-0                         - The core Simple DirectMedia Layer 
#                                             library, This allows Pygame to draw 
#                                             directly to the hardware framebuffer via 
#                                             KMS/DRM without an x11 or Wayland 
#                                             desktop.
#   - libsdl2-image-2.0-0                   - An extension for SDL2 required to load 
#                                             various image formats.
#   - libsdl2-image-dev                     - provides the decoding backends required 
#                                             to handle PNG's with alpha channels 
#                                             (transparency).
#   - libsdl2-ttf-dev & libfreetype6-dev    - Provides the C-headers required for 
#                                             Pygame to compile its pygame.font 
#                                             typography rendering module.
#   - libgl1-mesa-dri                       - Provides the Direct Rendering 
#                                             Infrastructure (DRI) drivers for 
#                                             hardware accelerated OpenGL.
#   - libegl1                               - The EGL interface. This acts as the 
#                                             bridge between OpenGL ES and the 
#                                             underlying hardware display system.
#   - libgles2                              - Provides the OpenGL ES 2.0 API, which is 
#                                             essential for modern GL to execute the 
#                                             hardware accelerated projection mapping 
#                                             on embedded GPUs.
#   - rpicam-apps                           - Contains the rpicam-still binary required 
#                                             by the engine to capture raw sensor data 
#                                             from the Pi Camera
#   - libx11-dev                            - Provides the X11 Window System headers 
#                                             required by the glcontext compiler, even 
#                                             though this will be running headless.
#   ___________________________________________________________________________________
#
#   Secondly, The Python dependencies:
#
#   - Flask                     - This runs the backend server and the webUI (vop.py)
#   - pygame                    - This handles the direct-to-screen framebuffer display 
#                                 via KMSDRM (engine.py)
#   - moderngl                  - This powers the hardware-accelerated multi-world 
#                                 projection mapping
#   - numpy                     - This handles the heavy math for colorspace 
#                                 conversions and 4 channel image buffers.
#   - opencv-python-headless    - Processes the image saving, flipping and latent TIFF
#                                 stacking.
#   - rawpy                     - Parses and debayers the raw .dng sensor data.
#   - pyrr                      - Handles the 3D Matrix math (Matrix44) for the virtual
#                                 camera frustum and aspect ratio scaling
#   ___________________________________________________________________________________
#
#   Thirdly, User permissions:
#   
#   - video     - Grants Pygame and the KMS/DRM driver direct write access to the 
#                 physical display hardware (e.g., /dev/dri/card0). This allows the 
#                 application to push pixels directly to the HDMI monitor without 
#                 needing an X11 or Wayland window server.
#   - render    - Grants ModernGL direct access to the Pi's GPU rendering nodes
#                 (e.g., /dev/dri/renderD128). This is strictly required to execute
#                 hardware-accelerated OpenGL ES shaders and 3D matrix math for the 
#                 multi-world projection mapping without requiring root (sudo)
#                 privileges.
#   - input     - Since the VOP is designed to run headless and take over the display 
#                 hardware without an x11/wayland server. It also requires access to 
#                 the TTY input device to catch keystrokes (like Ctrl-C or Pygame event
#                 loops)
#   ___________________________________________________________________________________
#
#   Lastly, Systemd Daemon:
#
#   - vop.service - The script automatically generates and enables a systemd service.
#                   This ensures the VOP starts automatically on boot and continues 
#                   running securely in the background even if you disconnect SSH.
#
#######################################################################################

# 1. Halt execution immediately if any command fails
set -e

# 2. Bulletproof Pathing: Resolve the exact directory where this script lives and move
#    into it
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Starting VOP Environment Deployment in $SCRIPT_DIR..."

# 3. System Dependencies
echo "Updating APT repositories..."
sudo apt update -y

echo "Installing system libraries and compilers..."
sudo apt install -y git python3-pip python3-venv python3-dev ffmpeg \
    libsdl2-2.0-0 libsdl2-image-2.0-0 libsdl2-dev libsdl2-image-dev \
    libsdl2-ttf-dev libfreetype6-dev libgl1-mesa-dri libegl1 \
    libgles2 libx11-dev rpicam-apps

# 4. Virtual Environment Setup
VENV_DIR="venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Initializing Python virtual environment in ./$VENV_DIR..."
    python3 -m venv "$VENV_DIR"
else
    echo "Virtual environment already exists. Skipping creation."
fi

# 5. Python Dependencies
echo "Upgrading pip..."
./$VENV_DIR/bin/pip install --upgrade pip

echo "Installing standard Python modules..."
./$VENV_DIR/bin/pip install Flask moderngl numpy opencv-python-headless rawpy pyrr

echo "Compiling Pygame from source for KMSDRM support (this will take a few minutes)..."
./$VENV_DIR/bin/pip install pygame --no-binary pygame --force-reinstall --no-cache-dir

# 6. Hardware Permissions
echo "Applying DRM, Render, and Input permissions to user: $USER..."
sudo usermod -a -G video,render,input "$USER"

# Make the manual start script executable (kept for manual debugging if needed)
if [ -f "run_vop.sh" ]; then
    chmod +x run_vop.sh
fi

# 7. Systemd Service Creation & Enabling
echo "Configuring systemd service for automatic startup..."
SERVICE_FILE="vop.service"

# This block creates the vop.service file directly, dynamically injecting the current path and user
cat <<EOF > "$SERVICE_FILE"
[Unit]
Description=VOP Server Daemon
After=network.target

[Service]
User=$USER
Group=$USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=$SCRIPT_DIR/$VENV_DIR/bin/python3 $SCRIPT_DIR/vop.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

echo "Installing and enabling vop.service..."
# Move the newly generated file into the OS system directory
sudo mv "$SERVICE_FILE" /etc/systemd/system/
# Tell the OS to refresh its list of available services
sudo systemctl daemon-reload
# Tell the OS to launch this service automatically on every boot
sudo systemctl enable vop.service

echo "========================================"
echo "Deployment Complete."
echo "Permissions modified and systemd service installed."
echo "A system reboot is required."
echo "========================================"
echo "              - Daemon Info -"
echo " The VOP will now start automatically on boot."
echo " To view live terminal logs at any time, run:"
echo " sudo journalctl -u vop.service -f"
echo "========================================"

# 8. Reboot Prompt
read -r -p "Reboot the system now? (y/N): " REBOOT_PROMPT
if [[ "$REBOOT_PROMPT" =~ ^[Yy]$ ]]; then
    echo "Rebooting..."
    sudo reboot now
else
    echo "Exiting. Run 'sudo reboot now' before starting the VOP."
    echo 
fi