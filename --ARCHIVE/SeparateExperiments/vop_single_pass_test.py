"""
VOP Module:     vop_single_pass_test.py
Version:        v0.0.1
Description:    Single-pass full-color capture. 
                Used to determine if grayscale tinting is a temporal stacking artifact.
"""

import os
import time
import numpy as np
import subprocess
import pygame
import imageio

# --- Configuration (Synced with your Clinical Script) ---
HOME             = os.path.expanduser("~")
VOP_DIR          = os.path.join(HOME, "vop")
SHUTTER_SPEED    = "2000000"  # 2 seconds
WIDTH, HEIGHT    = 1920, 1080

def generate_sawtooth_pattern():
    """ Creates the Sawtooth experiment pattern for single-pass viewing. """
    print("Generating Sawtooth pattern...")
    image = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    mid = WIDTH // 2

    # Top Half: Linear Sawtooth Ramps (Red -> Green -> Blue)
    for x in range(WIDTH):
        r = max(0, 255 - int((x / mid) * 255)) if x < mid else 0
        g = 255 - int(abs(x - mid) / mid * 255)
        b = max(0, int(((x - mid) / mid) * 255)) if x >= mid else 0
        image[0:HEIGHT//2, x, 0] = r
        image[0:HEIGHT//2, x, 1] = g
        image[0:HEIGHT//2, x, 2] = b

    # Bottom Half: Grayscale Linear Ramp
    ramp = np.linspace(0, 255, WIDTH, dtype=np.uint8)
    image[HEIGHT//2:, :, 0] = ramp
    image[HEIGHT//2:, :, 1] = ramp
    image[HEIGHT//2:, :, 2] = ramp
    return image

def run_single_pass(source_img):
    pygame.init()
    pygame.mouse.set_visible(False)
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)

    # Display the full color pattern
    surf = pygame.surfarray.make_surface(source_img.swapaxes(0, 1))
    screen.blit(surf, (0, 0))
    pygame.display.update()
    
    print("  [DISPLAY] Full Color Pattern. Stabilizing (2s)...")
    time.sleep(2)

    # Capture Single Full-Color Image
    print("  [CAPTURE] 2-Second Full Color Exposure...")
    output_path = os.path.join(VOP_DIR, "single_pass_capture.jpg")
    cmd = [
        "rpicam-still", "-r", 
        "-o", output_path,
        "--shutter", SHUTTER_SPEED, 
        "--gain", "1", 
        "--immediate",
        "--awbgains", "1.0,1.0" # Keeps raw math neutral
    ]
    subprocess.run(cmd, check=True)
    
    pygame.quit()
    print(f"\n[SUCCESS] Single-pass capture saved: {output_path}")

if __name__ == "__main__":
    source = generate_sawtooth_pattern()
    run_single_pass(source)