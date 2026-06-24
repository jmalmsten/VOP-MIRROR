#!/bin/bash
# VOP Automated Deployment Script
# Target: Raspberry Pi OS Lite (Bookworm, 64-bit)
# Version: 1.5.0
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
#   Fourthly, Systemd Daemon:
#
#   - vop.service - The script automatically generates and enables a systemd service.
#                   This ensures the VOP starts automatically on boot and continues 
#                   running securely in the background even if you disconnect SSH.
#
#   ___________________________________________________________________________________
#
#   Optional, HDMI Full RGB Fix:
#
#   Some HDMI monitors negotiate the "Limited" color range (16-235) by default,
#   which lifts black levels and makes them look milky. The VOP needs deep blacks 
#   so the camera doesn't accidentally pick up stray light during long exposures.
#   The fix is a one-line systemd service that forces "Full RGB" (0-255) at every 
#   boot. This script will offer to set it up at the end of deployment.
#
#   ___________________________________________________________________________________
#
#   Changelog:
#   v1.5.0 - Removed 'After=multi-user.target' from the optional vop-rgb-fix 
#            service. That line combined with vop.service being WantedBy the 
#            same target created an ordering cycle in systemd's dependency 
#            graph, causing systemd to silently delete vop.service from the 
#            boot transaction. With the line removed, both services start 
#            cleanly at boot, with rgb-fix correctly preceding vop.
#   v1.4.0 - Added optional HDMI Full RGB Fix prompt at end of deployment.
#
#######################################################################################

# Halt execution immediately if any command fails
set -e

# Bulletproof Pathing: Resolve the exact directory where this script lives and move
# into it
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Starting VOP Environment Deployment in $SCRIPT_DIR..."

# 1. System Dependencies

# --- Clock sync guard (fresh-reflash hardening) ---------------------------
# A Raspberry Pi has no battery-backed RTC, so a freshly-flashed drive boots
# with a stale clock. On Debian Trixie, apt verifies repo signatures with sqv,
# which REJECTS signatures whose validity window starts "in the future"
# relative to the system clock — the "Not live until <date>" errors. So before
# touching any signed repo, make sure NTP has actually synced. We wait up to
# ~60s, then WARN and continue (deliberately not a hard fail: the operator
# might be intentionally offline, and we shouldn't brick the whole deploy).
echo "Ensuring the system clock is NTP-synced before touching apt repos..."
sudo timedatectl set-ntp true 2>/dev/null || true            # enable NTP (no-op if on)
sudo systemctl restart systemd-timesyncd 2>/dev/null || true # nudge an immediate sync
                                                             # (|| true: ignore if the
                                                             #  box uses chrony instead)

