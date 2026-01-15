"""
VOP Module: dark_frame_analyzer.py
Version: v0.0.3
Description:    Accounts for Pi5 16-bit scaling and provides 12-bit normalized values

Version: v0.0.2
Description:    Extracts 12-bit RAW data from DNG to calculate sensor noise floor.

Version: v0.0.1
Description:    Captures a dark frame at clinical settings and calculates
                the sensor's noise floor (Mean and Standard Deviation)
"""

import numpy as np
import rawpy
# We Use 'rpicam' libraries if available, or call the system command
import subprocess
import os

def capture_dark_frame(output_path):
    """
    Triggers a clinical-grade dark capture.
    --shutter 2 000 000 (2 seconds)
    --gain 1 (base ISO 100)
    --raw (To get the DNG for analysis)
    """
    print("Capturing 2-second dark frame... (Keep the lens cap on!)")
    
    # Using the system call to ensure we get the exact 12-bit RAW data
    cmd = [
        "rpicam-still",
        "-r",
        "-o", output_path,
        "--shutter", "2000000",
        "--gain", "1",
        "--immediate"
    ]
    subprocess.run(cmd, check=True)
    return output_path.replace("jpg", "dng")

def analyze_noise(dng_path):
    """
    Opens the DNG and analyzes the raw 12-bit pixel values.
    """
    if not os.path.exists(dng_path):
        print(f"Error: Could not find DNG at {dng_path}")
        return
    print(f"Analyzing RAW data from: {dng_path}")

    with rawpy.imread(dng_path) as raw:
        # raw_image is the 2d array of Bayer pixels
        data_16bit = raw.raw_image.astype(np.float32)
        
        # Normalize to 12-bit (0-4095) 
        # 16-bit is 0-65535. Dividing by 16 gives us the sensor's native scale
        data_12bit = data_16bit / 16.0


        mean_val     = np.mean(data_12bit)
        std_dev     = np.std(data_12bit)
        max_val     = np.max(data_12bit)

        print("-" * 35)
        print(f"SENSOR ANALYSIS (Normalized to 12-bit)")
        print("=" * 35)
        print(f"Noise Floor (Mean): {mean_val:.4} - We expect Mean to be ~256 (the standard black pedestal)")
        print(f"Grain Intensity (StdDev): {std_dev:.4f} - StdDev is the 'true' noise/grain. Lower is better")
        print(f"Brightest Hot Pixel: {max_val} - Max shows the brightest 'hot' or 'stuck' pixel found")
        print("-" * 35)

        # Logic check for the 'Blue Glow' or Light Leaks
        if mean_val > 270:
            print("Status: Elevated thermal glow detected. (Check cooling).")
        else:
            print("Status: Clinical Black Level Verified.")

if __name__ == "__main__":
    # Target directory on the Pi
    file_base= "/home/admininja/dark_test_003.jpg"

    # Execute the capture
    dng_file = capture_dark_frame(file_base)

    # Run the analysis
    analyze_noise(dng_file)