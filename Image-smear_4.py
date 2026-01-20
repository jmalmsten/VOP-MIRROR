"""
VOP Module:     Image-smear_4.py
Version:        v0.0.4
Description:    Multidimensional VOP Smear. 
                - Normalized coordinates (0.0 - 1.0) for start/end positions.
                - Rotation interpolation.
                - Smear duration defined in floating-point seconds.
"""

import os
import time
import subprocess
import argparse
import pygame

def run_smear(image_name, offset_ms, smear_sec, gain, rot_start, rot_end, pos_start, pos_end):
    # --- Configuration ---
    VERSION = "v0.0.4"
    PRO_MAG_DIR = os.path.expanduser("~/vop/ProjMag")
    
    # Timing Phases (Convert seconds to ms for internal logic)
    SAFETY_BUFFER_MS = 500.0
    TOTAL_SMEAR_MS = float(smear_sec * 1000.0)
    EXPOSURE_MS = TOTAL_SMEAR_MS + (SAFETY_BUFFER_MS * 2)
    SHUTTER_US = int(EXPOSURE_MS * 1000)
    
    # Milestone Markers
    START_BLACK_1 = 1000.0 
    START_SMEAR   = START_BLACK_1 + SAFETY_BUFFER_MS
    START_BLACK_2 = START_SMEAR + TOTAL_SMEAR_MS
    END_ALL       = START_BLACK_2 + SAFETY_BUFFER_MS

    # Filename uses float smear seconds
    filename = f"ImageSmear_{VERSION}_{offset_ms}_{smear_sec}s_{gain}.jpg"

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
    
    # Parse Coordinates (Comma separated string to float tuple)
    x1, y1 = map(float, pos_start.split(','))
    x2, y2 = map(float, pos_end.split(','))
    
    # --- THE MAGIC ANCHOR ---
    anchor_time = time.time()
    captured = False
    running = True

    print(f"Running {VERSION} | Traversal: ({x1},{y1}) to ({x2},{y2}) over {smear_sec}s")

    while running:
        elapsed = (time.time() - anchor_time) * 1000
        
        if elapsed > END_ALL + 2000:
            running = False
            continue

        # Phase Logic
        if elapsed < START_SMEAR:
            color_bg = (0, 0, 0)
            show_image = False
        elif elapsed < START_BLACK_2:
            # ACTIVE SMEAR
            progress = (elapsed - START_SMEAR) / TOTAL_SMEAR_MS
            
            # Linear Interpolation of Normalized Coordinates
            curr_x_norm = x1 + (progress * (x2 - x1))
            curr_y_norm = y1 + (progress * (y2 - y1))
            
            # Convert Normalized to Pixel Coordinates (Targeting Image Center)
            target_x = int(curr_x_norm * WIDTH)
            target_y = int(curr_y_norm * HEIGHT)
            
            # Rotation Math
            current_rot = rot_start + (progress * (rot_end - rot_start))
            rotated_img = pygame.transform.rotate(source_img, current_rot)
            
            # Center the rotated surface on our calculated target point
            rect = rotated_img.get_rect(center=(target_x, target_y))
            
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
    parser.add_argument("--smear", type=float, default=8.0) # Floating point seconds
    parser.add_argument("--gain", type=float, default=1.0)
    parser.add_argument("--rot_start", type=float, default=0.0)
    parser.add_argument("--rot_end", type=float, default=0.0)
    parser.add_argument("--pos_start", type=str, default="0.5,0.0") # x,y
    parser.add_argument("--pos_end", type=str, default="0.5,1.0")   # x,y
    args = parser.parse_args()
    
    run_smear(args.image, args.offset, args.smear, args.gain, 
              args.rot_start, args.rot_end, args.pos_start, args.pos_end)