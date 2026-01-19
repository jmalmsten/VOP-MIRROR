"""
VOP Module:     vop_monochrome_stack.py
Version:        v0.1.0
Description:    Captures 3 monochrome passes using full Bayer resolution.
                Normalizes RGGB sensitivity (2,1,2) to maintain neutral input.
"""

import os
import time
import subprocess
import numpy as np
import rawpy
import imageio
import pygame
import colorsys

# --- Configuration ---
# Neutralizing the RGGB bias: Red and Blue get 2x to match the 2x Green pixels
BAYER_NORMALIZATION = [2.0, 1.0, 1.0, 2.0] # R, G1, G2, B
SHUTTER_US = 2000000 
WIDTH, HEIGHT = 1920, 1080
VOP_DIR = os.path.expanduser("~/vop")

def generate_hsv_channel_maps():
    """ Generates 3 grayscale images representing R, G, and B channel intensities. """
    print("Generating HSV channel maps...")
    hsv_full = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    
    for x in range(WIDTH):
        hue = x / WIDTH
        r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
        hsv_full[0:HEIGHT//2, x] = [int(r*255), int(g*255), int(b*255)]
    
    ramp = np.linspace(0, 255, WIDTH, dtype=np.uint8)
    hsv_full[HEIGHT//2:, :, 0] = ramp
    hsv_full[HEIGHT//2:, :, 1] = ramp
    hsv_full[HEIGHT//2:, :, 2] = ramp

    return hsv_full[:,:,0], hsv_full[:,:,1], hsv_full[:,:,2]

def capture_pass(channel_name, gray_map):
    """ Shows the grayscale map on screen and captures RAW. """
    print(f"\n[PHASE] Capturing {channel_name.upper()} monochrome pass...")
    
    # Display as Grayscale (R=G=B)
    display_img = np.stack([gray_map]*3, axis=-1)
    surf = pygame.surfarray.make_surface(display_img.swapaxes(0,1))
    screen.blit(surf, (0, 0))
    pygame.display.update()
    time.sleep(2.5) 

    dng_path = os.path.join(VOP_DIR, f"mono_{channel_name}.dng")
    cmd = [
        "rpicam-still", "-r", "-o", dng_path.replace(".dng", ".jpg"),
        "--shutter", str(SHUTTER_US), "--gain", "1", "--immediate",
        "--awbgains", "1.0,1.0", "-n"
    ]
    subprocess.run(cmd, check=True)
    return dng_path

def extract_monochrome_plate(dng_path):
    """
    Extracts the RAW mosaic and normalizes for Bayer bias.
    Returns a single 16-bit monochrome plate.
    """
    with rawpy.imread(dng_path) as raw:
        # Get raw 12-bit data
        data = raw.raw_image.astype(np.float32)
        
        # Apply 2,1,2 normalization to the Bayer grid (RGGB)
        # Assuming standard IMX477 Bayer order
        data[0::2, 0::2] *= BAYER_NORMALIZATION[0] # Red
        data[0::2, 1::2] *= BAYER_NORMALIZATION[1] # Green 1
        data[1::2, 0::2] *= BAYER_NORMALIZATION[2] # Green 2
        data[1::2, 1::2] *= BAYER_NORMALIZATION[3] # Blue

        # Demosaic into a high-quality monochrome plate
        # We use a neutral WB [1,1,1,1] because we normalized manually
        processed = raw.postprocess(user_wb=[1,1,1,1], no_auto_bright=True, 
                                   output_bps=16, demosaic_algorithm=rawpy.DemosaicAlgorithm.AHD)
        
        # Convert the processed RGB back to a single Luminosity channel (Grayscale)
        # Using the standard Rec.709 weights
        mono_plate = (0.2126 * processed[:,:,0] + 
                      0.7152 * processed[:,:,1] + 
                      0.0722 * processed[:,:,2])
        return mono_plate

# --- Main ---
if __name__ == "__main__":
    os.makedirs(VOP_DIR, exist_ok=True)
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    pygame.init()
    pygame.mouse.set_visible(False) 
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)

    try:
        r_map, g_map, b_map = generate_hsv_channel_maps()
        
        # 1. Capture the 3 "Film Strips"
        r_plate = extract_monochrome_plate(capture_pass("red", r_map))
        g_plate = extract_monochrome_plate(capture_pass("green", g_map))
        b_plate = extract_monochrome_plate(capture_pass("blue", b_map))

        # 2. Merge into Final Color Stack
        print("\n[MERGE] Reassembling color stack from normalized plates...")
        stacked = np.stack([r_plate, g_plate, b_plate], axis=-1)
        
        # Save as 16-bit TIFF
        out_path = os.path.join(VOP_DIR, "vop_bayer_normalized_stack.tiff")
        imageio.imwrite(out_path, np.clip(stacked, 0, 65535).astype(np.uint16))
        print(f"[SUCCESS] Final stack saved to: {out_path}")

    finally:
        pygame.quit()