#!/bin/bash
# VOP Pre-Deployment Script
# Target: a Linux desktop preparing a USB stick / SD card for a Raspberry Pi
# Version: 2.0.0
#
# Flashes Raspberry Pi OS Lite (64-bit) onto the specified block device, mounts
# the resulting partitions, and injects the headless-config knobs that would
# otherwise have to be done by hand. Result: a stick that boots straight into
# an SSH-ready Pi without ever needing a keyboard or HDMI on the target.
#
# Everything that varies between setups (password, SSH key, custom shell,
# webcam stream, fan control, IP) is asked at the start as a prompt, with safe
# defaults. Hit Enter through all of them for a sensible minimal install.
#
# Networking model: wired ethernet only. The VOP's host Pi connects through a
# wired switch
#
# Usage:
#   ./predeploy_vop.sh /dev/sd#
#
# That argument is mandatory. There is no auto-detect, on purpose: getting it
# wrong means dd-ing over the wrong drive, and that is not a recoverable
# mistake. The script shows a summary and prompts twice before writing.
#
# Recommendation from me is to first run lsblk to see the current block drives.
# When you think you know which is correct. Pull out the USB stick. Run lsblk 
# again and see if it disappeared in the correct spot. Once confirmed. Put the
# USB stick back in and do a third lsblk. When double confirmed. Start this 
# script.
#
# Changelog:
#   2.0.0 - Public release. All maintainer-specific assumptions turned into
#           prompts with safe defaults: optional SSH key (auto-detected or
#           skippable), optional password override, optional custom shell,
#           optional webcam service, optional fan control. All interaction is
#           now gathered up front before the flash. Declining the custom shell
#           copies the stock /etc/skel files so the home dir is never bare.
#   1.4.0 - Added PWM fan control via a config.txt dtoverlay line.
#   1.3.0 - Removed all WiFi / rfkill configuration; wired ethernet only. Added
#           .bash_profile injection so SSH login shells source .bashrc.
#   1.2.0 - Added custom .bashrc (timestamped prompt, auto-ls, case-insensitive
#           completion).
#   1.1.0 - Fixed home directory ownership: Pi OS won't reclaim an already-
#           existing /home/<user>/ at first boot, so we chown it to UID 1000
#           ourselves before injecting anything.
#   1.0.0 - Initial version.

set -e   # Halt on any error
set -u   # Treat unset variables as errors

###############################################################################
# CONFIGURATION  --  defaults the prompts will offer. Edit to taste.
###############################################################################
PI_USERNAME="vop"
PI_PASSWORD="12345"          # default; overridable at the prompt below

# Optional default SSH PUBLIC key path. Leave EMPTY in the public copy.
#   - If set and the file exists, it becomes the offered default.
#   - If empty, the script auto-detects a standard key (ed25519 -> rsa ->
#     ecdsa) in ~/.ssh at prompt time.
# Set this to your own key (e.g. "$HOME/.ssh/id_fleet.pub") to skip the hunt.
DEFAULT_SSH_PUBKEY=""

# Only used to (a) clear a stale SSH host-key entry on THIS workstation and
# (b) print the correct `ssh` hint at the end. It does NOT assign a static IP
# to the Pi -- the Pi still gets its address via DHCP.
DEFAULT_PI_IP="192.168.1.2"

# Fan defaults (only offered if you opt into fan control at the prompt).
DEFAULT_FAN_GPIO=14
DEFAULT_FAN_TRIGGER_C=60

# Working dirs / temp paths
WORK_DIR="$HOME/vop-predeploy-tmp"
IMG_FILE="$WORK_DIR/raspios_lite_arm64.img"
IMG_URL="https://downloads.raspberrypi.com/raspios_lite_arm64_latest"
MOUNT_BOOT="/mnt/pi_boot"
MOUNT_ROOT="/mnt/pi_root"

###############################################################################
# Step 0 -- Argument & sanity checks
###############################################################################

