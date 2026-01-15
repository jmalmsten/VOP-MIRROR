# 🎞️ VOP Studio v0.0.1 Cheat Sheet

This document covers the workflow and command set for the **Virtual Optical Printer** (VOP) studio engine.

---

## 🛠️ The Studio Engine (`VOP_orchestrator.py`)
Launch the engine with `python3 VOP_orchestrator.py`. The engine uses an HDMI handshake to auto-detect resolution and pre-loads all masks into RAM.

| Command | Usage Example | Description |
| :--- | :--- | :--- |
| **`status`** | `status` | Reports current resolution, optical calibration, and a list of images in RAM. |
| **`test`** | `test 15` | Projects a 10-step grayscale ramp for X seconds. Use to calibrate `BLACK_CLIP`. |
| **`snap`** | `snap` | Projects the first frame of the sheet and saves a 16-bit technical TIFF. |
| **`dry`** | `dry` | **Looping Preview.** Plays the animation/smears on HDMI. Hit [ENTER] to stop. |
| **`run`** | `run` | **Production Pass.** Captures and stacks every frame into 16-bit TIFFs. |
| **`reload`** | `reload` | Re-reads `config.txt` and refreshes `Projector/` RAM cache live. |
| **`help`** | `help` | Displays the internal command list. |
| **`q`** | `q` | Safely shuts down Pygame and the hardware worker processes. |

> **Note:** For `dry`, `run`, and `snap`, if no filename is provided, the engine defaults to `x-sheet_filled.csv`.

---

## 📋 The Guiding X-Sheet (`x-sheet.csv`)
This is your "Keyframe" sheet. Edit this in **LibreOffice Calc** or **VisiData**. 

| Column | Unit | Description |
| :--- | :--- | :--- |
| **`frame`** | Int | The frame number (e.g., 1, 24, 48). |
| **`image`** | String | Filename of the mask (must be in `Projector/` folder). |
| **`[corner]_x_start`** | 0.0-1.0 | Corner position at the **start** of the shutter. |
| **`[corner]_y_start`** | 0.0-1.0 | Corner position at the **start** of the shutter. |
| **`[corner]_x_end`** | 0.0-1.0 | Corner position at the **end** of the shutter (The Smear). |
| **`color_hex`** | HEX | Virtual Gel color (e.g., `#0000FF` for blue). |
| **`exposure`** | Abs | Camera shutter speed (v4l2 value). |
| **`focus`** | Abs | Camera focus motor position. |



---

## ⚙️ Master Configuration (`config.txt`)
Global hardware and optical settings. Use the `reload` command in the CLI to apply changes without restarting.

| Key | Default | Description |
| :--- | :--- | :--- |
| **`BLACK_CLIP`** | `0.03` | Remaps monitor blacks to 0.0. Increase to kill backlight glow. |
| **`GAMMA`** | `1.0` | Adjusts contrast. >1.0 "crunches" midtones for cleaner masks. |
| **`GLOBAL_BRIGHTNESS`**| `1.0` | Master fader for projection intensity. |
| **`DEFAULT_DURATION`** | `0.5` | How long (in seconds) the smear lasts per frame. |
| **`CAMERA_DEVICE`** | `/dev/video0`| The Linux path to your camera hardware. |



---

## 🚀 Standard Production Workflow

1.  **Compose:** Edit `x-sheet.csv` to set your keyframes and colors.
2.  **Compile:** Run `python3 x-sheet_gen.py`. This auto-detects your masks and bakes the interpolation.
3.  **Calibrate:** Use `test` and `reload` to tune your `BLACK_CLIP` and `GAMMA`.
4.  **Verify:** Run `dry` to see the loop. Run `snap` to check the actual camera sensor result.
5.  **Execute:** Run `run` to capture the final sequence.

---
*VOP Studio - Version v0.0.1 - 2025-12-31*