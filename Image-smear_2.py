"""
VOP Module:     Image-smear_2.py
Version:        v0.0.2
Description:    Moves a lineart bitmap across the screen with "Overscan".
                Allows full-screen images to glide from off-screen left
                to off-screen right over the exposure duration.
"""

import os
import time
import subprocess
import argparse
import pygame

def run_smear(image_name, offset_ms, smear_ms, gain):
    # --- Configuration ---
    VERSION = "v0.0.2"
    PRO_MAG_DIR = os.path.expanduser("~/vop/ProjMag")
    
    # Timing Phases (ms)
    SAFETY_BUFFER_MS = 500.0
    TOTAL_SMEAR_MS = float(smear_ms)
    EXPOSURE_MS = TOTAL_SMEAR_MS + (SAFETY_BUFFER_MS * 2)
    SHUTTER_US = int(EXPOSURE_MS * 1000)
    
    # Milestone Markers
    START_BLACK_1 = 1000.0 
    START_SMEAR   = START_BLACK_1 + SAFETY_BUFFER_MS
    START_BLACK_2 = START_SMEAR + TOTAL_SMEAR_MS
    END_ALL       = START_BLACK_2 + SAFETY_BUFFER_MS

    filename = f"ImageSmear_{VERSION}_{offset_ms}_{EXPOSURE_MS}_{gain}.jpg"

    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    pygame.init()
    pygame.mouse.set_visible(False)
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    WIDTH, HEIGHT = screen.get_size()

    img_path = os.path.join(PRO_MAG_DIR, image_name)
    if not os.path.exists(img_path):
        print(f"ERROR: File {img_path} not found.")
        pygame.quit()
        return

    # Load image
    target_img = pygame.image.load(img_path).convert()
    img_w, img_h = target_img.get_size()
    
    # --- THE MAGIC ANCHOR ---
    anchor_time = time.time()
    
    captured = False
    running = True

    print(f"Running {VERSION} | Traversal: {-img_w} to {WIDTH}")

    while running:
        elapsed = (time.time() - anchor_time) * 1000
        
        if elapsed > END_ALL + 2000:
            running = False
            continue

        # Coordinate & Phase Logic
        if elapsed < START_SMEAR:
            color_bg = (0, 0, 0)
            show_image = False
        elif elapsed < START_BLACK_2:
            # ACTIVE SMEAR
            progress = (elapsed - START_SMEAR) / TOTAL_SMEAR_MS
            
            # OVERSCAN MATH: 
            # Start at -img_w (hidden left) and end at WIDTH (hidden right)
            pos_x = int(-img_w + (progress * (WIDTH + img_w)))
            pos_y = (HEIGHT // 2) - (img_h // 2)
            
            color_bg = (0, 0, 0)
            show_image = True
        else:
            color_bg = (0, 0, 0)
            show_image = False

        # Rendering
        screen.fill(color_bg)
        if show_image:
            # Pygame handles negative coordinates by clipping automatically
            screen.blit(target_img, (pos_x, pos_y))
        pygame.display.update()

        # Trigger Logic
        trigger_target = START_BLACK_1 - offset_ms
        if not captured and elapsed >= trigger_target:
            cmd = [
                "rpicam-still", "-o", filename,
                "--shutter", str(SHUTTER_US),
                "--gain", str(gain),
                "--immediate", "--awbgains", "3.18,1.45", "-n"
            ]
            subprocess.Popen(cmd)
            print(f"CAMERA: Triggered at {int(elapsed)}ms")
            captured = True

    pygame.quit()
    print(f"Done. File: {filename}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=str, required=True)
    parser.add_argument("--offset", type=int, default=718)
    parser.add_argument("--smear", type=int, default=8000)
    parser.add_argument("--gain", type=float, default=1.0)
    args = parser.parse_args()
    
    run_smear(args.image, args.offset, args.smear, args.gain)