if [ $# -ne 1 ]; then
    echo "Usage: $0 /dev/sdX"
    echo "  where /dev/sdX is the target USB stick (NOT a partition like /dev/sdX1)"
    exit 1
fi

TARGET_DEV="$1"

# Refuse partition paths -- only accept whole-disk devices.
if [[ "$TARGET_DEV" =~ [0-9]$ ]]; then
    echo "ERROR: '$TARGET_DEV' looks like a partition. Pass the whole disk (e.g. /dev/sdg, not /dev/sdg1)."
    exit 1
fi

# Refuse if the device isn't a real block device on this system.
if [ ! -b "$TARGET_DEV" ]; then
    echo "ERROR: '$TARGET_DEV' is not a block device on this system."
    exit 1
fi

# Grab size/model once, for the summary banner later.
DEV_SIZE="$(lsblk -ndo SIZE "$TARGET_DEV")"
DEV_MODEL="$(lsblk -ndo MODEL "$TARGET_DEV")"

###############################################################################
# Step 1 -- Gather ALL interactive choices up front
###############################################################################
# Everything that needs a human is asked here, before the long-running flash.
# Once you clear the final go/no-go at the bottom of this section, the rest of
# the script runs unattended.

echo
echo "=================================================================="
echo "  VOP Pre-Deployment"
echo "=================================================================="
echo "  Preparing to image: $TARGET_DEV  ($DEV_SIZE, $DEV_MODEL)"
echo "=================================================================="

# --- 1a. Password override --------------------------------------------------
# The default password is deliberately trivial, and that is a feature:
#   - The VOP is meant to hold NOTHING secret -- it's a light-adding appliance.
#   - SSH into it is meant to be ONE-WAY: no private keys live on the Pi, so a
#     compromised VOP can't walk backwards into the rest of your network.
# The weak default signals "don't trust this box." But if you'd rather not run
# your luggage combination as a login, you can override it here.
#
# read -s = silent (no echo), since this is a password. The bare `echo` after
# each read emits the newline that -s swallows.
echo
echo "  Default Pi password is '$PI_PASSWORD'. It's intentionally weak -- the"
echo "  VOP should hold nothing secret and SSH to it is meant to be one-way."
echo
read -r -s -p "  Press Enter to keep it, or type a new password: " PW_INPUT
echo
if [ -n "$PW_INPUT" ]; then
    # Re-type confirmation: a mistyped password here would otherwise lock you
    # out of the freshly-flashed Pi with no easy recovery short of re-flash.
    read -r -s -p "  Re-type to confirm: " PW_CONFIRM
    echo
    if [ "$PW_INPUT" != "$PW_CONFIRM" ]; then
        echo "  Passwords did not match. Aborting before any changes are made."
        exit 1
    fi
    PI_PASSWORD="$PW_INPUT"
    echo "  Custom password set."
else
    echo "  Keeping default password '$PI_PASSWORD'."
fi

# --- 1b. SSH public key -----------------------------------------------------
# Injecting your PUBLIC key lets this workstation log in to the Pi with key
# auth on first boot -- no password typing. Only the public half is copied, so
# nothing that could authenticate back into your network ends up on the Pi.
#
# Resolve a default to offer: explicit config var first, else auto-detect.
SSH_PUBKEY=""               # final choice; empty means "no key, password only"
KEY_DEFAULT=""
if [ -n "$DEFAULT_SSH_PUBKEY" ] && [ -f "$DEFAULT_SSH_PUBKEY" ]; then
    KEY_DEFAULT="$DEFAULT_SSH_PUBKEY"
else
    for candidate in id_ed25519 id_rsa id_ecdsa; do
        if [ -f "$HOME/.ssh/${candidate}.pub" ]; then
            KEY_DEFAULT="$HOME/.ssh/${candidate}.pub"
            break
        fi
    done
fi

echo
echo "  SSH public key. Lets this machine log into the Pi with key auth (no"
echo "  password) on first boot. Only the PUBLIC key is copied to the Pi."
if [ -n "$KEY_DEFAULT" ]; then
    echo "  Found: $KEY_DEFAULT"
    read -r -p "  Enter to use it, type another path, or type 'skip': " KEY_INPUT
    if [ -z "$KEY_INPUT" ]; then
        SSH_PUBKEY="$KEY_DEFAULT"
    elif [ "$KEY_INPUT" = "skip" ]; then
        SSH_PUBKEY=""
    else
        SSH_PUBKEY="$KEY_INPUT"
    fi
else
    echo "  No standard key found in ~/.ssh."
    read -r -p "  Type a path to a public key, or press Enter to skip: " KEY_INPUT
    SSH_PUBKEY="$KEY_INPUT"          # empty stays empty = skip
fi

# Validate a chosen key actually exists, before we destroy anything.
if [ -n "$SSH_PUBKEY" ] && [ ! -f "$SSH_PUBKEY" ]; then
    echo "  ERROR: no file at '$SSH_PUBKEY'. Aborting before any changes."
    exit 1
fi

# --- 1c. Custom shell prompt ------------------------------------------------
# Optional. Shows a live preview rendered in the actual cyan so you see exactly
# what you're opting into. Declining keeps the stock Raspberry Pi OS shell.
echo
echo "  The VOP ships an optional custom shell prompt: a timestamp line, a"
echo "  color-coded user@host:path line, and auto-ls on directory change."
echo "  Here's how it would look (rendered live):"
echo
echo -e "    \e[1;36m[$(date +'%F %T')]\e[0m"
echo -e "    \e[1;36m${PI_USERNAME}@raspberrypi:/home/${PI_USERNAME}\e[0m"
echo -e "    \e[1;36m\$\e[0m"
echo
echo "  Decline to keep the stock Raspberry Pi OS shell."
read -r -p "  Install the custom VOP shell prompt? [y/N]: " SHELL_INPUT
if [[ "$SHELL_INPUT" =~ ^[Yy]$ ]]; then
    INSTALL_CUSTOM_SHELL=1
else
    INSTALL_CUSTOM_SHELL=0
fi

# --- 1d. Webcam livestream service ------------------------------------------
# Optional. A Logitech C920's ONBOARD H.264 relayed to OBS over SRT with no
# transcode (~3% CPU). The capture values are tuned to one specific setup --
# you'll want to edit apply_c920_controls.sh on the Pi for yours.
echo
echo "  Optional webcam stream: Logitech C920 H.264 -> SRT (no transcode)."
echo "  The capture settings (exposure, white balance, mains frequency) are"
echo "  tuned to one setup; edit apply_c920_controls.sh afterwards for yours."
read -r -p "  Install the C920 webcam stream service? [y/N]: " WEBCAM_INPUT
if [[ "$WEBCAM_INPUT" =~ ^[Yy]$ ]]; then
    INSTALL_WEBCAM=1
else
    INSTALL_WEBCAM=0
fi

# --- 1e. PWM fan control ----------------------------------------------------
# Optional. A device-tree overlay lets the kernel ramp a fan from SoC
# temperature with zero userspace overhead. Only useful if you have a fan
# wired to a GPIO pin. On yes, you set the pin and the trigger temperature.
echo
echo "  Optional PWM fan control via device-tree overlay. The kernel ramps the"
echo "  fan from SoC temperature, no userspace polling. Only useful if you have"
echo "  a fan wired to a GPIO pin."
read -r -p "  Configure PWM fan control? [y/N]: " FAN_INPUT
if [[ "$FAN_INPUT" =~ ^[Yy]$ ]]; then
    INSTALL_FAN=1
    read -r -p "  Fan GPIO pin number [default ${DEFAULT_FAN_GPIO}]: " FAN_GPIO_INPUT
    FAN_GPIO="${FAN_GPIO_INPUT:-$DEFAULT_FAN_GPIO}"
    read -r -p "  Temperature trigger in C [default ${DEFAULT_FAN_TRIGGER_C}]: " FAN_TEMP_INPUT
    FAN_TRIGGER_C="${FAN_TEMP_INPUT:-$DEFAULT_FAN_TRIGGER_C}"

    # Validate both as plain integers -- they get interpolated into config.txt
    # and a non-numeric value would silently produce a broken overlay line.
    if ! [[ "$FAN_GPIO" =~ ^[0-9]+$ ]] || ! [[ "$FAN_TRIGGER_C" =~ ^[0-9]+$ ]]; then
        echo "  ERROR: GPIO pin and temperature must be whole numbers. Aborting."
        exit 1
    fi
    if [ "$FAN_TRIGGER_C" -lt 60 ]; then
        echo "  Note: the gpio-fan overlay generally won't honor triggers below"
        echo "        60 C; the kernel may clamp it. Continuing with ${FAN_TRIGGER_C}."
    fi
else
    INSTALL_FAN=0
fi

# --- 1f. Pi IP (host-key cleanup + ssh hint only) ---------------------------
echo
echo "  Pi IP address. Used only to clear a stale SSH host-key entry on THIS"
echo "  machine and to print the correct ssh command at the end. It does NOT"
echo "  assign a static IP to the Pi (that's still DHCP)."
read -r -p "  Pi IP [default ${DEFAULT_PI_IP}]: " IP_INPUT
PI_EXPECTED_IP="${IP_INPUT:-$DEFAULT_PI_IP}"

# --- 1g. Summary + final destructive confirmation ---------------------------
echo
echo "=================================================================="
echo "  Ready to flash. Chosen configuration:"
echo "=================================================================="
echo "    Target device:   $TARGET_DEV  ($DEV_SIZE, $DEV_MODEL)"
echo "    Pi username:     $PI_USERNAME"
echo "    SSH key:         ${SSH_PUBKEY:-<none, password login only>}"
echo "    Custom shell:    $([ "$INSTALL_CUSTOM_SHELL" -eq 1 ] && echo yes || echo 'no (stock)')"
echo "    Webcam stream:   $([ "$INSTALL_WEBCAM" -eq 1 ] && echo yes || echo no)"
if [ "$INSTALL_FAN" -eq 1 ]; then
    echo "    Fan control:     yes (GPIO ${FAN_GPIO}, ${FAN_TRIGGER_C} C)"
else
    echo "    Fan control:     no"
fi
echo "    Pi IP (hint):    $PI_EXPECTED_IP"
echo
echo "  *** THIS WILL ERASE EVERYTHING ON $TARGET_DEV ***"
echo "=================================================================="
echo
read -r -p "  Type the full device path again to confirm: " CONFIRM_DEV
if [ "$CONFIRM_DEV" != "$TARGET_DEV" ]; then
    echo "  Confirmation mismatch. Aborting."
    exit 1
fi
read -r -p "  Final go/no-go? (y/N): " GO_PROMPT
if [[ ! "$GO_PROMPT" =~ ^[Yy]$ ]]; then
    echo "  Aborted by user."
    exit 0
fi

###############################################################################
# Step 2 -- Unmount any existing partitions on the target
###############################################################################
echo
echo "==> Unmounting any existing partitions on $TARGET_DEV..."
for part in "$TARGET_DEV"*; do
    if mountpoint -q "$part" 2>/dev/null; then
        sudo umount "$part" || true
    fi
done
sudo umount "${TARGET_DEV}"* 2>/dev/null || true   # belt and suspenders

###############################################################################
# Step 3 -- Download and decompress the image (skip if cached)
###############################################################################
echo
echo "==> Preparing OS image..."
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"

if [ -f "$IMG_FILE" ]; then
    echo "    Cached image found at $IMG_FILE -- using it."
    echo "    (Delete it manually to force a fresh download.)"
else
    echo "    Downloading latest 64-bit Lite image..."
    wget -O raspios_lite_arm64.img.xz "$IMG_URL"
    echo "    Decompressing..."
    xz -dv raspios_lite_arm64.img.xz
fi

###############################################################################
# Step 4 -- Flash with dd
###############################################################################
echo
echo "==> Flashing $IMG_FILE to $TARGET_DEV (this takes a while)..."
sudo dd if="$IMG_FILE" of="$TARGET_DEV" bs=4M status=progress conv=fsync
sync

# Force the kernel to re-read the partition table.
sudo partprobe "$TARGET_DEV" || true
sleep 2

###############################################################################
# Step 5 -- Mount the freshly-flashed partitions
###############################################################################
echo
echo "==> Mounting partitions..."
sudo mkdir -p "$MOUNT_BOOT" "$MOUNT_ROOT"
sudo mount "${TARGET_DEV}1" "$MOUNT_BOOT"
sudo mount "${TARGET_DEV}2" "$MOUNT_ROOT"

###############################################################################
# Step 6 -- Headless configuration injection
###############################################################################
echo
echo "==> Injecting headless config..."

# 6a. Enable SSH on first boot (touch flag in boot partition).
sudo touch "$MOUNT_BOOT/ssh"

# 6b. Create user with hashed password (Pi OS reads userconf.txt at first boot).
#     Feeding the password via stdin keeps special characters safe.
VOP_HASH=$(echo -n "$PI_PASSWORD" | openssl passwd -6 -stdin)
echo "$PI_USERNAME:$VOP_HASH" | sudo tee "$MOUNT_BOOT/userconf.txt" > /dev/null

# 6c. Pre-create the home directory and chown it to UID 1000 BEFORE dropping
#     files in. Pi OS won't reclaim an already-existing /home/<user>/ at first
#     boot, so without this the user can log in but everything in their home
#     dir requires sudo.
HOME_DIR="$MOUNT_ROOT/home/$PI_USERNAME"
sudo mkdir -p "$HOME_DIR"
sudo chown 1000:1000 "$HOME_DIR"

# 6d. Inject the SSH public key (only if the user chose one).
if [ -n "$SSH_PUBKEY" ]; then
    SSH_DIR="$HOME_DIR/.ssh"
    sudo mkdir -p "$SSH_DIR"
    sudo cp "$SSH_PUBKEY" "$SSH_DIR/authorized_keys"
    sudo chown -R 1000:1000 "$SSH_DIR"        # UID 1000 = first user on Pi
    sudo chmod 700 "$SSH_DIR"
    sudo chmod 600 "$SSH_DIR/authorized_keys"
    echo "    SSH key installed from $SSH_PUBKEY"
else
    echo "    No SSH key chosen -- password login only."
fi

###############################################################################
# Step 7 -- Shell environment
###############################################################################
echo
echo "==> Configuring shell environment..."

if [ "$INSTALL_CUSTOM_SHELL" -eq 1 ]; then
    # --- Custom VOP shell prompt --------------------------------------------
    # The 'EOF' is quoted so $variables in the heredoc stay literal -- they
    # must expand at runtime on the Pi, not at flash-time on the host.
    BASHRC_FILE="$HOME_DIR/.bashrc"
    sudo tee "$BASHRC_FILE" > /dev/null <<'EOF'
# ~/.bashrc: executed by bash(1) for non-login shells.
# Customized by predeploy_vop.sh during system imaging.

# If not running interactively, don't do anything
# (prevents prompt machinery from breaking scp/sftp/rsync sessions)
case $- in
    *i*) ;;
      *) return;;
