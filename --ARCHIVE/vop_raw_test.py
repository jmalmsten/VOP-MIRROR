"""
VOP Module:     vop_raw_test.py
Version:        v0.0.1
Description:    Clinical test to find the 16-bit "Door".
                Attempts DNG, 16-bit TIFF, and RAW-embedded PNG.
"""
import subprocess
import os

def run_audit():
    print("--- STARTING 16-BIT AUDIT ---")
    
    # Test A: Direct DNG (The Digital Negative)
    # This captures the 12-bit Bayer data directly. 
    # It should be ~18-20MB (compressed raw) or ~30MB (uncompressed).
    print("Testing A: DNG Capture...")
    subprocess.run(["rpicam-still", "-o", "test_A.dng", "-n", "--immediate", "--shutter", "100000"])

    # Test B: 16-bit TIFF via ISP
    # This asks the ISP to develop into 16-bit. 
    # If this works, it MUST be ~75MB.
    print("Testing B: 16-bit TIFF...")
    subprocess.run(["rpicam-still", "-o", "test_B.tif", "--encoding", "tiff", "-n", "--immediate", "--shutter", "100000"])

    # Test C: PNG with RAW Stack
    # Captures a standard PNG but appends the RAW data at the end.
    print("Testing C: PNG + RAW...")
    subprocess.run(["rpicam-still", "-o", "test_C.png", "--raw", "-n", "--immediate", "--shutter", "100000"])

    print("\n--- RESULTS ---")
    for f in ["test_A.dng", "test_B.tif", "test_C.png"]:
        if os.path.exists(f):
            size = os.path.getsize(f) / (1024*1024)
            print(f"{f}: {size:.2f} MB")
        else:
            print(f"{f}: FAILED TO CAPTURE")

if __name__ == "__main__":
    run_audit()