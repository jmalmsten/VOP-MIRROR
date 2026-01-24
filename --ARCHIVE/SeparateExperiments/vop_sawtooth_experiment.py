"""
VOP Module:     vop_sawtooth_experiment.py
Version:        v0.0.1
Description:    Experiment to visualize the 'Brightness Valley'.
                Uses linear sawtooth ramps instead of HSV math.
"""

import os
import time
import numpy as np
import rawpy
import subprocess
import pygame
import imageio

# --- Configuration (Kept from your Clinical Script) ---
HOME             = os.path.expanduser("~")
VOP_DIR          = os.path.join(HOME, "vop")
AWB_GAINS        = (2.65, 1.0, 1.26) 
SHUTTER_SPEED    = "2000000"  # 2 seconds
WIDTH, HEIGHT    = 1920, 1080

def generate_sawtooth_source():
    """ Creates a source image where colors peak and drop linearly. """
    print("Generating Sawtooth experiment pattern...")
    image = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    mid = WIDTH // 2

    # Top Half: Linear Sawtooth Ramps
    for x in range(WIDTH):
        # Red peaks at 0, drops to 0 at mid
        r = max(0, 255 - int((x / mid) * 255)) if x < mid else 0
        # Green peaks at mid, drops to 0 at edges
        g = 255 - int(abs(x - mid) / mid * 255)
        # Blue peaks at end, drops to 0 at mid
        b = max(0, int(((x - mid) / mid) * 255)) if x >= mid else 0

        image[0:HEIGHT//2, x, 0] = r
        image[0:HEIGHT//2, x, 1] = g
        image[0:HEIGHT//2, x, 2] = b

    # Bottom Half: Standard Grayscale Ramp (for reference)
    ramp = np.linspace(0, 255, WIDTH, dtype=np.uint8)
    image[HEIGHT//2:, :, 0] = ramp
    image[HEIGHT//2:, :, 1] = ramp
    image[HEIGHT//2:, :, 2] = ramp

    return image

def run_capture_sequence(source_img):
    pygame.init()
    pygame.mouse.set_visible(False)
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)

    dng_files = {}
    labels = ['red', 'green', 'blue']

    for i, color in enumerate(labels):
        screen.fill((0, 0, 0))
        pygame.display.update()
        time.sleep(1.0)

        # Show only the current channel
        display_surface = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        display_surface[:, :, i] = source_img[:, :, i]

        surf = pygame.surfarray.make_surface(display_surface.swapaxes(0, 1))
        screen.blit(surf, (0, 0))
        pygame.display.update()
        
        print(f"  [DISPLAY] {color.upper()} Sawtooth...")
        time.sleep(2)

        output_path = os.path.join(VOP_DIR, f"exp_stack_{color}.jpg")
        cmd = ["rpicam-still", "-r", "-o", output_path, "--shutter", SHUTTER_SPEED, "--gain", "1", "--immediate"]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
        dng_files[color] = output_path.replace(".jpg", ".dng")

    pygame.quit()
    return dng_files

# --- The Stacker (Simplified for this experiment) ---
def merge_experiment(dng_map):
    print("\nMerging Sawtooth Experiment...")
    final_channels = []
    color_order = ['red', 'green', 'blue']
    
    for i, color in enumerate(color_order):
        with rawpy.imread(dng_map[color]) as raw:
            # Basic develop (Neutral)
            processed = raw.postprocess(user_wb=[1,1,1,1], no_auto_bright=True, output_bps=16)
            clean_channel = processed[:, :, i].astype(np.float32) * AWB_GAINS[i]
            final_channels.append(clean_channel)
    
    stacked = np.stack(final_channels, axis=-1)
    final_image = np.clip(stacked, 0, 65535).astype(np.uint16)
    out_path = os.path.join(VOP_DIR, "sawtooth_experiment.tiff")
    imageio.imwrite(out_path, final_image)
    print(f"[SUCCESS] Experiment saved: {out_path}")

if __name__ == "__main__":
    source = generate_sawtooth_source()
    files = run_capture_sequence(source)
    merge_experiment(files)