esac

# don't put duplicate lines or lines starting with space in the history.
HISTCONTROL=ignoreboth

# append to the history file, don't overwrite it
# (so multiple SSH sessions don't clobber each other's history)
shopt -s histappend

# history sizing
HISTSIZE=1000
HISTFILESIZE=2000

# check the window size after each command and update LINES and COLUMNS
# (important for the auto-ls below to know how wide to format)
shopt -s checkwinsize

# debian_chroot bookkeeping (Pi OS is Debian-based, so we keep this)
if [ -z "${debian_chroot:-}" ] && [ -r /etc/debian_chroot ]; then
    debian_chroot=$(cat /etc/debian_chroot)
fi

# enable color support of ls and add the standard alias
# (dircolors gives `ls` its file-type coloring)
if [ -x /usr/bin/dircolors ]; then
    test -r ~/.dircolors && eval "$(dircolors -b ~/.dircolors)" || eval "$(dircolors -b)"
    alias ls='ls --color=auto'
fi

# pull in ~/.bash_aliases if it exists
# (good place for any VOP-specific shortcuts you add later)
if [ -f ~/.bash_aliases ]; then
    . ~/.bash_aliases
fi

# enable programmable completion features
# (tab-completion for things like systemctl, git, etc.)
if ! shopt -oq posix; then
    if [ -f /usr/share/bash-completion/bash_completion ]; then
        . /usr/share/bash-completion/bash_completion
    elif [ -f /etc/bash_completion ]; then
        . /etc/bash_completion
    fi
