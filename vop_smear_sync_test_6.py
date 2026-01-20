"""
VOP Module:     vop_smear_sync_test_6.py
Version:        v0.0.6
Description:    Uses SIGUSR1 signal to trigger rpicam-still. This eliminates
                process-start lag and ISP negotiation delays.
"""

import os
import time
import subprocess
import argparse
import pygame
import signal

def run_test(offset_ms, exposure_ms, gain):
    VERSION = "v0.0.6"
    FPS = 60
    FRAME_MS = 1000.0 / FPS
    SHUTTER_US = int(exposure_ms * 1000)
    
    # Phases
    PRE_HEAT_MS = 2000.0   # 2s to allow camera to stabilize
    PHASE1_MS = 10.0 * FRAME_MS
    PHASE2_MS = float(exposure_ms)
    PHASE3_MS = 10.0 * FRAME_MS
    TOTAL_ANIM_MS = PHASE1_MS + PHASE2_MS + PHASE3_MS
    
    filename = f"{VERSION}_off{offset_ms}_exp{exposure_ms}_gain{gain}.jpg"

    # 1. Start the camera in SIGNAL mode immediately
    # It will sit and wait for SIGUSR1
    cmd = [
        "rpicam-still", "-t", "0", "-o", filename,
        "--shutter", str(SHUTTER_US),
        "--gain", str(gain),
        "--immediate", "--awbgains", "3.18,1.45",
        "--signal", "-n"
    ]
    cam_proc = subprocess.Popen(cmd)
    print(f"CAMERA: Process spawned, warming up (PID: {cam_proc.pid})")

    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    pygame.init()
    pygame.mouse.set_visible(False)
    screen = pygame.display.set_mode((0,0), pygame.FULLSCREEN)
    WIDTH, HEIGHT = screen.get_size()
    
    square_size = 120
    anim_start_time = time.time() + (PRE_HEAT_MS / 1000.0)
    
    captured = False
    running = True

    while running:
        t = time.time()
        
        if t < anim_start_time:
            screen.fill((0, 0, 0))
            pygame.display.update()
            continue

        elapsed_ms = (t - anim_start_time) * 1000
        
        if elapsed_ms > TOTAL_ANIM_MS + 2000:
            running = False
            continue

        # Coordinate Logic
        if elapsed_ms < PHASE1_MS:
            p, y = elapsed_ms / PHASE1_MS, 0.15
        elif elapsed_ms < (PHASE1_MS + PHASE2_MS):
            p, y = (elapsed_ms - PHASE1_MS) / PHASE2_MS, 0.5
        elif elapsed_ms < TOTAL_ANIM_MS:
            p, y = (elapsed_ms - PHASE1_MS - PHASE2_MS) / PHASE3_MS, 0.85
        else:
            p, y = 1.0, 2.0 # Move off screen

        pos_x = int(p * (WIDTH - square_size))
        pos_y = int(y * HEIGHT) - (square_size // 2)

        screen.fill((0, 0, 0))
        if y < 1.0:
            pygame.draw.rect(screen, (255,255,255), (pos_x, pos_y, square_size, square_size))
        pygame.display.update()

        # 2. TRIGGER via SIGNAL
        trigger_target_ms = PHASE1_MS - offset_ms
        if elapsed_ms >= trigger_target_ms and not captured:
            os.kill(cam_proc.pid, signal.SIGUSR1)
            print(f"SIGUSR1 SENT AT: {int(elapsed_ms)}ms")
            captured = True

    # 3. Cleanup
    time.sleep(1) # Final buffer
    cam_proc.terminate()
    pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--exposure", type=int, default=1000)
    parser.add_argument("--gain", type=float, default=1.0)
    args = parser.parse_args()
    run_test(args.offset, args.exposure, args.gain)