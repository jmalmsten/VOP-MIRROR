"""
VOP Module:     vop_smear_sync_test_4.py
Version:        v0.0.4
Description:    Triple-lane latency test with Terminal Blackout.
                Prevents "static burn-in" of the final square by clearing
                the screen immediately after the third lane finishes.
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
    
    # Timing Phases (ms)
    PHASE1_MS = 10.0 * FRAME_MS  # Lane 1: Top (Blind)
    PHASE2_MS = float(exposure_ms) # Lane 2: Middle (Exposure)
    PHASE3_MS = 10.0 * FRAME_MS  # Lane 3: Bottom (Blind)
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
    blackout_triggered = False

    print(f"Smear v0.0.6 | Shutter: {exposure_ms}ms | Gain: {gain}")
    print(f"Applying Terminal Blackout to prevent 'static burn' in final frame.")

    while running:
        t = time.time()
        elapsed_ms = (t - start_time) * 1000
        
        # 1. Terminal Blackout Check
        if elapsed_ms > TOTAL_ANIM_MS:
            if not blackout_triggered:
                screen.fill((0, 0, 0))
                pygame.display.update()
                blackout_triggered = True
            
            # Keep the loop alive for a moment to let the camera finish
            if elapsed_ms > TOTAL_ANIM_MS + 1000:
                running = False
            continue

        # 2. Coordinate & Lane Logic
        # All lanes are now full white (255) for maximum photon count
        color = (255, 255, 255)

        if elapsed_ms < PHASE1_MS:
            # LANE 1: Top (Pre-roll)
            progress = elapsed_ms / PHASE1_MS
            pos_y = int(HEIGHT * 0.15)
        elif elapsed_ms < (PHASE1_MS + PHASE2_MS):
            # LANE 2: Middle (ACTIVE)
            progress = (elapsed_ms - PHASE1_MS) / PHASE2_MS
            pos_y = int(HEIGHT * 0.5) - (square_size // 2)
        else:
            # LANE 3: Bottom (Post-roll)
            progress = (elapsed_ms - PHASE1_MS - PHASE2_MS) / PHASE3_MS
            pos_y = int(HEIGHT * 0.85) - square_size

        pos_x = int(progress * (WIDTH - square_size))

        # 3. Rendering
        screen.fill((0, 0, 0))
        pygame.draw.rect(screen, color, (pos_x, pos_y, square_size, square_size))
        pygame.display.update()

        # 4. Trigger Logic
        if elapsed_ms >= (PHASE1_MS - offset_ms) and not captured:
            cmd = [
                "rpicam-still", "-o", "smear_v6_blackout.jpg",
                "--shutter", str(SHUTTER_US),
                "--gain", str(gain),
                "--immediate", "--awbgains", "3.18,1.45", "-n"
            ]
            subprocess.Popen(cmd)
            captured = True

    # Ensure the script ends cleanly
    pygame.quit()
    print("\nTest Complete. Terminal Blackout applied.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=680)
    parser.add_argument("--exposure", type=int, default=1000)
    parser.add_argument("--gain", type=float, default=2.0)
    args = parser.parse_args()
    
    run_test(args.offset, args.exposure, args.gain)