fi

# --- Clean cd Function ---
# Wrapper around builtin cd. Currently a passthrough, but kept here
# so PROMPT_COMMAND can reliably detect dir changes via $PWD.
cd() {
    builtin cd "$@"
}

# --- The Ultimate Prompt Builder (v1.6 - VOP Cyan Edition) ---
# Color note: \e[1;36m = bold cyan. Swap to e.g. 1;33 (yellow) or 1;35
# (magenta) on other Pis if you ever want each box to have its own hue.
_build_my_prompt() {
    # 1. Row 1: Timestamp in bold cyan
    # No leading \n -- sits flush under the previous command's output
    echo -e "\e[1;36m[$(date +'%F %T')]\e[0m"

    # 2. Row 2: user@host:cwd in bold cyan
    # Leading \n gives a visual gap between timestamp and the path line
    echo -e "\n\e[1;36m${USER}@${HOSTNAME}:${PWD}\e[0m"

    # 3. Auto-ls on directory change
    # Only runs the listing when $PWD actually differs from last time,
    # so you don't get a re-listing after every single command.
    if [ "$PWD" != "$_LAST_PWD" ]; then
        # Count entries (including dotfiles, excluding . and ..)
        local item_count=$(ls -1A 2>/dev/null | wc -l)
        if [ "$item_count" -gt 0 ]; then
            # Cap at 100 entries -- the VOP work dirs can hold thousands
            # of TIFFs and you don't want to flood the terminal each cd.
            if [ "$item_count" -lt 100 ]; then
                ls -CF --color=always -w $COLUMNS
            else
                echo -e "\e[1;36m\n[Notice] $item_count items in directory. Auto-ls skipped.\e[0m"
            fi
        fi
        export _LAST_PWD="$PWD"
    fi
}

