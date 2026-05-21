"""
VOP Module:     camera_hardware.py
Description:    Subprocess execution and timing for the IMX477 sensor.
                Restored: --raw flag and dummy JPEG logic.
"""

#
###########################################################################
#
#                                   VOP
#                       Copyright (C) 2025  jmalmsten
#
#     This program is free software: you can redistribute it and/or modify 
#     it under the terms of the GNU Affero General Public License as 
#     published by the Free Software Foundation, either version 3 of the 
#     License, or (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful, but 
#     WITHOUT ANY WARRANTY; without even the implied warranty of 
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU 
#     Affero General Public License for more details.
#
#     You should have received a copy of the GNU Affero General Public 
#     License along with this program.  If not, see 
#     <http://www.gnu.org/licenses/>.
#
#     Source code for this application can be found at 
#     https://codeberg.org/jmalmsten-com/VOP
#
###########################################################################



import subprocess
import time
import os

# Pi 4B hardware initialization delay. 
# This dictates both the Python sleep timer and the libcamera pre-capture delay.
PRIME_WAIT_MS = 1500 

# IMPORTANT: the `total_ms` parameter is the actual shutter time in
# milliseconds — it is passed directly into libcamera's --shutter flag
# (after the us conversion on the next line). It does NOT include any
# prime-wait overhead. Callers that need to also wait for sensor prime
# should call wait_for_sensor_prime() separately; do NOT add
# PRIME_WAIT_MS to this argument or you will get an exposure that is
# 1.5 seconds longer than intended.
#
# Several pre-existing callers (measure_noise, the old engine code,
# possibly others) do add PRIME_WAIT_MS here. That's a pre-existing
# bug pattern: their captures are 1.5s longer than the audit log
# claims. For measure_noise this is benign-ish (it just gives a
# slightly higher noise-floor reading, which is conservative).
# For ACB / single-peak-measurement and any future calibration
# routine where exposure precision matters, do NOT add PRIME_WAIT_MS.

def trigger_capture(output_path, total_ms, gain, awb_r, awb_b, resolution="2028x1520"):
    """
    Executes rpicam-still in an independent parallel process.
    The total_ms includes a 1000ms padding (500ms black header + 500ms black tail).
    """
    
    # rpicam-still requires a "primary" output file to attach the RAW DNG data to.
    dummy_jpg = output_path.replace(".dng", ".jpg")
    
    # Calculate the physical shutter duration in microseconds.
    shutter_us = int(total_ms * 1000)
    
    cmd = [
        "rpicam-still",
        
        # TIMING AND SYNCHRONIZATION
        # -t sets the pre-capture delay. By matching this to PRIME_WAIT_MS, the camera 
        # sits idle in the dark and opens its shutter at the exact millisecond the 
        # Python loop wakes up to render the HDMI frames.
        "-t", str(PRIME_WAIT_MS),   
        
        # MANUAL OVERRIDES
        # Explicitly declaring --shutter and --gain completely disables the camera's 
        # Auto Gain Control (AGC) and auto-exposure algorithms. The sensor is locked.
        "--shutter", str(shutter_us),
        "--gain", str(gain),
        "--awbgains", f"{awb_r},{awb_b}",
        
        # IMAGE PROCESSING
        # Disable spatial/color denoising to preserve strict RAW photon counts
        "--denoise", "off",
        
        # -n disables the camera preview window, preventing DRM lock conflicts with OpenGL
        "-n",
        
        # SENSOR RESOLUTION
        "--width", resolution.split('x')[0],
        "--height", resolution.split('x')[1],
        
        # FILE OUTPUT
        "--raw", 
        "-o", dummy_jpg
    ]
    
    return subprocess.Popen(cmd)

def wait_for_sensor_prime():
    """
    Blocks Python execution for PRIME_WAIT_MS to accommodate sensor initialization.
    Because rpicam-still is launched with `-t 1500`, the camera and the Python thread 
    will exit their respective waiting periods simultaneously.
    """
    time.sleep(PRIME_WAIT_MS / 1000.0)