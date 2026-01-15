"""
VOP Module: clinical_capture.py

Version: v0.0.3
Description:    Portable version using dynamic paths.

Version: v0.0.2
Description:    Adds debayering so the output TIFF is a viewable 
                RGB color image. After the Masterdark is subtracted from it. 

Version: v0.0.1
Description:    Captures a raw image, subtracts the Master Dark,
                Applies AWB gains, and saves a 'clean'12-bit array.
"""

import numpy as np
import rawpy
import subprocess
import os
import imageio # For saving the high-bit depth result

# Dynamic Path Discovery
HOME = os.path.expanduser("~")
VOP_DIR = os.path.join(HOME, "vop")
MASTER_DARK_PATH = os.path.join(VOP_DIR, "master_dark_2s_g1.npy")
# Configuration from your calibration
AWB_GAINS = (1.9, 1.0, 3.5) # Red, Green (fixed), Blue

def clinical_snap(output_name, shutter=2000000):
    # Ensure the output directory exists
    if not os.path.exists(VOP_DIR):
        os.makedirs(VOP_DIR)
    
    print(f"Capturing Clinical Color Frame: {output_name}")

    # Pathing without hard coded usernames
    raw_path = os.path.join(VOP_DIR, f"{output_name}.jpg")
    dng_path = raw_path.replace(".jpg", ".dng")

    # 1. Capture the raw data

    cmd = [
        "rpicam-still", "-r",
        "-o", raw_path,
        "--shutter", str(shutter),
        "--gain", "1",
        "--immediate"
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL)

    # 2. Open with Rawpy
    with rawpy.imread(dng_path) as raw:
        # Get the actual raw array
        raw_array = raw.raw_image.astype(np.float32) / 16

        # 3 SUBTRACT FIRST (The Clinical Way)
        if os.path.exists(MASTER_DARK_PATH):
            master_dark = np.load(MASTER_DARK_PATH)
            # Apply subtraction to the raw bayer grid
            clean_raw = np.maximum(raw_array - master_dark, 0)

            # Inject the cleaned data back into the rawpy object
            # This 'tricks' the debayering engine into using our clean data
            raw.raw_image[:] = (clean_raw * 16).astype(np.uint16)
            print("  [SUCCESS] Bayer-level dark subtraction complete: {os.path.basename(MASTER_DARK_PATH)}")
        
        # 4. DEBAYER SECOND (Turning numbers into color)
        # user_wb: applies your calibrated color gains
        # no_auto_bright: prevents the software from 'guessing' exposure
        # output_bps=16: preserves your 12-bit depth in a 16-bit file
        rgb_color = raw.postprocess(
            user_wb=[AWB_GAINS[0], 1.0, AWB_GAINS[2], 1.0],
            no_auto_bright=True,
            output_bps=16
        )

        # 5. Export
        tiff_path = os.path.join(VOP_DIR, f"{output_name}_clinical_color.tiff")
        imageio.imwrite(tiff_path, rgb_color)
        print(f"  Result saved: {tiff_path}")
        

if __name__ == "__main__":
    clinical_snap("test_subject_002")