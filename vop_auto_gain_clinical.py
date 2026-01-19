"""
VOP Module:     vop_auto_gain_clinical.py
Version:        v0.1.6
Description:    Clinical Gain Calibration. 
                Saves to disk first to eliminate pipe truncation errors.
                Explicitly breaks out and identifies channels.
"""

import os
import time
import subprocess
import argparse
import numpy as np
import cv2
import pygame

def run_calibration(exposure_seconds):
    shutter_us = int(exposure_seconds * 1000000)
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    os.environ["DISPLAY"] = ":0"
    
    pygame.init()
    screen = pygame.display.set_mode((1920, 1080), pygame.FULLSCREEN)
    
    # 1. Show Gray (128)
    screen.fill((128, 128, 128))
    pygame.display.update()
    time.sleep(exposure_seconds + 0.5) 

    # 2. Capture to a physical file (Matching your working check_red.jpg method)
    debug_path = os.path.expanduser("~/vop/clinical_verify.jpg")
    print(f"Capturing to {debug_path}...")
    
    cmd = [
        "rpicam-still",
        "--shutter", str(shutter_us),
        "--gain", "1",
        "--immediate",
        "--awbgains", "1.0,1.0",
        "-o", debug_path,
        "-n"
    ]
    
    try:
        subprocess.run(cmd, check=True)
        
        # 3. Read back from disk
        img = cv2.imread(debug_path)
        if img is None:
            print("Error: Could not read the captured file.")
            return

        # 4. Explicit Channel Split
        # OpenCV standard is BGR
        blue_ch = img[:, :, 0]
        green_ch = img[:, :, 1]
        red_ch = img[:, :, 2]
        
        h, w = red_ch.shape
        r_roi = red_ch[h//4:3*h//4, w//4:3*w//4]
        g_roi = green_ch[h//4:3*h//4, w//4:3*w//4]
        b_roi = blue_ch[h//4:3*h//4, w//4:3*w//4]

        r_avg = np.mean(r_roi)
        g_avg = np.mean(g_roi)
        b_avg = np.mean(b_roi)

        # Calculate Gains
        r_gain = g_avg / r_avg if r_avg > 0.1 else 99.0
        b_gain = g_avg / b_avg if b_avg > 0.1 else 99.0

        print("\n" + "="*45)
        print("   VOP CLINICAL CHANNEL VERIFICATION")
        print("="*45)
        print(f"Average Intensities (Center ROI):")
        print(f"  Channel [0] (Blue):  {b_avg:.2f}")
        print(f"  Channel [1] (Green): {g_avg:.2f}")
        print(f"  Channel [2] (Red):   {r_avg:.2f}")
        print("-" * 45)
        print(f"RECOMMENDED: --awbgains {r_gain:.3f},{b_gain:.3f}")
        print("="*45)

        if r_avg < 10:
            print("\n[!] ANALYSIS: Red is still reporting near-zero.")
            print("    This is impossible if clinical_verify.jpg looks gray.")
            print("    Let's check the corners instead of the center...")
            r_corner = np.mean(red_ch[0:100, 0:100])
            print(f"    Red Corner Intensity: {r_corner:.2f}")

    finally:
        pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=2.0)
    args = parser.parse_args()
    run_calibration(args.seconds)