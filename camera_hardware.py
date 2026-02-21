"""
VOP Module:     camera_hardware.py
Version:        v0.0.6
Description:    Subprocess execution and timing for the IMX477 sensor.
"""
import subprocess
import time

def trigger_capture(output_path, total_ms, gain, awb_r, awb_b, resolution="2028x1520"):
    """
    Executes rpicam-still in an independent parallel process.
    """
    cmd = [
        "rpicam-still",
        "--immediate",
        "--shutter", str(int(total_ms * 1000)),
        "--gain", str(gain),
        "--awbgains", f"{awb_r},{awb_b}",
        "--denoise", "off",
        "-n",
        "--width", resolution.split('x')[0],
        "--height", resolution.split('x')[1],
        "-o", output_path
    ]
    return subprocess.Popen(cmd)

def wait_for_sensor_prime():
    """
    Blocks execution to accommodate the 700ms sensor initialization offset.
    """
    time.sleep(0.7)
