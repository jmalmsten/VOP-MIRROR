"""
VOP Module:     vop_smear_sync_test_7.py
Version:        v0.0.7
Description:    Restores the high-stability "Cold Start" trigger logic from 
                v0.0.4 while maintaining triple-lane and blackout features.
"""

import os
import time
import subprocess
import argparse
import pygame

def run_test(offset_ms, exposure_ms, gain):
    VERSION = "v0.0.7"
    FPS = 60
    FRAME_MS = 1000.0 / FPS
    SHUTTER_US = int(exposure_ms * 1000)
    
    # Timing Phases (ms)
    PRE_HEAT_MS = 1000.0          # Black buffer for OS stability
    PHASE1_MS = 10.0 * FRAME_MS   # Lane 1: Top (Blind)
    PHASE2_MS = float(exposure_ms) # Lane 2: Middle (Exposure)
    PHASE3_MS = 10.0 * FRAME_MS   # Lane 3: Bottom (Blind)
    TOTAL_ANIM_MS = PHASE1_MS + PHASE2_MS + PHASE3_MS
    
    filename = f"{VERSION}_off{offset_ms}_exp{exposure_ms}_gain{gain}.jpg"

    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    pygame.init()
    pygame.mouse.set_visible(False)
    info = pygame.display.Info()
    WIDTH, HEIGHT = info.current_w, info.current_h
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
    
    square_size = 120
    
    # Sync start time AFTER pygame init
    start_point = time.time()
    anim_start_time = start_point + (PRE_HEAT_MS / 1000.0)
    
    captured = False
    running = True
    blackout_active = False

    print(f"Running {VERSION} | Offset: {offset_ms} | Exp: {exposure_ms}")

    while running:
        t = time.time()
        
        # 1. Pre-Heat Phase
        if t < anim_start_time:
            screen.fill((0, 0, 0))
            pygame.display.update()
            continue

        elapsed_ms = (t - anim_start_time) * 1000
        
        # 2. Terminal Blackout Logic
        if elapsed_ms > TOTAL_ANIM_MS:
            if not blackout_active:
                screen.fill((0, 0, 0))
                pygame.display.update()
                blackout_active = True
            
            # Shutter cleanup: wait long enough for sensor to close
            if elapsed_ms > TOTAL_ANIM_MS + 2000:
                running = False
            continue

        # 3. Coordinate & Lane Logic
        if elapsed_ms < PHASE1_MS:
            # PHASE 1: Top (10 frames)
            progress = elapsed_ms / PHASE1_MS
            pos_y = int(HEIGHT * 0.15)
        elif elapsed_ms < (PHASE1_MS + PHASE2_MS):
            # PHASE 2: Middle (Exposure)
            progress = (elapsed_ms - PHASE1_MS) / PHASE2_MS
            pos_y = int(HEIGHT * 0.5) - (square_size // 2)
        else:
            # PHASE 3: Bottom (10 frames)
            progress = (elapsed_ms - PHASE1_MS - PHASE2_MS) / PHASE3_MS
            pos_y = int(HEIGHT * 0.85) - square_size

        pos_x = int(progress * (WIDTH - square_size))

        # 4. Rendering
        screen.fill((0, 0, 0))
        pygame.draw.rect(screen, (255, 255, 255), (pos_x, pos_y, square_size, square_size))
        pygame.display.update()

        # 5. Cold Start Trigger Logic (Proven Method)
        trigger_target_ms = PHASE1_MS - offset_ms
        if elapsed_ms >= trigger_target_ms and not captured:
            cmd = [
                "rpicam-still", "-o", filename,
                "--shutter", str(SHUTTER_US),
                "--gain", str(gain),
                "--immediate", "--awbgains", "3.18,1.45", "-n"
            ]
            subprocess.Popen(cmd)
            print(f"TRIGGER: Process spawned at {int(elapsed_ms)}ms")
            captured = True

    pygame.quit()
    print(f"Finished. File: {filename}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=680)
    parser.add_argument("--exposure", type=int, default=1000)
    parser.add_argument("--gain", type=float, default=1.0)
    args = parser.parse_args()
    run_test(args.offset, args.exposure, args.gain)