#!/usr/bin/env bash
#
# VOP - onboard LED control setup
# -------------------------------
# Runs ONCE at boot (as root, via vop-led.service) to put the Pi's onboard
# LEDs under manual software control and hand write access to the VOP
# service user, so the engine can blank them during exposures with no sudo.
#
# Why this exists:
#   The VOP lives in a light-tight cabinet with the camera ~1.18m above the
#   projection monitor. The Pi's onboard LEDs sit right next to the camera.
#   The red PWR LED is a steady stray source; the green ACT LED is worse
#   during a job because it flickers on every TIFF write, strobing green
#   light at the latent. Both will fog long exposures.
#
# What it does, per LED found:
#   1. Sets the trigger to "none" so brightness is manual and steady
#      (no activity/power blinking).
#   2. Leaves it ON (brightness 1) as a normal "powered up" indicator.
#   3. chgrp's the 'brightness' file to 'gpio' and makes it group-writable,
#      so the VOP user can write 0/1 at runtime without root.
#
# The actual 0/1 toggling lives in modules/leds.py + the engine (Phase 2).
# This script only sets the stage at boot.

set -u   # error on unset vars. Deliberately NOT 'set -e': if one LED node
         # is missing on this board we want to skip it, not abort.

LED_BASE="/sys/class/leds"

# Group that should own the brightness files. 'gpio' exists on Pi OS and the
# default login user is normally a member. If your VOP user is not in it:
#   sudo usermod -aG gpio jmalmsten   (then reboot)
LED_GROUP="gpio"

# Candidate node names, newest naming first. Current Pi OS: red = "PWR",
# green = "ACT". Older images: red = "led1", green = "led0". We configure
# whichever exist - edit these arrays if you ever want to leave one alone.
RED_CANDIDATES=("PWR" "led1")
GREEN_CANDIDATES=("ACT" "led0")

# configure_led <human label> <candidate node names...>
configure_led() {
    local label="$1"; shift
    local name path
    for name in "$@"; do
        path="$LED_BASE/$name"
        if [ -d "$path" ]; then
            echo "[VOP-LED] Configuring $label LED at $path"
            # 1. Detach from kernel trigger -> brightness becomes manual/steady.
            echo none > "$path/trigger" 2>/dev/null \
                || echo "[VOP-LED]   (could not set trigger on $name)"
            # 2. Steady ON until the engine blanks it for an exposure.
            echo 1 > "$path/brightness" 2>/dev/null \
                || echo "[VOP-LED]   (could not set brightness on $name)"
            # 3. Hand runtime write access to the VOP user via the gpio group.
            #    Only 'brightness' needs to be writable - trigger stays 'none'
            #    for the whole boot, set once here as root.
            chgrp "$LED_GROUP" "$path/brightness" 2>/dev/null \
                || echo "[VOP-LED]   (could not chgrp brightness on $name)"
            chmod g+w "$path/brightness" 2>/dev/null \
                || echo "[VOP-LED]   (could not chmod brightness on $name)"
            return 0
        fi
    done
    echo "[VOP-LED] No $label LED node found (tried: $*) - skipping."
    return 1
}

echo "[VOP-LED] Setting up onboard LED control..."
configure_led "RED / PWR"   "${RED_CANDIDATES[@]}"
configure_led "GREEN / ACT" "${GREEN_CANDIDATES[@]}"
echo "[VOP-LED] Done."