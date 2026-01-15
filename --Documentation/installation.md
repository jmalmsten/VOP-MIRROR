# VOP Studio Installation & Setup Guide (v0.1.0)

This guide provides the complete, step-by-step instructions to set up the **Virtual Optical Printer** (VOP) on a fresh install of **Raspberry Pi OS Lite (64-bit)**. 

The system is designed for "bare-metal" execution using **KMS/DRM** to ensure precise timing and direct hardware control without the overhead of a desktop environment.

## 1. System Permissions
The VOP engine requires direct access to the GPU for projection and the ISP for camera capture. You must add your user to the hardware groups.

```bash
# Add user to hardware groups
sudo usermod -aG video,render $USER
```
NOTE: You must reboot or log out and back in for these permissions to take effect.
## 2. System-Level Dependencies

Install the low-level SDL2 drivers for HDMI output and the v4l-utils suite for hardware-level camera control (focus, exposure, white balance).

```bash
sudo apt update
sudo apt install -y libsdl2-2.0-0 libsdl2-image-2.0-0 libsdl2-mixer-2.0-0 libsdl2-ttf-2.0-0 v4l-utils
```

## 3. Python Environment

To ensure hardware acceleration on the Raspberry Pi 5, we use the system-packaged versions of OpenCV and Pygame. This avoids performance issues found in standard pip installs on ARM architecture.

```bash
sudo apt install -y python3-opencv python3-pygame
```
## 4. Project Directory Structure

After cloning the repository, the following directory structure must be present. The "Cerebrum" (VOP.py) will attempt to initialize these if they are missing.
Bash

# Create the studio environment
mkdir -p Projector bipack FilmMag modules

- Projector/: Place your source mask images (slides) here.
- bipack/: Folder for secondary masking layers and traveling mattes.
- FilmMag/: The "Film Magazine" where 16-bit latent TIFFs are stacked and stored.
- modules/: Contains the modular Python logic (config_engine.py, xsheet_engine.py, etc.).

## 5. Master Configuration (config.txt)

Create a file named config.txt in the root directory. This file acts as the "Optical Calibration" sheet for the printer.
Plaintext

```
# Hardware Handshake
SCREEN_WIDTH=1920
SCREEN_HEIGHT=1080
CAMERA_DEVICE=/dev/video0

# Optical Settings
BLACK_CLIP=0.03
GAMMA=1.0
GLOBAL_BRIGHTNESS=1.0

# Printer Logic
DEFAULT_DURATION=0.5
VSYNC_PULL=0.01
FILM_MAG=FilmMag
PROJECTOR_DIR=Projector
```

## 6. Hardware Verification

Once the environment is set up, run the main controller to verify that the HDMI and Camera handshakes are successful.
Bash

```bash
python3 VOP.py
```

Inside the VOP CLI, run a test pattern:


Plaintext
```
VOP > test 5
```

- **Success:** A 10-step grayscale ramp appears on the monitor for 5 seconds.

Next. You can try entering 

```
status
```
This reports the current set projection resolution and lists images in your Projector/ folder.

## 7. Troubleshooting

**Black Screen:** Ensure your monitor is powered on before running the script. KMS/DRM requires a valid EDID handshake at startup.

**Permission Denied:** Ensure you have rebooted after running the usermod command in Step 1.

**Camera Not Found:** Check that the camera ribbon cable is seated correctly and that CAMERA_DEVICE in config.txt matches your /dev/videoX path.