SYNC_WAIT=0          # seconds elapsed
SYNC_MAX=60          # give up after this many seconds
# NTPSynchronized is a systemd property that reads "yes" once the clock is set.
# It's backend-agnostic (works whether timesyncd or chrony is doing the work).
while [ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" != "yes" ]; do
    if [ "$SYNC_WAIT" -ge "$SYNC_MAX" ]; then
        echo "  WARNING: clock still not NTP-synced after ${SYNC_MAX}s."
        echo "           If apt reports 'Not live until ...' signature errors,"
        echo "           wait for the clock to sync (check with: timedatectl)"
        echo "           and then re-run this script."
        break
    fi
    echo "  Waiting for clock sync... (${SYNC_WAIT}s elapsed)"
    sleep 3
    SYNC_WAIT=$((SYNC_WAIT + 3))
done
# Report the result either way so the deploy log is unambiguous.
if [ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" = "yes" ]; then
    echo "  Clock is synced: $(date)"
fi
# --------------------------------------------------------------------------

echo "Updating APT repositories..."
sudo apt update -y

echo "Installing system libraries and compilers..."
sudo apt install -y git python3-pip python3-venv python3-dev ffmpeg \
    libsdl2-2.0-0 libsdl2-image-2.0-0 libsdl2-dev libsdl2-image-dev \
    libsdl2-ttf-dev libfreetype6-dev libgl1-mesa-dri libegl1 \
    libgles2 libx11-dev rpicam-apps

# 2. Virtual Environment Setup
VENV_DIR="venv"

if [ ! -d "$VENV_DIR" ]; then
    echo "Initializing Python virtual environment in ./$VENV_DIR..."
    python3 -m venv "$VENV_DIR"
else
    echo "Virtual environment already exists. Skipping creation."
fi

# 3. Python Dependencies
echo "Upgrading pip..."
./$VENV_DIR/bin/pip install --upgrade pip

echo "Installing standard Python modules..."
./$VENV_DIR/bin/pip install Flask moderngl numpy opencv-python-headless rawpy pyrr

echo "Compiling Pygame from source for KMSDRM support (this will take a few minutes)..."
./$VENV_DIR/bin/pip install pygame --no-binary pygame --force-reinstall --no-cache-dir

# 4. Hardware Permissions
echo "Applying DRM, Render, and Input permissions to user: $USER..."
sudo usermod -a -G video,render,input "$USER"

# Make the manual start script executable (kept for manual debugging if needed)
if [ -f "run_vop.sh" ]; then
    chmod +x run_vop.sh
fi

# 5. Systemd Service Creation & Enabling
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
# Tell the OS to launch this service automatically on every boot
sudo systemctl enable vop.service

# ---------------------------------------------------------------------------
# 5b. VOP Notifier (self-hosted ntfy)
# ---------------------------------------------------------------------------
# Installs a tiny self-hosted ntfy server so the VOP can push "Job Done" and
# error alerts to your phone over the LAN / VPN. No Docker, no cloud: a single
# static Go binary (MIT licensed — installed as a separate program, so no
# clash with this script's AGPL) managed by its own systemd unit. The engine
# publishes to it over loopback (modules/notifier.py); the phone subscribes
# over the network. The exact Topic URL is printed in the summary at the end.
echo "Setting up the VOP notifier (self-hosted ntfy)..."

# --- Detect THIS Pi's current LAN IP, for the server's base-url and for the
# --- Topic URL we print at the end. Prefer eth0 (the VOP is wired); fall back
# --- to the first global IPv4 if eth0 isn't the active interface, then to
# --- loopback as a last resort so we never write an empty base-url.
PI_IP="$(ip -4 -o addr show eth0 2>/dev/null | awk '{print $4}' | cut -d/ -f1 | head -n1)"
if [ -z "$PI_IP" ]; then
    PI_IP="$(hostname -I | awk '{print $1}')"
fi
if [ -z "$PI_IP" ]; then
    PI_IP="127.0.0.1"
    echo "  WARNING: could not detect a LAN IP; base-url falls back to 127.0.0.1."
    echo "           Set the real IP in /etc/ntfy/server.yml and restart ntfy,"
    echo "           or the phone won't be able to reach it."
fi
echo "  Detected Pi IP for notifier: $PI_IP"

# --- Add ntfy's official apt repo (idempotent on re-run). ntfy isn't in
# --- Debian's own repos. We use the CURRENT archive.ntfy.sh repo (the old
# --- archive.heckel.io one is being retired in 2026). arch=arm64 matches
# --- 64-bit Pi OS on the Pi 4B.
sudo mkdir -p /etc/apt/keyrings
sudo curl -L -o /etc/apt/keyrings/ntfy.gpg https://archive.ntfy.sh/apt/keyring.gpg
sudo apt install -y apt-transport-https
echo "deb [arch=arm64 signed-by=/etc/apt/keyrings/ntfy.gpg] https://archive.ntfy.sh/apt stable main" \
    | sudo tee /etc/apt/sources.list.d/ntfy.list
sudo apt update -y          # second update: needed to see the freshly-added repo
sudo apt install -y ntfy

# --- Write the LAN-only server config, baking in the detected IP as base-url.
# --- NOTE the UNQUOTED heredoc (<<EOF, not <<'EOF') so $PI_IP expands here.
# --- This overwrites any hand-edits on re-run — that's intentional: the deploy
# --- script's job is a reproducible-from-scratch setup. The cache lets a phone
# --- that was asleep during a long job still pick up the alert on reconnect.
sudo mkdir -p /var/cache/ntfy
sudo tee /etc/ntfy/server.yml > /dev/null <<EOF
# --- VOP notifier: self-hosted ntfy, LAN-only (generated by deploy_vop.sh) ---
base-url: "http://$PI_IP:7777"
listen-http: ":7777"
cache-file: "/var/cache/ntfy/cache.db"
cache-duration: "12h"
log-level: warn
EOF

# --- Enable + (re)start so it runs now and on every boot.
sudo systemctl enable ntfy
sudo systemctl restart ntfy

# 6. Optional HDMI Full RGB Fix
# This fix forces "Full RGB" (0-255) HDMI output. Recommended for most setups,
# but exposed as an opt-in prompt because some monitors / TVs already negotiate
# the correct range and forcing it could cause issues on edge-case hardware.
echo
echo "----------------------------------------"
echo " Optional: HDMI Full RGB Fix"
echo "----------------------------------------"
echo " By default, the Raspberry Pi often outputs a 'Limited' color range"
echo " (16-235) over HDMI, which lifts black levels and makes them look milky."
echo " For the VOP, deep blacks matter — they keep the camera from picking up"
echo " stray light during long exposures. The fix is a small systemd oneshot"
echo " service that forces 'Full RGB' (0-255) at every boot."
echo
echo " If your monitor already shows true blacks, skip this. If you're unsure,"
echo " saying yes is the safer default for VOP use."
echo "----------------------------------------"
read -r -p "Set up the HDMI Full RGB fix now? (y/N): " RGB_PROMPT
if [[ "$RGB_PROMPT" =~ ^[Yy]$ ]]; then
    RGB_FIX_SCRIPT="$SCRIPT_DIR/CaliTools/FullRGBFix/force_full_rgb.sh"
    RGB_SERVICE_FILE="vop-rgb-fix.service"
    
    if [ ! -f "$RGB_FIX_SCRIPT" ]; then
        echo "WARNING: $RGB_FIX_SCRIPT not found. Skipping RGB fix setup."
        echo "         (Did the git clone include the CaliTools/ subdirectory?)"
    else
        echo "Setting up HDMI Full RGB fix..."
        chmod +x "$RGB_FIX_SCRIPT"
        
        # Generate the service file. We add 'Before=vop.service' so the RGB 
        # fix fires before the engine grabs the framebuffer -- otherwise the 
        # engine might see the wrong range during its first render.
        # 
        # Note: There is intentionally NO 'After=multi-user.target' here.
        # Adding that line creates an ordering cycle (multi-user wants vop, 
        # vop is After=rgb-fix, rgb-fix is After=multi-user) which causes 
        # systemd to silently drop vop.service from the boot transaction.
        # The Before=vop.service alone is enough to enforce the correct
        # ordering between the two services.
        cat <<EOF > "$RGB_SERVICE_FILE"
[Unit]
Description=VOP Monitor Full RGB Calibration
Before=vop.service

[Service]
Type=oneshot
ExecStart=$RGB_FIX_SCRIPT
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
        sudo mv "$RGB_SERVICE_FILE" /etc/systemd/system/
        sudo systemctl daemon-reload
        sudo systemctl enable vop-rgb-fix.service
        echo "HDMI Full RGB fix installed and enabled."
    fi
else
    echo "Skipping HDMI Full RGB fix. You can run it later by re-running this"
    echo "script, or by manually executing CaliTools/FullRGBFix/deploy_rgb_fix.sh"
fi

# 7. Optional Onboard LED Blanking
# The Pi's onboard LEDs (red PWR, green ACT) sit right beside the camera
# inside the light-tight cabinet. The red is a steady stray source; the green
# strobes on every TIFF write during a job - both fog long exposures. This
# installs a small systemd oneshot that, at each boot, puts both LEDs under
# manual control and hands their brightness write-access to the VOP user, so
# the engine can blank them while exposing. Opt-in, like the RGB fix above.
echo
echo "----------------------------------------"
echo " Optional: Onboard LED Blanking"
echo "----------------------------------------"
echo " The Pi's red PWR and green ACT LEDs sit next to the camera inside the"
echo " cabinet. During long exposures they leak light onto the latent image —"
echo " the red steadily, the green strobing on every disk write. This sets up"
echo " a small systemd oneshot service that, at each boot, puts both LEDs under"
echo " manual control and lets the VOP blank them during exposures."
echo
echo " Recommended for the sealed-cabinet setup. Skip it if your Pi is out in"
echo " the open and you'd rather keep the LEDs as normal status indicators."
echo "----------------------------------------"
read -r -p "Set up onboard LED blanking now? (y/N): " LED_PROMPT
if [[ "$LED_PROMPT" =~ ^[Yy]$ ]]; then
    LED_SETUP_SCRIPT="$SCRIPT_DIR/CaliTools/LedControl/setup_led_control.sh"
    LED_SERVICE_FILE="vop-led.service"

    if [ ! -f "$LED_SETUP_SCRIPT" ]; then
        echo "WARNING: $LED_SETUP_SCRIPT not found. Skipping LED blanking setup."
        echo "         (Did the git clone include the CaliTools/ subdirectory?)"
    else
        echo "Setting up onboard LED blanking..."
        chmod +x "$LED_SETUP_SCRIPT"

        # The runtime brightness writes happen as the VOP user (User=$USER in
        # vop.service), NOT root, so that user must belong to the 'gpio' group
        # that setup_led_control.sh grants write-access to. Add them now; the
        # membership change takes effect after the reboot at the end of this
        # script. Harmless / idempotent if they're already a member.
        sudo usermod -aG gpio "$USER"

        # Generate the service file. As with the RGB fix we use
        # 'Before=vop.service' so the LEDs are configured before the engine
        # starts, and we deliberately OMIT 'After=multi-user.target' to avoid
        # the ordering cycle that would silently drop vop.service from boot.
        cat <<EOF > "$LED_SERVICE_FILE"
[Unit]
Description=VOP Onboard LED Control Setup
Before=vop.service

[Service]
Type=oneshot
ExecStart=$LED_SETUP_SCRIPT
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
        sudo mv "$LED_SERVICE_FILE" /etc/systemd/system/
        sudo systemctl daemon-reload
        sudo systemctl enable vop-led.service
        echo "Onboard LED blanking installed and enabled (active after reboot)."
    fi
else
    echo "Skipping onboard LED blanking. You can set it up later by re-running"
    echo "this script and answering yes."
fi

echo
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
echo "              - Notifier -"
echo " Self-hosted ntfy is running on this Pi (port 7777)."
echo " In the ntfy phone app (Android: install from F-Droid), choose"
echo " 'Subscribe to topic' and enter this Topic URL exactly:"
echo
echo "     http://$PI_IP:7777/vop-alerts"
echo
echo " With your phone on the home LAN / VPN you'll then get Job Done and"
echo " error pushes. (iOS needs an internet relay for background push; on"
echo " Android it's fully LAN-only.)"
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
