"""
VOP Module:     triple_stack_test.py
Version:        v0.1.0
Description:    Bayer-aware stacking. Extracts specific physical pixels per pass.
                Includes UI fixes (hidden cursor, blackout-intervals)
                Uses Calibrated Gains: (2.65, 1.0, 1.26)
"""

import os
import time
import numpy as np
import rawpy
import subprocess
import pygame
import imageio
import colorsys

# --- Configuration ---
HOME             = os.path.expanduser("~")
VOP_DIR          = os.path.join(HOME, "vop")
CALIB_DIR        = os.path.join(VOP_DIR, "calib_frames")
MASTER_DARK_PATH = os.path.join(VOP_DIR, "master_dark_2s_g1.npy")

# SPECTROMETER CALIBRATED GAINS (From last run)
AWB_GAINS = (2.65, 1.0, 1.26) # Red, Green, Blue
SHUTTER_SPEED = "2000000"   # 2 seconds

# HDMI Resolution targets
WIDTH, HEIGHT = 1920, 1080

# Ensure directories exist
os.makedirs(CALIB_DIR, exist_ok=True)

# --- PART 1: The Generator ---
def generate_source_tiff():
    """ Creates the Color/Grayscale ramp test image."""
    print("Generating source test pattern...")
    image = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)

    # Top Half: Color Spectrum Ramp (HSV -> RGB)
    for x in range(WIDTH):
        hue = x / WIDTH # 0.0 to 1.0
        r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        image[0:HEIGHT//2, x, 0] = int(r * 255)
        image[0:HEIGHT//2, x, 1] = int(g * 255)
        image[0:HEIGHT//2, x, 2] = int(b * 255)

    # Bottom Half: Grayscale Linear Ramp
    ramp = np.linspace(0, 255, WIDTH, dtype=np.uint8)
    image[HEIGHT//2:, :, 0] = ramp
    image[HEIGHT//2:, :, 1] = ramp
    image[HEIGHT//2:, :, 2] = ramp

    source_path = os.path.join(CALIB_DIR, "source_ramp.tiff")
    imageio.imwrite(source_path, image)
    print(f"Source pattern saved: {source_path}")
    return image

# --- PART 2: Display & Capture ---
def run_capture_sequence(source_img):
    """ Handles the full R-G-B sequence without dropping back to terminal. """
    pygame.init()
    pygame.mouse.set_visible(False) # Hide cursor
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)

    dng_files = {}
    labels = ['red', 'green', 'blue']

    for i, color in enumerate(labels):
        # 1. Clear to Black (Black-out interval)
        screen.fill((0, 0, 0))
        pygame.display.update()
        time.sleep(1.0)

        # 2. Display the specific channel
        display_surface = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        display_surface[:, :, i] = source_img[:, :, i]

        surf = pygame.surfarray.make_surface(display_surface.swapaxes(0, 1))
        screen.blit(surf, (0, 0))
        pygame.display.update()
        print(f"  [DISPLAY] Showing {color.upper()} pass. Stabilizing (2s)...")
        time.sleep(2)

        # 3. Capture
        print(f"  [CAPTURE] Exposing {color.upper()}...")
        output_path = os.path.join(VOP_DIR, f"tmp_stack_{color}.jpg")
        cmd = [
            "rpicam-still", "-r", 
            "-o", output_path,
            "--shutter", SHUTTER_SPEED, 
            "--gain", "1", 
            "--immediate"
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)
        dng_files[color] = output_path.replace(".jpg", ".dng")

    # Final Blackout before closing
    screen.fill((0,0,0))
    pygame.display.update()
    time.sleep(1)
    pygame.quit()
    return dng_files

# --- PART 3: The Stacker ---
def merge_stack_clinical(dng_map):
    """ Performs Bayer-aware channel extraction and clinical merging. """
    print("\nProcessing and Merging Channels...")
    
    # Load Master Dark
    if os.path.exists(MASTER_DARK_PATH):
        dark_map = np.load(MASTER_DARK_PATH)
        print("  Loaded Master Dark for subtraction.")
    else:
        print("  [WARNING] Master Dark not found.")
        dark_map = 0

    final_channels = []
    color_order = ['red', 'green', 'blue']
    
    for i, color in enumerate(color_order):
        print(f"  Extracting {color.upper()} channel...")
        dng_path = dng_map[color]
        
        with rawpy.imread(dng_path) as raw:
            # 1. Get RAW 12-bit data
            data = raw.raw_image.astype(np.float32) / 16.0

            # 2. Clinical Subtraction
            data = np.maximum(data - dark_map, 0)

            # Inject cleaned data back into the raw object for high-quality demosaicing
            raw.raw_image[:] = (data * 16).astype(np.uint16)

            # 3. Bayer Extraction
            # We develop the frame but we will ONLY keep the channel that was actually projected.
            processed = raw.postprocess(
                user_wb=[1,1,1,1], # Neutral weights
                no_auto_bright=True,
                output_bps=16,
                demosaic_algorithm=rawpy.DemosaicAlgorithm.AAHD
            )

            # Extract just the channel matching our current pass
            clean_channel = processed[:, :, i].astype(np.float32)
            
            # 4. Apply Calibrated AWB Gain
            clean_channel *= AWB_GAINS[i]
            final_channels.append(clean_channel)
    
    # 5. Final Stack (Merging R, G, and B into one 3D array)
    stacked = np.stack(final_channels, axis=-1)

    # 6. Final Scale to 16-bit
    final_image = np.clip(stacked, 0, 65535).astype(np.uint16)

    out_path = os.path.join(VOP_DIR, "triple_stack_clinical_v010.tiff")
    imageio.imwrite(out_path, final_image)
    print(f"\n[SUCCESS] Clinical Triple-Stack saved: {out_path}")

    # Cleanup temp files
    print("Cleaning up temporary files...")
    for f in dng_map.values():
        if os.path.exists(f): os.remove(f)
        jpg = f.replace(".dng", ".jpg")
        if os.path.exists(jpg): os.remove(jpg)

if __name__ == "__main__":
    # 1. Generate Source
    source = generate_source_tiff()

    # 2. Perform the 3-pass Capture Sequence
    try:
        captured_data = run_capture_sequence(source)

        # 3. Merge Channels
        merge_stack_clinical(captured_data)

    except Exception as e:
        print(f"An error occurred during the sequence: {e}")
        pygame.quit()