# Hook the builder into bash's prompt cycle
# PROMPT_COMMAND runs before each prompt is drawn
PROMPT_COMMAND="_build_my_prompt"

# Keep PS1 itself minimal -- just the cyan $ -- since the builder
# above already drew the timestamp and path lines.
# The \[ and \] markers tell bash these escapes are zero-width, so
# line-wrap math stays correct on long commands.
export PS1='\[\e[1;36m\]$ \[\e[0m\]'

# Initialize the dir tracker so the first prompt doesn't auto-ls
# unless you actually cd somewhere.
export _LAST_PWD="$PWD"

# Case-insensitive tab completion (so `cd dow<TAB>` matches `Downloads`)
bind -s 'set completion-ignore-case on'
EOF

    sudo chown 1000:1000 "$BASHRC_FILE"
    sudo chmod 644 "$BASHRC_FILE"

    # .bash_profile: read by bash for login shells (SSH, console login).
    # Without this, the .bashrc above would only fire for non-login shells,
    # so SSH connections would land in the default Pi OS prompt until the user
    # ran `source ~/.bashrc` manually. Sourcing .bashrc from .bash_profile is
    # the canonical fix for the whole "my prompt only appears sometimes" class
    # of Bash startup-file confusion.
    BASH_PROFILE_FILE="$HOME_DIR/.bash_profile"
    sudo tee "$BASH_PROFILE_FILE" > /dev/null <<'EOF'
