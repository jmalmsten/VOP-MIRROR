"""
VOP Module:     camera_hardware.py
Version:        v0.0.1
Description:    Hardware Abstraction Layer for Pi Camera HQ (Rolling Shutter).
                DO NOT MODIFY WITHOUT MANUAL AUDIT.
"""
import subprocess
import time

# Rolling Shutter Latency Offset (Handshake)
LATENCY_OFFSET_MS = 900.0 

def trigger_capture(buffer_file, total_ms, gain, awb_r, awb_b):
    """
    Constructs and fires the parallel camera process.
    Uses Rule 4 & 5: --immediate --shutter --gain --awbgains --denoise off -n.
    """
    shutter_us = int(total_ms * 1000)
    cmd = [
        "rpicam-still",
        "-o", buffer_file,
        "-r", # Raw output
        "--shutter", str(shutter_us),
        "--gain", str(gain),
        "--awbgains", f"{awb_r},{awb_b}",
        "--immediate",
        "--denoise", "off",
        "-n" # No preview
    ]
    
    # Return the Popen object so the engine can manage the lifecycle
    return subprocess.Popen(cmd)

def wait_for_sensor_prime():
    """Rule 6: Offset before the anchor = time.time()."""
    time.sleep(LATENCY_OFFSET_MS / 1000.0)