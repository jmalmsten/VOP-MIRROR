"""
VOP Module:     camera_hardware.py
Version:        v0.0.6
Description:    Subprocess execution and timing for the IMX477 sensor.
                This module isolates the hardware triggers to ensure strict adherence 
                to the VOP execution timing rules.
"""
# subprocess is used to spawn new processes, connect to their input/output/error pipes, 
# and obtain their return codes.
import subprocess
# time is used for execution blocking (sleep).
import time

def trigger_capture(output_path, total_ms, gain, awb_r, awb_b, resolution="2028x1520"):
    """
    Executes rpicam-still in an independent parallel process.
    By using subprocess.Popen instead of subprocess.run, the Python script continues 
    executing immediately rather than waiting for the camera capture to finish.
    """
    cmd = [
        "rpicam-still",
        # --immediate bypasses the ISP (Image Signal Processor) auto-exposure and auto-focus 
        # convergence routines, forcing the camera to capture exactly when commanded.
        "--immediate",
        # --shutter expects microseconds. We multiply the milliseconds value by 1000.
        "--shutter", str(int(total_ms * 1000)),
        # --gain locks the analog sensor gain to the value provided in the UI.
        "--gain", str(gain),
        # --awbgains locks the red and blue white balance multipliers to prevent color shifting.
        "--awbgains", f"{awb_r},{awb_b}",
        # --denoise off and -n (no preview) bypass internal processing to guarantee maximum speed 
        # and raw data integrity (VOP Rule #4).
        "--denoise", "off",
        "-n",
        # Explicitly define the sensor readout resolution.
        "--width", resolution.split('x')[0],
        "--height", resolution.split('x')[1],
        # -o specifies the output file path.
        "-o", output_path
    ]
    # Spawns the process and returns the process handle so the main engine can monitor its completion.
    return subprocess.Popen(cmd)

def wait_for_sensor_prime():
    """
    Blocks execution to accommodate the 700ms sensor initialization offset.
    VOP Rule #6: The IMX477 requires ~700 milliseconds from the moment the process is launched 
    until the sensor actually begins recording photons. We sleep the engine thread here so the 
    projector graphics do not begin rendering before the sensor is ready.
    """
    time.sleep(0.7)