# ~/.bash_profile -- read by bash for login shells (SSH, console login)
#
# Bash's startup file rules are notoriously confusing. The short version:
#   - Login shells read ~/.bash_profile (or ~/.bash_login, or ~/.profile)
#   - Non-login interactive shells read ~/.bashrc
# SSH sessions start as login shells, so without this file our prompt
# customizations in ~/.bashrc never get loaded on connect.
#
# The standard workaround is to have .bash_profile source .bashrc,
# which gives both shell types the same environment.
if [ -f ~/.bashrc ]; then
    . ~/.bashrc
fi
EOF

    sudo chown 1000:1000 "$BASH_PROFILE_FILE"
    sudo chmod 644 "$BASH_PROFILE_FILE"
    echo "    Custom VOP shell prompt installed."
else
    # --- Stock shell --------------------------------------------------------
    # We pre-created the home dir above, which means Pi OS will NOT populate it
    # from /etc/skel at first boot. So copy the skeleton dotfiles ourselves;
    # otherwise a declined custom shell would leave a bare, prompt-less home.
    for skel in .bashrc .profile .bash_logout; do
        if [ -f "$MOUNT_ROOT/etc/skel/$skel" ]; then
            sudo cp "$MOUNT_ROOT/etc/skel/$skel" "$HOME_DIR/$skel"
            sudo chown 1000:1000 "$HOME_DIR/$skel"
            sudo chmod 644 "$HOME_DIR/$skel"
        fi
    done
    echo "    Stock Raspberry Pi OS shell installed (from /etc/skel)."
