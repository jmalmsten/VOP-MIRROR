"""
VOP Module:     vop_alignment_overlay.py
Version:        v0.0.1
Description:    Live camera view with a Red X overlay for physical centering.
"""

import cv2
import subprocess
import numpy as np

def run_overlay():
    # 1. Setup the rpicam-vid pipe to feed OpenCV
    # We use a raw YUV stream for speed and minimal lag
    cmd = [
        "rpicam-vid",
        "-t", "0",              # Run indefinitely
        "--width", "1280",      # Reduced res for lower latency during alignment
        "--height", "720",
        "--framerate", "30",
        "--shutter", "30000",   # High exposure for framing
        "--gain", "16",         # High gain to see the bezel
        "--codec", "yuv420",
        "-o", "-"               # Output to stdout
    ]

    print("Launching Alignment Overlay v0.0.1...")
    print("Controls: Press 'q' in this window to exit.")

    # Start the camera process
    pipe = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**8)

    # Resolution math for 1280x720
    w, h = 1280, 720
    frame_size = w * h * 3 // 2 # YUV420 format size

    try:
        while True:
            # Read one frame from the pipe
            raw_frame = pipe.stdout.read(frame_size)
            if len(raw_frame) != frame_size:
                break

            # Convert YUV to BGR (OpenCV standard)
            yuv = np.frombuffer(raw_frame, dtype=np.uint8).reshape((h * 3 // 2, w))
            frame = cv2.cvtColor(yuv, cv2.COLOR_YUV2BGR_I420)

            # 2. Draw the Big Red X
            # Thickness is 5 pixels for high visibility
            cv2.line(frame, (0, 0), (w, h), (0, 0, 255), 5)      # Top-left to bottom-right
            cv2.line(frame, (w, 0), (0, h), (0, 0, 255), 5)      # Top-right to bottom-left

            # 3. Display the result
            cv2.imshow("VOP Alignment Helper", frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    finally:
        pipe.terminate()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    run_overlay()