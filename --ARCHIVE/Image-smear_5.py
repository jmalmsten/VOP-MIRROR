"""
VOP Module:     Image-smear_5.py
Version:        v0.0.5
Description:    Multidimensional VOP Smear with Scaling.
                - Normalized coordinates, Rotation, and Scaling.
                - Smooth linear interpolation across all axes.
"""

import os
import time
import subprocess
import argparse
import pygame

def run_smear(image_name, offset_ms, smear_sec, gain, rot_start, rot_end, pos_start, pos_end, scale_start, scale_end):
    VERSION = "v0.0.5"
    PRO_MAG_DIR = os.path.expanduser("~/vop/ProjMag")
    
    SAFETY_BUFFER_MS = 500.0
    TOTAL_SMEAR_MS = float(smear_sec * 1000.0)
    EXPOSURE_MS = TOTAL_SMEAR_MS + (SAFETY_BUFFER_MS * 2)
    SHUTTER_US = int(EXPOSURE_MS * 1000)
    
    START_BLACK_1 = 1000.0 
    START_SMEAR   = START_BLACK_1 + SAFETY_BUFFER_MS
    START_BLACK_2 = START_SMEAR + TOTAL_SMEAR_MS
    END_ALL       = START_BLACK_2 + SAFETY_BUFFER_MS

    filename = f"ImageSmear_{VERSION}_{offset_ms}_{smear_sec}s_g{gain}.jpg"

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

    source_img = pygame.image.load(img_path).convert()
    
    x1, y1 = map(float, pos_start.split(','))
    x2, y2 = map(float, pos_end.split(','))
    
    anchor_time = time.time()
    captured = False
    running = True

    print(f"Running {VERSION} | Traversal + Rotation + Scaling")

    while running:
        elapsed = (time.time() - anchor_time) * 1000
        
        if elapsed > END_ALL + 2000:
            running = False
            continue

        if elapsed < START_SMEAR:
            color_bg = (0, 0, 0)
            show_image = False
        elif elapsed < START_BLACK_2:
            progress = (elapsed - START_SMEAR) / TOTAL_SMEAR_MS
            
            # 1. Translation (Position)
            curr_x = int((x1 + (progress * (x2 - x1))) * WIDTH)
            curr_y = int((y1 + (progress * (y2 - y1))) * HEIGHT)
            
            # 2. Scaling (Zoom)
            curr_scale = scale_start + (progress * (scale_end - scale_start))
            scaled_w = int(source_img.get_width() * curr_scale)
            scaled_h = int(source_img.get_height() * curr_scale)
            
            # Safety check: pygame doesn't like 0-pixel surfaces
            scaled_w = max(1, scaled_w)
            scaled_h = max(1, scaled_h)
            
            working_img = pygame.transform.scale(source_img, (scaled_w, scaled_h))
            
            # 3. Rotation
            current_rot = rot_start + (progress * (rot_end - rot_start))
            rotated_img = pygame.transform.rotate(working_img, current_rot)
            
            # 4. Center-aligned Blit
            rect = rotated_img.get_rect(center=(curr_x, curr_y))
            
            color_bg = (0, 0, 0)
            show_image = True
        else:
            color_bg = (0, 0, 0)
            show_image = False

        screen.fill(color_bg)
        if show_image:
            screen.blit(rotated_img, rect.topleft)
        pygame.display.update()

        trigger_target = START_BLACK_1 - offset_ms
        if not captured and elapsed >= trigger_target:
            cmd = [
                "rpicam-still", "-o", filename,
                "--shutter", str(SHUTTER_US),
                "--gain", str(gain),
                "--immediate", "--awbgains", "3.18,1.45", "-n"
            ]
            subprocess.Popen(cmd)
            captured = True

    pygame.quit()
    print(f"Done. File: {filename}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=str, required=True)
    parser.add_argument("--offset", type=int, default=718)
    parser.add_argument("--smear", type=float, default=8.0)
    parser.add_argument("--gain", type=float, default=1.0)
    parser.add_argument("--rot_start", type=float, default=0.0)
    parser.add_argument("--rot_end", type=float, default=0.0)
    parser.add_argument("--pos_start", type=str, default="0.5,0.5")
    parser.add_argument("--pos_end", type=str, default="0.5,0.5")
    parser.add_argument("--scale_start", type=float, default=1.0)
    parser.add_argument("--scale_end", type=float, default=1.0)
    args = parser.parse_args()
    
    run_smear(args.image, args.offset, args.smear, args.gain, 
              args.rot_start, args.rot_end, args.pos_start, args.pos_end,
              args.scale_start, args.scale_end)