fi

###############################################################################
# Step 8 -- PWM fan control (optional)
###############################################################################
if [ "$INSTALL_FAN" -eq 1 ]; then
    echo
    echo "==> Configuring PWM fan control..."

    # Appends one dtoverlay line to config.txt, mirroring raspi-config's
    # "Performance Options -> Fan" UI. The kernel reads it at boot and ramps
    # the fan from a thermal zone -- no userspace, no Python polling.
    #
    # Idempotency check: if the line already exists (e.g. re-flashing an
    # already-prepared stick) skip the append so we don't duplicate it.
    CONFIG_FILE="$MOUNT_BOOT/config.txt"
    # temp is in millidegrees C, hence the trailing 000.
    FAN_LINE="dtoverlay=gpio-fan,gpiopin=${FAN_GPIO},temp=${FAN_TRIGGER_C}000"

    if sudo grep -q "^dtoverlay=gpio-fan" "$CONFIG_FILE"; then
        echo "    gpio-fan overlay already present in config.txt -- skipping."
    else
        # Recent Pi OS uses an implicit [all] scope; appending at the end
        # takes effect under it.
        echo "$FAN_LINE" | sudo tee -a "$CONFIG_FILE" > /dev/null
        echo "    Added: $FAN_LINE"
    fi
fi

###############################################################################
# Step 9 -- Webcam livestream service (optional)
###############################################################################
if [ "$INSTALL_WEBCAM" -eq 1 ]; then
    echo
    echo "==> Installing webcam livestream service..."
    # Relays the C920's onboard H.264 to OBS over SRT with no transcode.
    # Needs ffmpeg + v4l2-utils (installed later by deploy_vop.sh); until then
    # the service restart-loops harmlessly and self-starts once ffmpeg appears.
    #
    # NOTE: the systemd unit below hardcodes user 'vop' and /home/vop. That's
    # fine as long as PI_USERNAME is "vop". If you changed PI_USERNAME, edit
    # the unit's User= line and the apply-script path to match.

    # --- 9a. Manual-controls script -----------------------------------------
    # Reapplies fixed exposure/WB/focus after ffmpeg opens the device (the
    # C920 reverts to auto on every open). Quoted 'EOF' keeps $DEV literal so
    # it expands at runtime on the Pi.
    WEBCAM_BIN_DIR="$HOME_DIR/bin"
    sudo mkdir -p "$WEBCAM_BIN_DIR"
    sudo tee "$WEBCAM_BIN_DIR/apply_c920_controls.sh" > /dev/null <<'EOF'
#!/usr/bin/env bash
# Locks the C920 on /dev/video0 to fixed manual settings for the VOP stream.
# Auto modes off first (activates their manual partners), values second.
# No "set -e": best-effort, so one failed control won't block the rest.
DEV="/dev/video0"

# Turn OFF the auto modes
v4l2-ctl -d "$DEV" --set-ctrl=auto_exposure=1                # 1 = Manual
v4l2-ctl -d "$DEV" --set-ctrl=exposure_dynamic_framerate=0   # hold 30fps
v4l2-ctl -d "$DEV" --set-ctrl=white_balance_automatic=0      # manual WB
v4l2-ctl -d "$DEV" --set-ctrl=focus_automatic_continuous=0   # manual focus

