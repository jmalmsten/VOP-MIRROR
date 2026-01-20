"""
VOP Module:     Image-smear_3.py
Version:        v0.0.3
Description:    Moves and rotates a lineart bitmap across the screen.
                Traversal: Off-screen Left to Off-screen Right.
                Rotation: Linear interpolation between rot_start and rot_end.
"""

import os
import time
import subprocess
import argparse
import pygame

def run_smear(image_name, offset_ms, smear_ms, gain, rot_start, rot_end):
    # --- Configuration ---
    VERSION = "v0.0.3"
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

    # Filename now uses active smear_ms per request
    filename = f"ImageSmear_{VERSION}_{offset_ms}_{int(smear_ms)}_{gain}.jpg"

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
    source_img = pygame.image.load(img_path).convert()
    img_w, img_h = source_img.get_size()
    
    # --- THE MAGIC ANCHOR ---
    anchor_time = time.time()
    
    captured = False
    running = True

    print(f"Running {VERSION} | Rotation: {rot_start} to {rot_end}")

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
            
            # Traversal Math (Overscan)
            pos_x = int(-img_w + (progress * (WIDTH + img_w)))
            pos_y_center = HEIGHT // 2
            
            # Rotation Math
            current_rot = rot_start + (progress * (rot_end - rot_start))
            
            # Rotate the image (Note: rotate is CCW, negative values for CW)
            rotated_img = pygame.transform.rotate(source_img, current_rot)
            
            # Center the rotated surface on our coordinate
            rect = rotated_img.get_rect(center=(pos_x + (img_w // 2), pos_y_center))
            
            color_bg = (0, 0, 0)
            show_image = True
        else:
            color_bg = (0, 0, 0)
            show_image = False

        # Rendering
        screen.fill(color_bg)
        if show_image:
            screen.blit(rotated_img, rect.topleft)
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
    parser.add_argument("--rot_start", type=float, default=0.0)
    parser.add_argument("--rot_end", type=float, default=0.0)
    args = parser.parse_args()
    
    # Corrected function call name
    run_smear(args.image, args.offset, args.smear, args.gain, args.rot_start, args.rot_end)