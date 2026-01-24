"""
VOP Module:     vop_smear_sync_test_8.py
Version:        v0.0.8
Description:    RESTORATION VERSION. Uses the exact timing anchor of v0.0.4.
                Triple-lane sync with Pre-Heat and Terminal Blackout.
"""

import os
import time
import subprocess
import argparse
import pygame

def run_test(offset_ms, exposure_ms, gain):
    # --- Configuration ---
    VERSION = "v0.0.8"
    FPS = 60
    FRAME_MS = 1000.0 / FPS
    SHUTTER_US = int(exposure_ms * 1000)
    
    # Timing Phases (ms) - All measured from ONE anchor
    PRE_HEAT_MS = 1000.0
    PHASE1_MS   = 10.0 * FRAME_MS
    PHASE2_MS   = float(exposure_ms)
    PHASE3_MS   = 10.0 * FRAME_MS
    
    # The Milestone Markers
    START_LANE1 = PRE_HEAT_MS
    START_LANE2 = START_LANE1 + PHASE1_MS
    START_LANE3 = START_LANE2 + PHASE2_MS
    END_ALL     = START_LANE3 + PHASE3_MS
    
    filename = f"{VERSION}_off{offset_ms}_exp{exposure_ms}_gain{gain}.jpg"

    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    pygame.init()
    pygame.mouse.set_visible(False)
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    WIDTH, HEIGHT = screen.get_size()
    square_size = 120
    
    # --- THE MAGIC ANCHOR ---
    # Like v0.0.4, we take ONE time and never adjust it.
    anchor_time = time.time()
    
    captured = False
    running = True

    print(f"Running {VERSION} | Anchor set. Shutter: {exposure_ms}ms")

    while running:
        # Calculate current 'now' relative ONLY to the anchor
        elapsed = (time.time() - anchor_time) * 1000
        
        if elapsed > END_ALL + 2000: # 2s buffer for hardware integration
            running = False
            continue

        # 1. Coordinate & Lane Logic
        if elapsed < START_LANE1:
            # PRE-HEAT: Black screen
            pos_y = -500 # Off-screen
            color = (0, 0, 0)
            progress = 0
        elif elapsed < START_LANE2:
            # PHASE 1: Top Lane
            progress = (elapsed - START_LANE1) / PHASE1_MS
            pos_y = int(HEIGHT * 0.15)
            color = (255, 255, 255)
        elif elapsed < START_LANE3:
            # PHASE 2: Middle Lane (EXPOSURE)
            progress = (elapsed - START_LANE2) / PHASE2_MS
            pos_y = int(HEIGHT * 0.5) - (square_size // 2)
            color = (255, 255, 255)
        elif elapsed < END_ALL:
            # PHASE 3: Bottom Lane
            progress = (elapsed - START_LANE3) / PHASE3_MS
            pos_y = int(HEIGHT * 0.85) - square_size
            color = (255, 255, 255)
        else:
            # BLACKOUT: Immediately clear
            pos_y = -500
            color = (0, 0, 0)
            progress = 0

        pos_x = int(progress * (WIDTH - square_size))

        # 2. Rendering
        screen.fill((0, 0, 0))
        if pos_y > 0:
            pygame.draw.rect(screen, color, (pos_x, pos_y, square_size, square_size))
        pygame.display.update()

        # 3. THE TRIGGER (The v0.0.4 logic)
        # We fire relative to the anchor-based 'elapsed' time
        if not captured and elapsed >= (START_LANE2 - offset_ms):
            cmd = [
                "rpicam-still", "-o", filename,
                "--shutter", str(SHUTTER_US),
                "--gain", str(gain),
                "--immediate", "--awbgains", "3.18,1.45", "-n"
            ]
            subprocess.Popen(cmd)
            captured = True

    pygame.quit()
    print(f"Success. File: {filename}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=680)
    parser.add_argument("--exposure", type=int, default=1000)
    parser.add_argument("--gain", type=float, default=1.0)
    args = parser.parse_args()
    run_test(args.offset, args.exposure, args.gain)