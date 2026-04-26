"""
VOP Module:     camera_hardware.py
Version:        v0.0.8
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

PRIME_WAIT_MS = 500 # Pi 4B needs more init time than Pi 5

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
    Blocks execution for PRIME_WAIT_MS to accommodate sensor initialization.
    This value must match the offset passed to trigger_capture() in engine.py.
    """
    time.sleep(PRIME_WAIT_MS / 1000.0)