# The dialed-in values (edit here to retune)
v4l2-ctl -d "$DEV" --set-ctrl=exposure_time_absolute=300     # ~1/30s (100us units)
v4l2-ctl -d "$DEV" --set-ctrl=gain=120                       # dim-room gain
v4l2-ctl -d "$DEV" --set-ctrl=white_balance_temperature=3500 # Kelvin
v4l2-ctl -d "$DEV" --set-ctrl=focus_absolute=0               # 0 = far / infinity

# Local environment (50Hz mains; set to 2 for 60Hz regions)
v4l2-ctl -d "$DEV" --set-ctrl=power_line_frequency=1

echo "C920 controls applied."
EOF
    sudo chmod +x "$WEBCAM_BIN_DIR/apply_c920_controls.sh"
    # Whole ~/bin owned by the Pi user, same as the home-dir ownership fix.
    sudo chown -R 1000:1000 "$WEBCAM_BIN_DIR"

    # --- 9b. systemd unit ---------------------------------------------------
    # System unit dir, left root-owned (systemd ignores user-owned unit files).
    sudo tee "$MOUNT_ROOT/etc/systemd/system/vop-webcam.service" > /dev/null <<'EOF'
[Unit]
Description=VOP webcam livestream (C920 H.264 passthrough over SRT)
After=network.target

[Service]
Type=simple
User=vop
ExecStart=/usr/bin/ffmpeg -nostats -loglevel warning \
  -use_wallclock_as_timestamps 1 \
  -f v4l2 -input_format h264 -video_size 1280x720 -framerate 30 -i /dev/video0 \
  -c:v copy -f mpegts "srt://0.0.0.0:8890?mode=listener"
ExecStartPost=/bin/sleep 3
ExecStartPost=-/home/vop/bin/apply_c920_controls.sh
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF

    # --- 9c. Enable it offline ----------------------------------------------
    # Can't `systemctl enable` against an unbooted root, so create the WantedBy
    # symlink by hand. The link TARGET is the path the Pi will see (/etc/...),
    # NOT the host mount path -- it resolves at boot on the Pi.
    WANTS_DIR="$MOUNT_ROOT/etc/systemd/system/multi-user.target.wants"
    sudo mkdir -p "$WANTS_DIR"
    sudo ln -sf /etc/systemd/system/vop-webcam.service \
        "$WANTS_DIR/vop-webcam.service"
    echo "    vop-webcam.service installed and enabled (starts once ffmpeg is present)."
fi

###############################################################################
# Step 10 -- Clean unmount and final touches
###############################################################################
echo
echo "==> Unmounting and finalizing..."
cd "$HOME"
sudo umount "$MOUNT_BOOT" "$MOUNT_ROOT"
sync

# Clear the old SSH host key so 'ssh' doesn't complain after the new fingerprint.
ssh-keygen -R "$PI_EXPECTED_IP" 2>/dev/null || true

###############################################################################
# Done
###############################################################################
echo
echo "=================================================================="
echo "  Pre-deployment complete."
echo "=================================================================="
echo
echo "Next steps:"
echo "  1. Eject the stick from this machine."
echo "  2. Insert it into the Pi (no SD card present)."
echo "  3. Connect the Pi's ethernet to your switch/router."
echo "  4. Power on. Wait ~60 seconds for the first-boot filesystem resize."
if [ -n "$SSH_PUBKEY" ]; then
    echo "  5. SSH in (key auth):   ssh $PI_USERNAME@$PI_EXPECTED_IP"
else
    echo "  5. SSH in (password):   ssh $PI_USERNAME@$PI_EXPECTED_IP"
    echo "       (use the password you set; default is '12345')"
fi
echo "  6. On the Pi:"
echo "       sudo apt install git -y"
echo "       git clone https://codeberg.org/jmalmsten-com/VOP.git"
echo "       cd VOP"
echo "       chmod +x deploy_vop.sh"
echo "       ./deploy_vop.sh"
echo
