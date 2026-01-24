"""
VOP Module:     vop_smear_sync_test.py
Version:        v0.0.4
Description:    Locked Spatial-Temporal Smear. Square traverses exactly 
                one screen width during the shutter duration.
"""

import os
import time
import subprocess
import argparse
import pygame

def run_test(offset_ms, exposure_ms, gain):
    # --- Configuration ---
    SHUTTER_US = int(exposure_ms * 1000)
    
    # Timing Phases (ms)
    PRE_WAIT_MS = 1000.0   # Top lane movement before exposure
    POST_WAIT_MS = 1000.0  # Top lane movement after exposure
    TOTAL_ANIM_MS = PRE_WAIT_MS + exposure_ms + POST_WAIT_MS
    
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    pygame.init()
    pygame.mouse.set_visible(False)
    info = pygame.display.Info()
    WIDTH, HEIGHT = info.current_w, info.current_h
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
    
    square_size = 120
    start_time = time.time()
    captured = False
    running = True

    print(f"Smear v0.0.4 | Exposure: {exposure_ms}ms | Gain: {gain} | Offset: {offset_ms}ms")

    while running:
        t = time.time()
        elapsed_ms = (t - start_time) * 1000
        
        if elapsed_ms > TOTAL_ANIM_MS:
            running = False
            continue

        # 1. Spatial-Temporal Logic
        # The square traverses the width [0.0 to 1.0] during the EXPOSURE phase.
        if elapsed_ms < PRE_WAIT_MS:
            # PHASE 1: Top Lane (Pre-roll)
            progress = elapsed_ms / PRE_WAIT_MS
            pos_y = int(HEIGHT * 0.2)
            color = (80, 80, 80)
        elif elapsed_ms < (PRE_WAIT_MS + exposure_ms):
            # PHASE 2: Bottom Lane (Active Exposure)
            # Progress resets to 0.0 at the start of exposure and hits 1.0 at the end
            progress = (elapsed_ms - PRE_WAIT_MS) / exposure_ms
            pos_y = int(HEIGHT * 0.7)
            color = (255, 255, 255)
        else:
            # PHASE 3: Top Lane (Post-roll)
            progress = (elapsed_ms - PRE_WAIT_MS - exposure_ms) / POST_WAIT_MS
            pos_y = int(HEIGHT * 0.2)
            color = (80, 80, 80)

        pos_x = int(progress * (WIDTH - square_size))

        # 2. Rendering
        screen.fill((0, 0, 0))
        pygame.draw.rect(screen, color, (pos_x, pos_y, square_size, square_size))
        pygame.display.update()

        # 3. Trigger Logic
        # Fired at PRE_WAIT_MS minus the offset
        if elapsed_ms >= (PRE_WAIT_MS - offset_ms) and not captured:
            cmd = [
                "rpicam-still", "-o", "smear_v4_locked.jpg",
                "--shutter", str(SHUTTER_US),
                "--gain", str(gain),
                "--immediate", "--awbgains", "3.18,1.45", "-n"
            ]
            subprocess.Popen(cmd)
            captured = True

    # 4. Cleanup Delay
    # We wait an extra second before quitting Pygame to ensure the 
    # hardware shutter has physically closed before the screen goes black.
    time.sleep(1.0)
    pygame.quit()
    print("\nTest Complete. Smear is now spatially locked to the shutter duration.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=680)
    parser.add_argument("--exposure", type=int, default=1000)
    parser.add_argument("--gain", type=float, default=2.0)
    args = parser.parse_args()
    
    run_test(args.offset, args.exposure, args.gain)