"""
VOP Module:     camera_hardware.py
Version:        v0.0.4
Description:    Hardware Abstraction Layer for Pi Camera HQ.
"""
import subprocess
import time

# Offset to account for sensor warm-up/shutter prep
LATENCY_OFFSET_MS = 900.0 

def trigger_capture(buffer_file, total_ms, gain, awb_r, awb_b, res_str="4056x3040"):
    """
    Triggers rpicam-still with specific resolution, shutter, and gain.
    """
    shutter_us = int(total_ms * 1000)
    width, height = res_str.split('x')
    
    cmd = [
        "rpicam-still",
        "-o", buffer_file,
        "-r",
        "--width", width,
        "--height", height,
        "--shutter", str(shutter_us),
        "--gain", str(gain),
        "--awbgains", f"{awb_r},{awb_b}",
        "--immediate",
        "--denoise", "off",
        "-n"
    ]
    # Return the process handle so the engine can .wait() on it
    return subprocess.Popen(cmd)

def wait_for_sensor_prime():
    time.sleep(LATENCY_OFFSET_MS / 1000.0)