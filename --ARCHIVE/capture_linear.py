"""
VOP Project - Interactive Linear 16-bit Capture
Version: v0.0.6
Description:    Adds White Balance control to the interactive capture.
                Locks Focus at 35 and allows manual Kelvin adjustment
"""

import cv2          # OpenCV for image capture
import numpy as np  # Numerical Python for 16 bit math
import subprocess   # To talk to the V4L2 hardware
import os           # File and path management
import time         # For timestamps and delays
import argparse     # Library for handling terminal arguments

# --- PRODUCTION CONFIGURATION ---
DEVICE = "/dev/video0"          # C920 webcam
OUT_DIR = "vop_stills"

def apply_hardware_logic(exposure, focus, wb, gain=0):
    """
    Applies hardware locks using the parameters passed from the user, now including White Balance
    Note: C920 White Balance is generally 2000-65000.
    """

    print(f"Hardware Lock -> Focus: {focus}, Exposure: {exposure}, WB: {wb}K, Gain: {gain}")

    # Disable auto-modes
    subprocess.run(['v4l2-ctl', '-d', DEVICE, '--set-ctrl=focus_automatic_continuous=0'], check=True)
    subprocess.run(['v4l2-ctl', '-d', DEVICE, '--set-ctrl=auto_exposure=1'], check=True)
    subprocess.run(['v4l2-ctl', '-d', DEVICE, '--set-ctrl=white_balance_automatic=0'], check=True)
    
    # Now we set the absolute values
    subprocess.run(['v4l2-ctl', '-d', DEVICE, f'--set-ctrl=focus_absolute={focus}'], check=True)
    subprocess.run(['v4l2-ctl', '-d', DEVICE, f'--set-ctrl=exposure_time_absolute={exposure}'], check=True)
    subprocess.run(['v4l2-ctl', '-d', DEVICE, f'--set-ctrl=white_balance_temperature={wb}'], check=True)
    subprocess.run(['v4l2-ctl', '-d', DEVICE, f'--set-ctrl=gain={gain}'], check=True)
    subprocess.run(['v4l2-ctl', '-d', DEVICE, '--set-ctrl=power_line_frequency=1'], check=True) # 1 = 50 Hz powerlines


def capture(exposure, focus, wb):
    # Ensure production folder exists
    if not os.path.exists(OUT_DIR):
        os.makedirs(OUT_DIR)
    
    

    # 1. Open the camera FIRST
    #    Open camera with V4L2 backend
    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    # 2. Apply hardware settings NOW while the 'eye' is open
    apply_hardware_logic(exposure, focus, wb)

    # 3. Wait for the sensor to stabilize (webcams need a moment to 'settle')
    time.sleep(2)

    # Flush the buffer (Grabbing 5 frames ensures we get the most recent one)
    for _ in range(5):
        cap.read()
    
    success, frame = cap.read()

    if success:
        # --- THE LINEARIZATION PIPELINE ---
        
        # 1. Convert 8 bit integers (0-255) to 32 bit floating point (0.0 - 1.0)
        img_float = frame.astype(np. float32) / 255.0

        # 2. Inverse Gamma Transform
        # Most webcams use a 2.2 Gamma curve to make images look 'good' to eyes.
        # We raise it to power 2.2 to 'undo' that cuve and get linear light values.
        img_linear = np.power(img_float, 2.2)

        # 3. Upscale to 16-bit (0.0-1.0 becomes 0-65535)
        # This gives us a massive 'container' so we don't lose data during editing.
        img_16bit = (img_linear * 65535.0).astype(np.uint16)

        # Generate filename with unix timestamp
        timestamp = int(time.time())
        file_path = os.path.join(OUT_DIR, f"vop_e{exposure}_f{focus}_wb{wb}_{timestamp}.tiff")

        # Save as UNCOMPRESSED TIFF (cv2.IMWRITE_TIFF_COMPRESSION = 1 is No Compression)
        cv2.imwrite(file_path, img_16bit, [cv2.IMWRITE_TIFF_COMPRESSION, 1])
        print(f"v0.0.5: saved Uncompressed 16bit TIFF: {file_path}")
    else:
        print("Error: Could not capture frame.")
    
    cap.release()

if __name__ == "__main__":
    # Setup the Argument Parser
    parser = argparse.ArgumentParser(description="VOP Interactive Capture v0.0.6")

    # Add arguments with defaults so you don't HAVE to type them every time
    parser.add_argument("-e", "--exposure", type=int, default=250, help="Exposure value (3-2047)")
    parser.add_argument("-f", "--focus", type=int, default=35, help="Focus value (0-250)")
    parser.add_argument("-w", "--whitebalance", type=int, default=4000, help="White Balance (2000-6500)")
    
    args = parser.parse_args()

    # Pass terminal argumets into our capture function
    capture(args.exposure, args.focus, args.whitebalance)