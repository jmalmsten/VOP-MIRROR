"""
VOP Module: camera_hw
Version: v0.1.3
Description: Handles camera capture, bipack filtering, and 16 bit stacking.
"""
import os, time, cv2, numpy as np, subprocess, glob

def capture_and_accumulate(scene, f_num, f_name, exp, foc, wb, cfg, is_snap=False):
    """
    Captures a frame from the sensor and merges it into the 16-bit Latent Image.
    """
    
    dev = cfg['CAMERA_DEVICE']

    # 1. FORCE RESOLUTION & FORMAT
    # The C920 often resets to 640x480 if this isn't forced before the capture starts.
    # Using MJPG allows the C920 to hit 1080p without bandwidth choking.
    subprocess.run(['v4l2-ctl', '-d', dev], check=True)


    # 2. Hardware Override: Force manual control via V4L2-CTL
    # We must first turn off automatic controls before we can set the manual settings.
    subprocess.run(['v4l2-ctl', '-d', dev, 
                    '--set-ctrl=focus_automatic_continuous=0',  # Turn off autofocus
                    '--set-ctrl=auto_exposure=1',               # Turn off auto-shutter
                    '--set-ctrl=white_balance_automatic=0',     # Turn off auto-white-balance
                    '--set-ctrl=gain=0'                         # Turn manual gain to zero
                    ], check=True)
    # Actually set the settings (Ensuring they stay within your specific camera's range)
    # Clamping the valuesjust in case the x-sheet has higher numbers
    foc_val = max(0, min(int(foc), 250))
    exp_val = max(3, min(int(exp), 2047))
    wb_val  = max(2000, min(int(wb), 6500))

    # We cast to int() because v4l2-ctl doesn't like the '.0' from the x-sheet floats
    subprocess.run(['v4l2-ctl', '-d', dev,
                    f'--set-ctrl=focus_absolute={int(foc_val)}',
                    f'--set-ctrl=exposure_time_absolute={int(exp_val)}',
                    f'--set-ctrl=white_balance_temperature={int(wb_val)}'], check=True)
    
    # 3. OPEN CAPTURE & FLUSH BUFFER
    # We Open the capture AFTER setting the hardware to ensure settings stick.
    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    
    # The 'Blackout" Fix:
    # The C920 has a 4-frame internal buffer. We must flush it to see the current projector state.
    time.sleep(1.0) # Give the projector a moment to settle
    for _ in range(20): #8 frames is safe to clear any stale buffer
        cap.grab()

    success, frame = cap.retrieve()
    cap.release()

    if not success:
        print("!!! CAMERA FAIL: Could not retrieve frame.")
        return None

    # 4. Linearize for Light Accumulation
    # We use Gamma 2.2 as an approximation for standard sensor curves
    linear = np.power(frame.astype(np.float32) / 255.0, 2.2)
    out_dir = cfg['CAM_MAG']

    # CAMERA-SIDE BLACK CLIP
    # Using the BLACK_CLIP value, we treat the monitor's 'milky black' as a noise floor to make sure it doesn't build up during multiple exposures.
    # Formula: (LinearValue - Floor) / (1.0 - Floor)
    bc = cfg['BLACK_CLIP']
    linear = np.where(linear < bc, 0.0, (linear - bc) / (1.0 - bc))
    
    # Ensure no negative values from the math
    linear = np.clip(linear, 0.0, 1.0)

    # 5. CAM-BIPACK MULTIPLICATION (FILTERING)
    # If a filter/matte exists in CamBiPack with the same filename, apply it.
    matte_path = os.path.join(cfg['CAM_BIPACK'], f_name)
    if os.path.exists(matte_path):
        matte = cv2.imread(matte_path)
        # Apply filter to sensor data before linearization
        # Linearize matte as well so math is light-accurate
        matte_linear = np.power(matte.astype(np.float32) / 255.0, 2.2)
        # Multiply the linear sensor data by the linear matte
        linear = linear * matte_linear


    # 6. Handle snapshots (technical stills)
    if is_snap:
        name = f"SNAP_{int(time.time())}.tiff"
        cv2.imwrite(os.path.join(out_dir, name), 
            (linear * 65535).astype(np.uint16), 
            [cv2.IMWRITE_TIFF_COMPRESSION, 1]) # 1 = No Compression
        return name
    
    # 7. LATENT STACKING LOGIC
    # Find any existing exposures for this frame in the CamMag
    search = os.path.join(out_dir, f"{scene}_{f_num:03d}_exp*.tiff")
    exist = sorted(glob.glob(search))
    
    if exist:
        count = int(exist[-1].split("_exp")[-1].split(".")[0]) + 1
        prev = cv2.imread(exist[-1], cv2.IMREAD_UNCHANGED).astype(np.float32) / 65535.0
        # Add current light to previous pass (The 16-bit Accumulator)
        linear = np.clip(prev + linear, 0.0, 1.0)
        os.remove(exist[-1]) 
    else:
        count = 1

    # 8. Save back to the CamMag as 16-bit TIFF
    name = f"{scene}_{f_num:03d}_exp{count:03d}.tiff"
    cv2.imwrite(os.path.join(out_dir, name), 
            (linear * 65535).astype(np.uint16), 
            [cv2.IMWRITE_TIFF_COMPRESSION, 1]) # 1 = No Compression
    return name
        