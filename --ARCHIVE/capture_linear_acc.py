"""
VOP Project - Interactive Accumulator Capture
Version: v0.0.7
Description: Captures 16-bit linear light. 
             - Filename includes exposure count.
             - Saves UNCOMPRESSED 16-bit TIFFs via OpenCV.
             - Metadata injected via Exiftool.
"""

import cv2          # OpenCV for image capture, math, and saving 16-bit
import numpy as np  # Numerical Python for 16-bit linear math
import subprocess   # To talk to V4L2 hardware and Exiftool
import os           # File and path management
import argparse     # Library for handling terminal arguments
import time         # For sensor stabilization delays
import glob         # To find existing versions of the frame

# --- PRODUCTION CONFIGURATION ---
DEVICE = "/dev/video0"
OUT_DIR = "vop_stills"

def apply_hardware_logic(e, f, w):
    """Sets hardware controls via V4L2 command line."""
    subprocess.run(['v4l2-ctl', '-d', DEVICE, '--set-ctrl=focus_automatic_continuous=0'], check=True)
    subprocess.run(['v4l2-ctl', '-d', DEVICE, '--set-ctrl=auto_exposure=1'], check=True)
    subprocess.run(['v4l2-ctl', '-d', DEVICE, '--set-ctrl=white_balance_automatic=0'], check=True)
    
    subprocess.run(['v4l2-ctl', '-d', DEVICE, f'--set-ctrl=focus_absolute={f}'], check=True)
    subprocess.run(['v4l2-ctl', '-d', DEVICE, f'--set-ctrl=exposure_time_absolute={e}'], check=True)
    subprocess.run(['v4l2-ctl', '-d', DEVICE, f'--set-ctrl=white_balance_temperature={w}'], check=True)

def capture_linear(e, f, w):
    """Captures a frame and converts it to a 0.0-1.0 linear float array."""
    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    apply_hardware_logic(e, f, w)
    time.sleep(2)

    for _ in range(5):
        cap.read()
    
    success, frame = cap.read()
    cap.release()

    if not success or frame is None:
        return None
    
    # 8-bit -> 32-bit Float -> Linear Space
    img_float = frame.astype(np.float32) / 255.0
    return np.power(img_float, 2.2)

def write_exif_metadata(file_path, comment):
    """Uses exiftool to write metadata into the TIFF."""
    try:
        subprocess.run([
            'exiftool', '-overwrite_original', 
            f'-ImageDescription={comment}', file_path
        ], check=True, capture_output=True)
    except Exception as e:
        print(f"Metadata Warning: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VOP Accumulator v0.0.7")
    parser.add_argument("-n", "--name", type=str, default="scene00")
    parser.add_argument("-f", "--frame", type=int, default=1)
    parser.add_argument("-e", "--exposure", type=int, default=250)
    parser.add_argument("-w", "--wb", type=int, default=4000)
    parser.add_argument("--focus", type=int, default=35)

    args = parser.parse_args()

    if not os.path.exists(OUT_DIR): os.makedirs(OUT_DIR)

    # SEARCH LOGIC: Find if a file for this scene/frame already exists regardless of exp count
    search_pattern = os.path.join(OUT_DIR, f"{args.name}_{args.frame:03d}_exp*.tiff")
    existing_files = glob.glob(search_pattern)

    new_linear = capture_linear(args.exposure, args.focus, args.wb)
    
    if new_linear is None:
        print("Error: Camera failed.")
        exit(1)

    exp_count = 1
    if existing_files:
        # Sort files to find the latest exposure count
        existing_files.sort()
        old_path = existing_files[-1]
        
        # Extract the old exposure count from the filename (the '002' in '_exp002')
        try:
            last_count = int(old_path.split("_exp")[-1].split(".")[0])
            exp_count = last_count + 1
        except:
            exp_count = 2

        print(f"Found existing frame: {old_path}. Adding exposure {exp_count}...")
        
        existing_img = cv2.imread(old_path, cv2.IMREAD_UNCHANGED)
        existing_linear = existing_img.astype(np.float32) / 65535.0
        
        # Additive merge and safety clip
        combined_linear = existing_linear + new_linear
        final_linear = np.clip(combined_linear, 0, 1.0)
        
        # Remove the old file because we are generating a new one with an updated name
        os.remove(old_path)
    else:
        final_linear = new_linear

    # Generate the new filename with the counter
    new_filename = f"{args.name}_{args.frame:03d}_exp{exp_count:03d}.tiff"
    full_path = os.path.join(OUT_DIR, new_filename)

    # Convert to 16-bit Integer
    img_16bit = (final_linear * 65535.0).astype(np.uint16)

    # Save UNCOMPRESSED (OpenCV constant 1 means 'None' for compression)
    cv2.imwrite(full_path, img_16bit, [cv2.IMWRITE_TIFF_COMPRESSION, 1])
    
    # Metadata injection
    info_str = f"VOP_VER:0.0.7 | EXPOSURES:{exp_count} | FOCUS:{args.focus} | WB:{args.wb}"
    write_exif_metadata(full_path, info_str)
    
    print(f"Saved: {new_filename} (Uncompressed 16-bit)")