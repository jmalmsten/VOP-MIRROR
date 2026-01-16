"""
VOP Module:     monitor_spectrometer.py
Version:        v0.0.1
Description:    Displays pure RGB colors on HDMI and captures RAW frames
                to calculate perfect White Balance gains for this monitor.
"""

import os
import time
import numpy as np
import rawpy
import subprocess
import pygame

# Portable Path Discovery
HOME = os.path.expanduser("~")
VOP_DIR = os.path.join(HOME, "vop")
# We'll save these to a subfolder to keep the main vop folder clean
CALIB_DIR = os.path.join(VOP_DIR, "calib_frames")

def capture_color(r, g, b, label):
    """ Fills the HDMI screen with color and snaps a RAW frame. """
    if not os.path.exists(CALIB_DIR):
        os.makedirs(CALIB_DIR)
    
    # 1. Initialize Pygame screen
    pygame.init()
    # Opens a fullscreen window on the primary HDMI output
    screen = pygame.display.set_mode((0,0), pygame.FULLSCREEN)
    screen.fill((r, g, b))
    pygame.display.update()

    # Wait 2 seconds for the monitor's IPS/LCD panel to reach full brightness
    time.sleep(2)

    # 2. Capture (Using your confirmed 2-second clinical exposure)
    print(f"  [CAPTURE] Measuring sensor response for: {label}...")
    output_path = os.path.join(CALIB_DIR, f"spec_{label}.jpg")
    cmd = [
        "rpicam-still", "-r",
        "-o", output_path,
        "--shutter", "2000000", 
        "--gain", "1", 
        "--immediate"
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)

    pygame.quit()
    return output_path.replace(".jpg", ".dng")

def calculate_gains(files):
    """ Analyzes the RAW captures to find the perfect multipliers """
    results = {}    
    print("\nAnalyzing RAW data...")
    for label, path in files.items():
        with rawpy.imread(path) as raw:
            # Get 12-bit normalized data
            data = raw.raw_image.astype(np.float32) / 16.0
            h, w = data.shape
            # Sample a 200x200 patch from the center to avoid lens vignetting
            crop = data[h//2-100:h//2+100, w//2-100:w//2+100]

            results[label] = np.mean(crop)
    
    # Calculate ratios relative to Green (the sensor's anchor)
    g_val  = results['green']
    r_gain = g_val / results['red']
    b_gain = g_val / results['blue']

    print("\n" + "="*40)
    print("  MONITOR SPECTROMETER RESULTS  ")
    print("\n" + "="*40) 
    print(f"RED   Channel Intensity: {results['red']:.2f} ")
    print(f"GREEN Channel Intensity: {results['green']:.2f}")
    print(f"BLUE  Channel Intensity: {results['blue']:.2f}")
    print("-" * 40)
    print(f"SUGGESTED AWB GAINS: {r_gain:.2f}, 1.0, {b_gain:.2f}")
    print("="*40)
    print("Copy these gains into your clinical_capture.py script.")    

if __name__ == "__main__":
    # Execute the sequence
    try:
        dng_files = {
            'red':      capture_color(255, 0, 0, "RED"),
            'green':    capture_color(0, 255, 0, "GREEN"),
            'blue':     capture_color(0, 0, 255, "BLUE")
        }
        calculate_gains(dng_files)
    except Exception as e:
        print(f"ERROR: {e}")
        pygame.quit()