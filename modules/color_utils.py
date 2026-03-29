"""
VOP Module:     color_utils.py
Version:        v0.0.7
Description:    16-bit linear workspace modifications and latent image accumulation.
                Updated screen capture parser to handle 4-channel FBO output.
"""
import os
import cv2
import rawpy
import numpy as np

def generate_sensor_preview(buffer_file, static_dir, cam_gel_rgb, mono_forced): # <-- Added mono_forced here
    if not os.path.exists(buffer_file): return False
    with rawpy.imread(buffer_file) as raw:
        img = raw.postprocess(gamma=(1,1), no_auto_bright=True)
    
    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    
    # Mono stripping logic here for previews
    if mono_forced:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    gel_bgr = np.array([cam_gel_rgb[2], cam_gel_rgb[1], cam_gel_rgb[0]], dtype=np.float32)
    img = (img.astype(np.float32) * gel_bgr).clip(0, 255).astype(np.uint8)
    cv2.imwrite(os.path.join(static_dir, "probe_live.jpg"), img)
    
    os.remove(buffer_file)
    dummy = buffer_file.replace(".dng", ".jpg")
    if os.path.exists(dummy): os.remove(dummy)
    return True

def process_and_stack_latent_image(buffer_file, output_file, tiff_flag, cam_gel_rgb, mono_forced):
    if not os.path.exists(buffer_file): return False
    with rawpy.imread(buffer_file) as raw:
        img = raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16)
    
    img = cv2.cvtColor(raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16), cv2.COLOR_RGB2BGR)
    
    if mono_forced:
        # Exploit monochrome clarity by stripping color before tinting
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    # Now apply the CG tint (cam_gel_rgb)
    gel_bgr = np.array([cam_gel_rgb[2], cam_gel_rgb[1], cam_gel_rgb[0]], dtype=np.float32)
    img = (img.astype(np.float32) * gel_bgr).clip(0, 65535).astype(np.uint16)

    if os.path.exists(output_file):
        existing = cv2.imread(output_file, cv2.IMREAD_UNCHANGED)
        if existing is not None:
            img = cv2.add(img, existing.astype(np.uint16))

    cv2.imwrite(output_file, img, [cv2.IMWRITE_TIFF_COMPRESSION, tiff_flag])

    os.remove(buffer_file)
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