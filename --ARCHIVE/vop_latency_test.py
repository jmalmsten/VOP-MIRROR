"""
VOP Module:     vop_latency_test.py
Version:        v0.0.2
Description:    Measures system latency with high analogue gain.
                Uses a 1/100s shutter to ensure visibility on LCDs.
"""

import os
import time
import subprocess
import pygame

def run_latency_test():
    # --- Configuration ---
    TARGET_TRIGGER_MS = 2000
    # Analog gain 16 is the physical limit for the IMX477 without digital noise
    ANALOG_GAIN = 16 
    # 10000 microseconds = 1/100s. Fast enough to freeze, slow enough to see.
    SHUTTER_US = 10000 
    
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    pygame.init()
    
    # Get physical resolution
    info = pygame.display.Info()
    WIDTH, HEIGHT = info.current_w, info.current_h
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
    
    # Large font for easy reading in the capture
    font = pygame.font.SysFont("monospace", 400, bold=True)
    
    print(f"Starting latency counter. Triggering at {TARGET_TRIGGER_MS}ms...")
    
    start_time = time.time()
    captured = False
    running = True

    while running:
        # Calculate milliseconds since script start
        elapsed = int((time.time() - start_time) * 1000)
        
        # Display: Dark Gray background (helps sensor) with White text
        screen.fill((40, 40, 40)) 
        txt = font.render(f"{elapsed:04d}", True, (255, 255, 255))
        
        # Center the text
        text_rect = txt.get_rect(center=(WIDTH // 2, HEIGHT // 2))
        screen.blit(txt, text_rect)
        pygame.display.update()

        # Trigger at the target millisecond
        if elapsed >= TARGET_TRIGGER_MS and not captured:
            # We use Popen so the script doesn't freeze during the save
            cmd = [
                "rpicam-still",
                "-o", "latency_result.jpg",
                "--shutter", str(SHUTTER_US),
                "--gain", str(ANALOG_GAIN),
                "--immediate",
                "--awbgains", "2.4,1.5", # Use your validated "Daylight" gains
                "-n"
            ]
            subprocess.Popen(cmd)
            print(f"SYSTEM TRIGGER ISSUED AT: {elapsed}ms")
            captured = True
            
        # Give it a second to finish the save before closing
        if elapsed > (TARGET_TRIGGER_MS + 1000):
            running = False
            
    pygame.quit()
    print("\nTest Complete. Inspect 'latency_result.jpg'.")
    print(f"LATENCY = (Number in Photo) - {TARGET_TRIGGER_MS}")

if __name__ == "__main__":
    run_latency_test()