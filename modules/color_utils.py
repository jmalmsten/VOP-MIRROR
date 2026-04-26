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

def generate_sensor_preview(buffer_file, static_dir, cam_gel_rgb, mono_forced, black_clip=0.0):
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
    Analyzes a dark frame, draws a bounding box for UI feedback,
    and exports the result to a static JSON for the frontend.
    """
    
    if not os.path.exists(buffer_file):
        return 0.0
    
    try:
        with rawpy.imread(buffer_file) as raw:
            # Strictly linear 16-bit extraction
            rgb = raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16)
        
        # Center crop 200x200
        h, w, _ = rgb.shape
        cy, cx = h // 2, w // 2

        # Slice the numpy array to isolate the center patch
        crop = rgb[cy-100:cy+100, cx-100:cx+100]

        # Calculate mean intensity and normalize to 0.0 - 1.0 float
        mean_16bit = np.mean(crop)
        noise_float = float(mean_16bit /65535.0)

        # --- PREVIEW GENERATION ---
        # Convert to BGR for OpenCV Processing
        img_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        # Downscale 16-bit to 8-bit for JPEG saving
        img_8bit = (img_bgr /256.0).astype(np.uint8)

        # Burn a bright green rectangle to show the user exactly what area was measured
        # Parameters: image, top-left coord, bottom-right coord, color (BGR), thickness
        cv2.rectangle(img_8bit, (cx-100, cy-100), (cx+100, cy+100), (0, 255, 0), 2)

        # Export the visual preview for the UI
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

