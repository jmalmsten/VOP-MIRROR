"""
VOP Module: master_dark_generator.py
Version: v0.0.1
Description: Averages multiple dark frames to create a clean 'Glow Map' for subtraction
"""

import numpy as np
import rawpy
import subprocess
import os

def capture_sequence(count=5):
    """Captures a series of dark frames."""
    dng_files = []
    print(f"Starting Master Dark sequence ({count} frames)...")

    for i in range (count):
        path = f"/home/admininja/vop/master_dark_tmp_i{i}.jpg"
        print(f"  Capturing frame {i+1}/{count}...")
        cmd = [
            "rpicam-still", "r",
            "-o", path,
            "--shutter", "2000000",
            "--gain", "1",
            "--immediate"
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        dng_files.append(path.replace(".jpg", ".dng"))
    
    return dng_files

def generate_master(file_base):
    """ Averages the DNGs into a single 32_bit NumPy array."""
    stack = []
    print("Stacking and averaging frames...")

    for f in files:
        with rawpy.imread(f) as raw:
            # Normalize to 12-bit immediately
            stack.append(raw.raw_image.astype(np.float32) / 16.0)
    
    master_dark = np.mean(stack, axis=0)

    # Save as a .npy for lightning-fast loading in the main engine
    output_name = "/home/admininja/vop/master_dark_2s_g1.npy"
    np.save(output_name, master_dark)

    # Cleanup temp files
    for f in files:
        os.remove(f)
        os.remove(f.replace(".dng", ".jpg"))

    print(f"Master Dark saved to: {output_name}")
    print(f"Final Shape: {master_dark.shape}")

if __name__ == "__main__":
    sequence = capture_sequence(5)
    generate_master(sequence)