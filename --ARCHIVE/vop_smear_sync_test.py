"""
VOP Module:     vop_smear_sync_test.py
Version:        v0.0.1
Description:    Teleportation sync test. Moves a square across the screen,
                switching lanes during the 40-frame exposure window.
"""

import os
import time
import subprocess
import argparse
import pygame

def run_test(offset_ms):
    # --- Settings ---
    FPS = 60
    FRAME_MS = 1000.0 / FPS
    TOTAL_FRAMES = 60
    EXPOSURE_FRAMES = 40
    START_EXPOSURE_FRAME = 10
    
    # Gain 8.0 (~ISO 800) for a cleaner noise floor check
    ANALOG_GAIN = 8.0
    # 40 frames at 60fps = 666,666 microseconds
    SHUTTER_US = int(EXPOSURE_FRAMES * FRAME_MS * 1000)
    
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    pygame.init()
    info = pygame.display.Info()
    WIDTH, HEIGHT = info.current_w, info.current_h
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
    
    square_size = 80
    
    # 0. Sync Clock Setup
    # Script starts 2 seconds of 'idle' time before the 1-second animation starts
    start_time = time.time() + 2.0
    captured = False
    running = True

    print(f"Starting Smear Sync Test... (Offset: {offset_ms}ms)")

    while running:
        t = time.time()
        # Relative time in MS since animation start
        elapsed_ms = (t - start_time) * 1000
        frame_idx = int(elapsed_ms / FRAME_MS)

        if frame_idx >= TOTAL_FRAMES:
            running = False
            continue

        # 1. Coordinate Logic
        # Linear horizontal movement
        pos_x = int((frame_idx / TOTAL_FRAMES) * (WIDTH - square_size))
        
        # Determine "Lane" (Vertical Pos)
        if START_EXPOSURE_FRAME <= frame_idx < (START_EXPOSURE_FRAME + EXPOSURE_FRAMES):
            # LANE: BOTTOM HALF (Exposure Zone)
            pos_y = int(HEIGHT * 0.7)
            color = (255, 255, 255) # White
        else:
            # LANE: TOP THIRD (Hidden Zone)
            pos_y = int(HEIGHT * 0.2)
            color = (150, 150, 150) # Gray (to detect leakages easily)

        # 2. Rendering
        screen.fill((10, 10, 10)) # Very dark gray floor
        pygame.draw.rect(screen, color, (pos_x, pos_y, square_size, square_size))
        
        # Optional: Add a frame counter overlay for debug
        # font = pygame.font.SysFont("monospace", 30)
        # txt = font.render(f"F:{frame_idx}", True, (50, 50, 50))
        # screen.blit(txt, (20, 20))
        
        pygame.display.update()

        # 3. Trigger Logic
        # We target the trigger to land exactly at Frame 10.
        # So we fire at (10 frames in MS) - (pre-roll offset)
        trigger_target_ms = (START_EXPOSURE_FRAME * FRAME_MS) - offset_ms
        
        if elapsed_ms >= trigger_target_ms and not captured:
            cmd = [
                "rpicam-still", "-o", "smear_test_result.jpg",
                "--shutter", str(SHUTTER_US),
                "--gain", str(ANALOG_GAIN),
                "--immediate", "--awbgains", "3.18,1.45", "-n"
            ]
            subprocess.Popen(cmd)
            print(f"TRIGGER: Shutter fired at frame {frame_idx} ({int(elapsed_ms)}ms)")
            captured = True

    pygame.quit()
    print("\nTest Complete. Inspect 'smear_test_result.jpg'.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=700, help="Latency pre-roll")
    args = parser.parse_args()
    run_test(args.offset)