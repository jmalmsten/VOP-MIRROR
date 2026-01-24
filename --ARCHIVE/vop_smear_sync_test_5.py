"""
VOP Module:     vop_smear_sync_test_5.py
Version:        v0.0.5
Description:    Triple-lane sync test with pre-heat buffer, terminal blackout,
                and dynamic file naming for clinical tracking.
"""

import os
import time
import subprocess
import argparse
import pygame

def run_test(offset_ms, exposure_ms, gain):
    # --- Configuration ---
    VERSION = "v0.0.5"
    FPS = 60
    FRAME_MS = 1000.0 / FPS
    SHUTTER_US = int(exposure_ms * 1000)
    
    # Timing Phases (ms)
    PRE_HEAT_MS = 1000.0   # 1. New: Black screen for OS/ISP settling
    PHASE1_MS = 10.0 * FRAME_MS   # Lane 1: Top (Blind)
    PHASE2_MS = float(exposure_ms) # Lane 2: Middle (Exposure)
    PHASE3_MS = 10.0 * FRAME_MS   # Lane 3: Bottom (Blind)
    
    TOTAL_ANIM_MS = PHASE1_MS + PHASE2_MS + PHASE3_MS
    
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    pygame.init()
    pygame.mouse.set_visible(False)
    info = pygame.display.Info()
    WIDTH, HEIGHT = info.current_w, info.current_h
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
    
    square_size = 120
    
    # 2. Dynamic Filename Generation
    filename = f"{VERSION}_offset{offset_ms}_exp{exposure_ms}_gain{gain}.jpg"
    
    # Timing Logic
    # The actual animation starts AFTER the pre-heat
    script_start = time.time()
    anim_start_time = script_start + (PRE_HEAT_MS / 1000.0)
    
    captured = False
    running = True
    blackout_triggered = False

    print(f"Running {VERSION} | {filename}")

    while running:
        t = time.time()
        
        # Check if we are still in Pre-Heat
        if t < anim_start_time:
            screen.fill((0, 0, 0))
            pygame.display.update()
            continue

        elapsed_ms = (t - anim_start_time) * 1000
        
        # 3. Terminal Blackout Logic
        if elapsed_ms > TOTAL_ANIM_MS:
            if not blackout_triggered:
                screen.fill((0, 0, 0))
                pygame.display.update()
                blackout_triggered = True
            
            # Keep script alive to allow hardware integration to finish
            if elapsed_ms > TOTAL_ANIM_MS + 2000: # Extra buffer for 6s exposures
                running = False
            continue

        # Coordinate & Lane Logic (All White Squares)
        color = (255, 255, 255)

        if elapsed_ms < PHASE1_MS:
            # PHASE 1: Top Lane (Pre-roll)
            progress = elapsed_ms / PHASE1_MS
            pos_y = int(HEIGHT * 0.15)
        elif elapsed_ms < (PHASE1_MS + PHASE2_MS):
            # PHASE 2: Middle Lane (EXPOSURE)
            progress = (elapsed_ms - PHASE1_MS) / PHASE2_MS
            pos_y = int(HEIGHT * 0.5) - (square_size // 2)
        else:
            # PHASE 3: Bottom Lane (Post-roll)
            progress = (elapsed_ms - PHASE1_MS - PHASE2_MS) / PHASE3_MS
            pos_y = int(HEIGHT * 0.85) - square_size

        pos_x = int(progress * (WIDTH - square_size))

        # Rendering
        screen.fill((0, 0, 0))
        pygame.draw.rect(screen, color, (pos_x, pos_y, square_size, square_size))
        pygame.display.update()

        # 4. Trigger Logic (Fires relative to the middle lane start)
        trigger_target_ms = PHASE1_MS - offset_ms
        if elapsed_ms >= trigger_target_ms and not captured:
            cmd = [
                "rpicam-still", "-o", filename,
                "--shutter", str(SHUTTER_US),
                "--gain", str(gain),
                "--immediate", "--awbgains", "3.18,1.45", "-n"
            ]
            subprocess.Popen(cmd)
            print(f"CAM_TRIGGER: Sent at {int(elapsed_ms)}ms (Target: {int(trigger_target_ms)}ms)")
            captured = True

    pygame.quit()
    print(f"\nTest Complete. Output saved to {filename}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=700)
    parser.add_argument("--exposure", type=int, default=1000)
    parser.add_argument("--gain", type=float, default=1.0)
    args = parser.parse_args()
    
    run_test(args.offset, args.exposure, args.gain)