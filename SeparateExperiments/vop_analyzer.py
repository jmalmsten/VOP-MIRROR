"""
VOP Module:     vop_analyzer.py
Version:        v0.0.1
Description:    Analyzes the 'vop_calibration_capture.jpg' to check 
                sensor response for Black, Mid, and White levels.
"""

import cv2
import numpy as np
import sys

def analyze_capture():
    img_path = "vop_calibration_capture.jpg"
    img = cv2.imread(img_path)
    
    if img is None:
        print(f"Error: Could not find {img_path}. Did you run the capture script?")
        return

    # Convert to grayscale for clinical brightness check
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape
    
    # Define three sample zones (Left: Black, Middle: Mid, Right: White)
    # We take a 200x200 pixel patch from the center of each bar
    zones = {
        "BLACK (Target 0)":   gray[h//2-100:h//2+100, w//6-100:w//6+100],
        "MID   (Target 128)": gray[h//2-100:h//2+100, w//2-100:w//2+100],
        "WHITE (Target 255)": gray[h//2-100:h//2+100, (w//6*5)-100:(w//6*5)+100]
    }

    print("--- VOP Optical Analysis v0.0.1 ---")
    for name, zone in zones.items():
        avg_val = np.mean(zone)
        min_val = np.min(zone)
        max_val = np.max(zone)
        std_dev = np.std(zone)
        
        print(f"{name}:")
        print(f"  Avg Brightness: {avg_val:.2f}")
        print(f"  Range:         {min_val} to {max_val}")
        print(f"  Noise (StdDev): {std_dev:.2f}")
        
        if max_val >= 254:
            print("  [!] WARNING: CLIPPING DETECTED. Sensor is saturated.")
        print("-" * 30)

if __name__ == "__main__":
    analyze_capture()