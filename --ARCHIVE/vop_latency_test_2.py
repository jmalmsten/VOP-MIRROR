"""
VOP Module:     vop_latency_calibration.py
Version:        v0.0.3
Description:    Measures latency with a -1000 to +1000 countdown.
                The number captured in the photo is the direct offset.
"""

import os
import time
import subprocess
import pygame

def run_calibration():
    # --- Settings ---
    ANALOG_GAIN = 16.0
    SHUTTER_US = 10000 # 1/100s
    
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    pygame.init()
    info = pygame.display.Info()
    WIDTH, HEIGHT = info.current_w, info.current_h
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
    font = pygame.font.SysFont("monospace", 400, bold=True)
    
    # We want the '0' to happen 2 seconds into the script
    # So we define the 'base_time' as (current + 2 seconds)
    trigger_time = time.time() + 2.0
    
    captured = False
    running = True

    print("Calibrating... Look for the '+' value in the resulting image.")

    while running:
        current_time = time.time()
        # Relative time in MS compared to our 0-point trigger
        elapsed_ms = int((current_time - trigger_time) * 1000)
        
        # Formatting the string with a +/- sign
        prefix = "+" if elapsed_ms >= 0 else ""
        display_str = f"{prefix}{elapsed_ms:04d}"
        if elapsed_ms < 0:
            # Manually handle sign for negative numbers to avoid '-0001' vs '-1'
            display_str = f"{elapsed_ms:05d}" 

        screen.fill((30, 30, 30))
        txt = font.render(display_str, True, (255, 255, 255))
        text_rect = txt.get_rect(center=(WIDTH // 2, HEIGHT // 2))
        screen.blit(txt, text_rect)
        pygame.display.update()

        # Trigger exactly at the 0ms mark
        if elapsed_ms >= 0 and not captured:
            cmd = [
                "rpicam-still", "-o", "calibration_offset.jpg",
                "--shutter", str(SHUTTER_US),
                "--gain", str(ANALOG_GAIN),
                "--immediate", "--awbgains", "2.4,1.5", "-n"
            ]
            subprocess.Popen(cmd)
            print(f"DEBUG: Trigger command sent at internal 0ms.")
            captured = True
            
        # Stop 1 second after trigger
        if elapsed_ms > 1000:
            running = False
            
    pygame.quit()
    print("\nCapture Complete. Check 'calibration_offset.jpg'.")
    print("The number shown is your total pipeline latency in milliseconds.")

if __name__ == "__main__":
    run_calibration()