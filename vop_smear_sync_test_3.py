"""
VOP Module:     vop_smear_sync_test_3.py
Version:        v0.0.3
Description:    Triple-lane latency stress test. 
                Lane 1: Top (10 frames, Blind)
                Lane 2: Middle (Exposure ms, Active)
                Lane 3: Bottom (10 frames, Blind)
"""

import os
import time
import subprocess
import argparse
import pygame

def run_test(offset_ms, exposure_ms, gain):
    # --- Configuration ---
    FPS = 60
    FRAME_MS = 1000.0 / FPS
    SHUTTER_US = int(exposure_ms * 1000)
    
    # Timing Phases
    PHASE1_MS = 10.0 * FRAME_MS  # Fixed 10 frames
    PHASE2_MS = float(exposure_ms)
    PHASE3_MS = 10.0 * FRAME_MS  # Fixed 10 frames
    TOTAL_ANIM_MS = PHASE1_MS + PHASE2_MS + PHASE3_MS
    
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

    print(f"Smear v0.0.5 | Shutter: {exposure_ms}ms | Gain: {gain}")
    print(f"Sync: Target Middle Lane. Top/Bottom lanes are 10-frame buffers.")

    while running:
        t = time.time()
        elapsed_ms = (t - start_time) * 1000
        
        if elapsed_ms > TOTAL_ANIM_MS:
            running = False
            continue

        # 1. Coordinate & Lane Logic
        if elapsed_ms < PHASE1_MS:
            # LANE 1: Top Third (Pre-roll, 10 frames)
            progress = elapsed_ms / PHASE1_MS
            pos_y = int(HEIGHT * 0.15)
            color = (100, 100, 100) # Dim gray
        elif elapsed_ms < (PHASE1_MS + PHASE2_MS):
            # LANE 2: Middle (EXPOSURE, variable duration)
            progress = (elapsed_ms - PHASE1_MS) / PHASE2_MS
            pos_y = int(HEIGHT * 0.5) - (square_size // 2)
            color = (255, 255, 255) # Pure white
        else:
            # LANE 3: Bottom Third (Post-roll, 10 frames)
            progress = (elapsed_ms - PHASE1_MS - PHASE2_MS) / PHASE3_MS
            pos_y = int(HEIGHT * 0.85) - square_size
            color = (100, 100, 100) # Dim gray

        pos_x = int(progress * (WIDTH - square_size))

        # 2. Rendering
        screen.fill((0, 0, 0))
        pygame.draw.rect(screen, color, (pos_x, pos_y, square_size, square_size))
        pygame.display.update()

        # 3. Trigger Logic
        # Fire exactly at the start of Phase 2, minus the pre-roll offset
        if elapsed_ms >= (PHASE1_MS - offset_ms) and not captured:
            cmd = [
                "rpicam-still", "-o", "smear_v5_tri_lane.jpg",
                "--shutter", str(SHUTTER_US),
                "--gain", str(gain),
                "--immediate", "--awbgains", "3.18,1.45", "-n"
            ]
            subprocess.Popen(cmd)
            captured = True

    # Keep display alive while sensor finishes integration
    time.sleep(1.5)
    pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=680)
    parser.add_argument("--exposure", type=int, default=1000)
    parser.add_argument("--gain", type=float, default=2.0)
    args = parser.parse_args()
    
    run_test(args.offset, args.exposure, args.gain)