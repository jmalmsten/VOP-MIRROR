"""
VOP Module:     color_utils.py
Description:    16-bit linear workspace modifications and latent image accumulation.
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


import os
import cv2
import rawpy
import numpy as np
import json

def apply_pedestal(img_16bit, clip_val):
    """
    Subtracts the noise floor pedestal in a float 32 workspace to prevent underflow,
    then clips at zero and returns to uint16.
    """

    if clip_val <= 0.0:
        return img_16bit
    
    int_threshold = int(clip_val * 65535)
    img_f = img_16bit.astype(np.float32)
    img_f = np.clip(img_f - int_threshold, 0, 65535)
    return img_f.astype(np.uint16)

def generate_sensor_preview(buffer_file, static_dir, cam_gel_rgb, mono_forced, black_clip=0.0,
                            par_x=1.0, par_y=1.0, preview_unsqueeze=False):
    if not os.path.exists(buffer_file): return False

    try:
        with rawpy.imread(buffer_file) as raw:
            rgb = raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16)
        
        # --- Patch defective pixels immediately ---
        rgb = apply_hot_pixel_patch(rgb, static_dir)
        
        # 1. Apply the Pedestal subtraction
        rgb = apply_pedestal(rgb, black_clip)

        # 2. Convert from RGB to BGR for OpenCV
        img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

        # Downscale to 8-bit for the preview JPEG AFTER the high-precision math
        img = (img / 256.0).astype(np.uint8)
        
        # Mono stripping logic here for previews
        if mono_forced:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

        gel_bgr = np.array([cam_gel_rgb[2], cam_gel_rgb[1], cam_gel_rgb[0]], dtype=np.float32)
        img = (img.astype(np.float32) * gel_bgr).clip(0, 255).astype(np.uint8)

        # ANAMORPHIC PREVIEW UNSQUEEZE
        # Cam View has captured the squeezed HDMI screen. If the user has asked
        # for a preview that matches what their NLE would produce, we apply the
        # inverse of the squeeze here as a JPG-level resample. PAR > 1 means the
        # original logical X was compressed into a smaller pixel-X span, so we
        # stretch X back out by PAR. PAR < 1 means we stretch Y back out by 1/PAR.
        # The latent TIFFs on disk are NOT processed here - they stay squeezed
        # so the NLE can do the real PAR-driven unsqueeze in post production.
        if preview_unsqueeze:
            try:
                px = float(par_x) if float(par_x) > 0 else 1.0
                py = float(par_y) if float(par_y) > 0 else 1.0
                par = px / py
                if abs(par - 1.0) > 1e-6:
                    h, w = img.shape[:2]
                    if par > 1.0:
                        # Wide-pixel case: stretch X horizontally
                        new_w = int(round(w * par))
                        img = cv2.resize(img, (new_w, h), interpolation=cv2.INTER_CUBIC)
                    else:
                        # Tall-pixel case: stretch Y vertically
                        new_h = int(round(h / par))
                        img = cv2.resize(img, (w, new_h), interpolation=cv2.INTER_CUBIC)
            except Exception as e:
                print(f"[VOP WARNING] Preview unsqueeze failed (falling back to squeezed): {e}")

        cv2.imwrite(os.path.join(static_dir, "probe_live.jpg"), img)
    
    except Exception as e:
        print(f"[VOP WARNING] Processing Error: {e}")

    finally:
        # Added finally block so cleanup happens even if something crashes
        if os.path.exists(buffer_file): os.remove(buffer_file)
        dummy = buffer_file.replace(".dng", ".jpg")
        if os.path.exists(dummy): os.remove(dummy)
        
    return True
def process_and_stack_latent_image(buffer_file, static_dir, output_file, tiff_flag, cam_gel_rgb, mono_forced, black_clip=0.0):
    if not os.path.exists(buffer_file): return False

    try:
        with rawpy.imread(buffer_file) as raw:
            rgb = raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16)
        
        # --- Patch defective pixels immediately ---
        rgb = apply_hot_pixel_patch(rgb, static_dir)
    
        # 1. Apply the pedestal subtraction
        rgb = apply_pedestal(rgb, black_clip)

        # 2. Convert from RGB to BGR for OpenCV
        img = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        
        if mono_forced:
            # Exploit monochrome clarity by stripping color before tinting
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        
        # Now apply the CG tint (cam_gel_rgb)
        gel_bgr = np.array([cam_gel_rgb[2], cam_gel_rgb[1], cam_gel_rgb[0]], dtype=np.float32)
        img = (img.astype(np.float32) * gel_bgr).clip(0, 65535).astype(np.uint16)

        # Check to see if file already exists
        if os.path.exists(output_file):
            existing = cv2.imread(output_file, cv2.IMREAD_UNCHANGED)
            if existing is not None:
                img = cv2.add(img, existing.astype(np.uint16))

        cv2.imwrite(output_file, img, [cv2.IMWRITE_TIFF_COMPRESSION, tiff_flag])

    except Exception as e:
        print(f"[VOP WARNING] Processing Error: {e}")

    finally:
        if os.path.exists(buffer_file): os.remove(buffer_file)
        dummy = buffer_file.replace(".dng", ".jpg")
        if os.path.exists(dummy): os.remove(dummy)
    return True

def write_screen_capture(pixels, width, height, static_dir):
    # CRITICAL FIX: Process the raw RGBA (4-channel) byte buffer from ModernGL.
    img = np.frombuffer(pixels, dtype=np.uint8).reshape((height, width, 4))
    img = np.flipud(img)
    # Convert RGBA directly down to standard BGR for JPEG saving.
    img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
    cv2.imwrite(os.path.join(static_dir, "probe_live.jpg"), img)

def measure_noise_floor(buffer_file, static_dir):
    """
    Analyzes a dark frame to determine the sensor's noise ceiling at the 
    current exposure settings, draws a bounding box for UI feedback,
    and exports the result to a static JSON for the frontend.
    
    Uses the 99.9th percentile of the center crop rather than the mean — 
    the noise crusher is a threshold, so the value we want is the *ceiling* 
    the noise reaches, not its average. Setting the crusher to the mean would
    let roughly half the noise distribution survive crushing.
    
    Hot pixels are patched before measurement so they don't dominate the 
    percentile statistic.
    """
    
    if not os.path.exists(buffer_file):
        return 0.0
    
    try:
        with rawpy.imread(buffer_file) as raw:
            # Strictly linear 16-bit extraction
            rgb = raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16)
        
        # Patch hot pixels first so they don't contaminate the measurement
        rgb = apply_hot_pixel_patch(rgb, static_dir)
        
        # Center crop 200x200
        h, w, _ = rgb.shape
        cy, cx = h // 2, w // 2
        crop = rgb[cy-100:cy+100, cx-100:cx+100]
        
        # 99.9th percentile: the value that 99.9% of pixels fall below.
        # This is the noise's effective ceiling — set the crusher just above 
        # this and all noise gets zeroed without sacrificing legitimate signal.
        # We use 99.9 rather than 100 (max) so that a single random outlier 
        # pixel can't skew the result; 99.9% of 200x200 = ~40,000 of 40,000 
        # pixels must agree.
        ceiling_16bit = np.percentile(crop, 99.9)
        noise_float = float(ceiling_16bit / 65535.0)
        
        # --- PREVIEW GENERATION ---
        img_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        img_8bit = (img_bgr / 256.0).astype(np.uint8)
        
        # Burn a bright green rectangle to show the user exactly what area was measured
        cv2.rectangle(img_8bit, (cx-100, cy-100), (cx+100, cy+100), (0, 255, 0), 2)
        cv2.imwrite(os.path.join(static_dir, "probe_live.jpg"), img_8bit)
        
        # Export the numerical result to a dedicated static JSON file
        out_json = os.path.join(static_dir, "noise_data.json")
        with open(out_json, "w") as f:
            json.dump({"measured_noise": noise_float}, f)
        
        return noise_float
    
    except Exception as e:
        print(f"[VOP WARNING] Noise Measurement Error: {e}")
        return 0.0
    finally:
        # Cleanup routine to prevent tmp folder bloat
        if os.path.exists(buffer_file): os.remove(buffer_file)
        dummy = buffer_file.replace(".dng", ".jpg")
        if os.path.exists(dummy): os.remove(dummy)

def apply_hot_pixel_patch(img_16bit, static_dir):
    """
    Reads the hot pixel map and replaces defective pixels with the median of their neighbors.
    Uses cv2.medianBlur and numpy indexing for near-instant C++ execution speed.
    """

    hp_file = os.path.join(static_dir, "hot_pixels.json")
    if not os.path.exists(hp_file):
        return img_16bit
    
    try:
        with open(hp_file, 'r') as f:
            data = json.load(f)
        
        if "pixels" not in data or not data["pixels"]:
            return img_16bit
        
        # Extract coordinates
        pts = np.array(data["pixels"])
        y_coords = pts[:, 0]
        x_coords = pts[:, 1]

        # Apply a 3x3 median blur to a copy of the image.
        blurred = cv2.medianBlur(img_16bit, 3)

        # Overwrite ONLY the defective pixels on the original image with the blurred pixels
        img_16bit[y_coords, x_coords] = blurred[y_coords, x_coords]

        return img_16bit
    except Exception as e:
        print(f"[VOP WARNING] Hot Pixel Patch Error: {e}")
        return img_16bit

def map_hot_pixels(buffer_file, static_dir):
    """
    Scans a dark frame for anomalies and saves coordinates to JSON.
    If it detects too many hot pixels ( > 0.5% of sensor), it assumes the lens cap is off.
    """
    if not os.path.exists(buffer_file): return -1

    try:
        with rawpy.imread(buffer_file) as raw:
            rgb = raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16)
        
        # Convert to grayscale to measure pure intensity
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)

        # Calculate the mathematical noise floor and standard deviation
        mean_val, std_val = cv2.meanStdDev(gray)
        mean_val, std_val = mean_val[0][0], std_val[0][0]

        # A hot pixel is anything 10 standard deviations above the noise floor
        # We also set a hard minimum (1000) so a perfectly clean, pitch black frame doesn't trigger false positives
        threshold = max(mean_val + (10 * std_val), 1000)

        # Find coordinates where intensity exceeds threshold
        y_coords, x_coords = np.where(gray > threshold)
        hp_count = len(y_coords)
        out_json = os.path.join(static_dir, "hot_pixels.json")

        if hp_count > 15000:
            with open(out_json, "w") as f:
                json.dump({"error": "LENS CAP OFF?", "pixels": []}, f)
            return  -1

        # Convert to a standard Python list of [y, x] pairs for JSON serialization
        pixels_list = [[int(y), int(x)] for y, x in zip(y_coords, x_coords)]

        with open(out_json, "w") as f:
            json.dump({"error": None, "pixels": pixels_list}, f)
        
        return hp_count
    except Exception as e:
        print(f"[VOP WARNING] Mapping Error: {e}")
        return -1
    finally:
        if os.path.exists(buffer_file): os.remove(buffer_file)
        dummy = buffer_file.replace(".dng", ".jpg")
        if os.path.exists(dummy): os.remove(dummy)

