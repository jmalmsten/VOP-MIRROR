"""
VOP Module:     camera_hardware.py
Version:        v0.0.7
Description:    Subprocess execution and timing for the IMX477 sensor.
                This is the only module allowed to talk to the physical camera hardware.
"""
# subprocess is used to spawn background terminal commands from within Python.
import subprocess
# time is used to explicitly block/pause the Python script execution.
import time

def trigger_capture(output_path, total_ms, gain, awb_r, awb_b, resolution="2028x1520"):
    """
    Executes rpicam-still in an independent parallel process.
    We use Popen instead of .run() so Python doesn't freeze while the camera exposes.
    """
    
    # BUGFIX: The RAW DNG Quirks
    # rpicam-still requires a "primary" output file (usually a JPEG) to attach the RAW data to.
    # If we just give it a .dng extension without the --raw flag, it saves a JPEG and names it .dng.
    # Here, we swap the .dng extension for .jpg to create a "dummy" primary file.
    dummy_jpg = output_path.replace(".dng", ".jpg")
    
    # Construct the terminal command as a list of strings for absolute safety against shell injection.
    cmd = [
        "rpicam-still",
        # --immediate skips the 2-3 second "warm up" phase where the camera tries to guess exposure.
        "--immediate",
        
        # --shutter defines the exact duration the sensor gathers light. It requires microseconds.
        # (Milliseconds * 1000 = Microseconds)
        "--shutter", str(int(total_ms * 1000)),
        
        # --gain locks the analog ISO gain applied directly to the sensor pixels.
        "--gain", str(gain),
        
        # --awbgains locks the Red and Blue multipliers to prevent color shifting mid-sequence.
        "--awbgains", f"{awb_r},{awb_b}",
        
        # --denoise off disables spatial/temporal blurring, retaining true optical grain.
        "--denoise", "off",
        
        # -n disables the on-screen preview window, saving massive amounts of GPU bandwidth.
        "-n",
        
        # Explicitly define the sensor readout resolution. 2028x1520 forces the 12-bit RAW mode on the IMX477.
        "--width", resolution.split('x')[0],
        "--height", resolution.split('x')[1],
        
        # THE CRITICAL FIX: --raw forces the generation of the Adobe DNG file.
        "--raw",
        
        # -o writes the dummy JPEG. Because --raw is active, rpicam-still will automatically
        # create a second file with the exact same name, but with a .dng extension.
        # That .dng file is the one the rest of the VOP engine will use.
        "-o", dummy_jpg
    ]
    
    # Launch the command in the background and return the process handle to the engine.
    return subprocess.Popen(cmd)

def wait_for_sensor_prime():
    """
    Blocks execution to accommodate the sensor initialization offset.
    VOP Rule #6: It takes the IMX477 about 700 milliseconds to wake up, allocate memory,
    and begin receiving photons after the command is sent. We sleep the script here
    so the projector doesn't flash the image before the camera is actually looking.
    """
    time.sleep(0.7)