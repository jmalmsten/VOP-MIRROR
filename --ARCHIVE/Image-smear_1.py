"""
VOP Module:     Image-smear_1.py
Version:        v0.0.1
Description:    Moves a lineart bitmap from ~/vop/ProjMag across the screen.
                Uses a 500ms Black Buffer before and after the 8s smear
                to act as a temporal safety shutter.
"""

import os
import time
import subprocess
import argparse
import pygame

def run_smear(image_name, offset_ms, smear_ms, gain):
    # --- Configuration ---
    VERSION = "v0.0.1"
    # Corrected Path: ProjMag is inside the vop folder
    PRO_MAG_DIR = os.path.expanduser("~/vop/ProjMag")
    
    # Timing Phases (ms)
    SAFETY_BUFFER_MS = 500.0   # Black frame buffer
    TOTAL_SMEAR_MS = float(smear_ms)
    # The camera shutter needs to be open for the whole sequence + safety
    EXPOSURE_MS = TOTAL_SMEAR_MS + (SAFETY_BUFFER_MS * 2)
    SHUTTER_US = int(EXPOSURE_MS * 1000)
    
    # Milestone Markers (from anchor)
    START_BLACK_1 = 1000.0 # Initial wait for OS stabilization
    START_SMEAR   = START_BLACK_1 + SAFETY_BUFFER_MS
    START_BLACK_2 = START_SMEAR + TOTAL_SMEAR_MS
    END_ALL       = START_BLACK_2 + SAFETY_BUFFER_MS

    filename = f"ImageSmear_{VERSION}_{offset_ms}_{EXPOSURE_MS}_{gain}.jpg"

    # Initialize Pygame
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    pygame.init()
    pygame.mouse.set_visible(False)
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    WIDTH, HEIGHT = screen.get_size()

    # Load Lineart from ~/vop/ProjMag
    img_path = os.path.join(PRO_MAG_DIR, image_name)
    if not os.path.exists(img_path):
        print(f"ERROR: File {img_path} not found.")
        pygame.quit()
        return

    # Load image and get dimensions for centering
    target_img = pygame.image.load(img_path).convert()
    img_w, img_h = target_img.get_size()
    
    # --- THE MAGIC ANCHOR ---
    anchor_time = time.time()
    
    captured = False
    running = True

    print(f"Running {VERSION} | Loading: {image_name}")
    print(f"Exposure: {EXPOSURE_MS}ms (8s smear + 1s safety)")

    while running:
        elapsed = (time.time() - anchor_time) * 1000
        
        if elapsed > END_ALL + 2000:
            running = False
            continue

        # Coordinate & Phase Logic
        if elapsed < START_SMEAR:
            # First Safety Buffer (Black)
            color_bg = (0, 0, 0)
            show_image = False
        elif elapsed < START_BLACK_2:
            # ACTIVE SMEAR
            progress = (elapsed - START_SMEAR) / TOTAL_SMEAR_MS
            # Move from far left to far right
            pos_x = int(progress * (WIDTH - img_w))
            pos_y = (HEIGHT // 2) - (img_h // 2)
            color_bg = (0, 0, 0)
            show_image = True
        else:
            # Second Safety Buffer (Black)
            color_bg = (0, 0, 0)
            show_image = False

        # Rendering
        screen.fill(color_bg)
        if show_image:
            screen.blit(target_img, (pos_x, pos_y))
        pygame.display.update()

        # Trigger Logic (Trigger relative to the START of the 9s exposure sequence)
        trigger_target = START_BLACK_1 - offset_ms
        if not captured and elapsed >= trigger_target:
            cmd = [
                "rpicam-still", "-o", filename,
                "--shutter", str(SHUTTER_US),
                "--gain", str(gain),
                "--immediate", "--awbgains", "3.18,1.45", "-n"
            ]
            subprocess.Popen(cmd)
            print(f"CAMERA: Shutter opened at {int(elapsed)}ms")
            captured = True

    pygame.quit()
    print(f"Done. Smear captured to {filename}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=str, required=True, help="Image file in ~/vop/ProjMag")
    parser.add_argument("--offset", type=int, default=718)
    parser.add_argument("--smear", type=int, default=8000)
    parser.add_argument("--gain", type=float, default=1.0)
    args = parser.parse_args()
    
    run_smear(args.image, args.offset, args.smear, args.gain)