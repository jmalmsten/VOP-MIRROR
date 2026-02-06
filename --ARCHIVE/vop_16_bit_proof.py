"""
VOP Module:     vop_16bit_proof.py
Version:        v0.0.1
Description:    Clinical verification of 16-bit DNG-to-TIFF pipeline.
"""
import subprocess
import os
import rawpy
import cv2
import numpy as np

def prove_16bit():
    raw_file = "raw_test.dng"
    out_file = "proof_16bit.tif"
    
    # 1. Capture a DNG (Native 12-bit sensor dump)
    print("Step 1: Capturing DNG...")
    # We use -r (raw) to ensure the DNG contains the full Bayer data
    subprocess.run([
        "rpicam-still", "-o", raw_file, "-r",
        "--shutter", "100000", "--gain", "1.0",
        "--immediate", "--denoise", "off", "-n"
    ])

    # 2. Develop DNG to 16-bit Linear array
    if os.path.exists(raw_file):
        print("Step 2: Developing RAW to 16-bit Linear...")
        with rawpy.imread(raw_file) as raw:
            # gamma(1,1) = Linear (No curve applied)
            # no_auto_bright = True (No exposure compensation)
            # output_bps=16 (True 16-bit per channel)
            rgb_16 = raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16)
        
        # 3. Convert RGB to BGR for OpenCV and Save Uncompressed
        print("Step 3: Saving Uncompressed TIFF...")
        bgr_16 = cv2.cvtColor(rgb_16, cv2.COLOR_RGB2BGR)
        cv2.imwrite(out_file, bgr_16, [cv2.IMWRITE_TIFF_COMPRESSION, 1])

        # 4. Check results
        size_mb = os.path.getsize(out_file) / (1024*1024)
        print(f"\n--- AUDIT RESULTS ---")
        print(f"TIFF Size: {size_mb:.2f} MB")
        print(f"Dtype:     {bgr_16.dtype}")
        
        if size_mb > 70:
            print("STATUS: 16-BIT CEILING BROKEN.")
        else:
            print("STATUS: STILL STUCK IN 8-BIT.")
    else:
        print("FAILED: DNG was not captured.")

if __name__ == "__main__":
    prove_16bit()