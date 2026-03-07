"""
VOP Module:     camera_hardware.py
Version:        v0.0.8
Description:    Subprocess execution and timing for the IMX477 sensor.
                Restored: --raw flag and dummy JPEG logic.
"""
import subprocess
import time
import os

def trigger_capture(output_path, total_ms, gain, awb_r, awb_b, resolution="2028x1520"):
    """
    Executes rpicam-still in an independent parallel process.
    The total_ms includes a 1000ms padding (500ms black header + 500ms black tail).
    """
    
    # THE CRITICAL FIX: The RAW DNG Quirks
    # rpicam-still requires a "primary" output file to attach the RAW data to.
    dummy_jpg = output_path.replace(".dng", ".jpg")
    
    # Calculate the physical shutter duration in microseconds, subtracting the 1000ms padding.
    shutter_us = int((total_ms - 1000) * 1000)
    
    cmd = [
        "rpicam-still",
        "--immediate",
        "--shutter", str(shutter_us),
        "--gain", str(gain),
        "--awbgains", f"{awb_r},{awb_b}",
        "--denoise", "off",
        "-n",
        "--width", resolution.split('x')[0],
        "--height", resolution.split('x')[1],
        "--raw", 
        "-o", dummy_jpg
    ]
    
    return subprocess.Popen(cmd)

def wait_for_sensor_prime():
    """
    Blocks execution for 700ms to accommodate the sensor initialization offset.
    This prevents the projector from flashing the smear before the camera is listening.
    """
    time.sleep(0.7)