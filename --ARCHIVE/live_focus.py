"""
VOP Project - Live Focus Sweep Utility
Version: v0.0.3
Description: Performs a focus sweep and saves JPEGs to a dedicated calibration folder, keeping the production folder clean.
"""

import cv2          # OpenCV: The library for computer vision and image capture
import subprocess   # Allows us to run Linux shell commands (v4l2-ctl)
import os           # Used for interacting with the operating system (folder/paths)
import time         # Used to add delays so hardware can keep up
import shutil       # Added in v0.0.2 to allow cleaning/deleting folders

# --- CONSTANTS ---
# /dev/video0 is the system address for your C920 webcam
DEVICE = "/dev/video0"
# The subfolder where we store our results
TARGET_DIR = "vop_focus_tests"

def prepare_directory():
    """
    Cleans out ONLY the focus test folder.
    Using a dedicated folder ensures we don't touch our 16-bit TIFFs later.
    """
    if os.path.exists(TARGET_DIR):
        # shutil.rmtree deletes the folder and everything inside it
        shutil.rmtree(TARGET_DIR)
    # Create a fresh version of the folder
    os.makedirs(TARGET_DIR)
    print(f"Directory {TARGET_DIR} is ready for fresh calibration images.")


def set_focus(val):
    """
    Communicates with the C920 hardware to set a manual focus value.
    0 = Infinity, 250 = Closest Focus.
    """
    # First, we MUST disable 'continuous' autofocus, or manual commands are ignored
    subprocess.run(['v4l2-ctl', '-d', DEVICE, '--set-ctrl=focus_automatic_continuous=0'], check=True)

    # Now we send the absolute focus value (C920 range: 0-250)
    # 0 is usually infinity; higher is closer.
    subprocess.run(['v4l2-ctl', '-d', DEVICE, f'--set-ctrl=focus_absolute={val}'], check=True)

def perform_sweep():
    # 1. Clean the folder
    prepare_directory()
    
    # 2. Initialize camera: Open the camera stream using the V4L2 backend
    # This backend is essential on linux for manual exposure/focus control
    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)

    # 3. Set the capture resolution to 1080p
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    print("Beginning Sweep. Please stay still...")

    try:
        # Loop from 0 to 250 in steps of 10
        for f_val in range(0, 251, 10):
            # Set current focus
            set_focus(f_val)

            # Wait for the physical lens motor to stop moving
            time.sleep(0.8)

            # Capture the image
            success, frame = cap.read()

            if success:
                # Format the filename with leading zeroes (e.g., focus_040.jpg)
                # so the files stay in numerical order in your file manager.
                file_path = os.path.join(TARGET_DIR, f"focus_{f_val:03d}.jpg")

                # Burn the ID into the image for easy identification
                cv2. putText(frame, f"Focus ID: {f_val}", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 255, 0), 3)

                # cv2.imwrite(path, image_data) saves the frame to your SD card
                cv2. imwrite(file_path, frame)

                # Print to terminal so you know the pi is actually working
                print(f"Saved: {file_path}")
    finally:
        # Free the hardware
        cap.release()
        print("\nSweep Complete. Check ~/vop_remote/{TARGET_DIR} on Fedora.")
if __name__ == "__main__":
    perform_sweep()
    
            
                    