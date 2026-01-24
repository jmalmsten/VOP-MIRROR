"""
VOP Module:     vop_latency_test_3.py
Version:        v0.0.3
Description:    Measures latency with Millisecond and Frame counters.
                Includes --offset and --fps arguments.
"""

import os
import time
import subprocess
import argparse
import pygame

def run_calibration(offset_ms, fps):
    # --- Settings ---
    ANALOG_GAIN = 16.0
    SHUTTER_US = 10000 # 1/100s
    FRAME_DURATION_MS = 1000.0 / fps
    
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    pygame.init()
    info = pygame.display.Info()
    WIDTH, HEIGHT = info.current_w, info.current_h
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
    
    # Fonts
    ms_font = pygame.font.SysFont("monospace", 300, bold=True)
    frame_font = pygame.font.SysFont("monospace", 150, bold=False)
    
    # The '0' happens 3 seconds in
    trigger_point = time.time() + 3.0
    
    captured = False
    running = True

    print(f"Calibrating: Offset {offset_ms}ms | FPS Target {fps}")

    while running:
        current_time = time.time()
        elapsed_ms = int((current_time - trigger_point) * 1000)
        
        # Calculate Frame Index relative to trigger (0)
        frame_idx = int(elapsed_ms / FRAME_DURATION_MS)
        
        # Millisecond Display Logic
        prefix_ms = "+" if elapsed_ms >= 0 else ""
        ms_str = f"{prefix_ms}{elapsed_ms:04d}" if elapsed_ms >= 0 else f"{elapsed_ms:05d}"

        # Frame Display Logic
        prefix_fr = "F+" if frame_idx >= 0 else "F"
        frame_str = f"{prefix_fr}{frame_idx}"

        screen.fill((30, 30, 30))
        
        # Render MS Counter (Large)
        ms_txt = ms_font.render(ms_str, True, (255, 255, 255))
        ms_rect = ms_txt.get_rect(center=(WIDTH // 2, HEIGHT // 2 - 50))
        screen.blit(ms_txt, ms_rect)
        
        # Render Frame Counter (Smaller, below MS)
        fr_txt = frame_font.render(frame_str, True, (0, 255, 0) if frame_idx == 0 else (200, 200, 200))
        fr_rect = fr_txt.get_rect(center=(WIDTH // 2, HEIGHT // 2 + 200))
        screen.blit(fr_txt, fr_rect)
        
        pygame.display.update()

        # TRIGGER LOGIC
        if elapsed_ms >= -offset_ms and not captured:
            cmd = [
                "rpicam-still", "-o", "calibration_offset.jpg",
                "--shutter", str(SHUTTER_US),
                "--gain", str(ANALOG_GAIN),
                "--immediate", "--awbgains", "2.4,1.5", "-n"
            ]
            subprocess.Popen(cmd)
            print(f"SYSTEM: Command issued at logical MS: {elapsed_ms} | Frame: {frame_idx}")
            captured = True
            
        if elapsed_ms > 1000:
            running = False
            
    pygame.quit()
    print("\nCapture Complete. Check 'calibration_offset.jpg'.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset", type=int, default=0, help="Pre-roll offset in ms")
    parser.add_argument("--fps", type=float, default=60.0, help="Monitor refresh rate")
    args = parser.parse_args()
    run_calibration(args.offset, args.fps)