"""
VOP Module:     color_utils.py
Description:    16-bit linear workspace modifications and latent image accumulation.
"""
import os
import cv2
import rawpy
import numpy as np

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
        
        # 1. Apply the Pedestal subtraction FIRST
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

def process_and_stack_latent_image(buffer_file, output_file, tiff_flag, cam_gel_rgb, mono_forced, black_clip=0.0):
    if not os.path.exists(buffer_file): return False

    try:
        with rawpy.imread(buffer_file) as raw:
            rgb = raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16)
    
        # 1. Apply the pedestal subtraction FIRST
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