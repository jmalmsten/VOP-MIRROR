"""
VOP Module:     color_utils.py
Version:        v0.0.4
Description:    16-bit linear workspace modifications and latent image accumulation.
"""
import os
import cv2
import rawpy
import numpy as np

def process_and_stack_latent_image(buffer_file, output_file, tiff_flag, cam_gel_rgb, mono_forced):
    """
    Converts raw DNG to 16-bit TIFF, applies gel multiplication, and accumulates exposures.
    """
    if not os.path.exists(buffer_file):
        return False
        
    with rawpy.imread(buffer_file) as raw:
        img = cv2.cvtColor(raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16), cv2.COLOR_RGB2BGR)
        
    if mono_forced:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    gel_bgr = np.array([cam_gel_rgb[2], cam_gel_rgb[1], cam_gel_rgb[0]], dtype=np.float32)
    img = (img.astype(np.float32) * gel_bgr).clip(0, 65535).astype(np.uint16)

    if os.path.exists(output_file):
        existing = cv2.imread(output_file, cv2.IMREAD_UNCHANGED)
        if existing is not None and existing.shape == img.shape:
            img = cv2.add(existing, img)
            
    cv2.imwrite(output_file, img, [cv2.IMWRITE_TIFF_COMPRESSION, tiff_flag])
    os.remove(buffer_file)
    return True

def generate_sensor_preview(buffer_file, static_dir, cam_gel_rgb, mono_forced):
    """
    Generates an 8-bit JPEG preview directly from the sensor DNG.
    """
    if not os.path.exists(buffer_file):
        return False
        
    with rawpy.imread(buffer_file) as raw:
        img = cv2.cvtColor(raw.postprocess(gamma=(1,1), no_auto_bright=True), cv2.COLOR_RGB2BGR)
        
    if mono_forced:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    gel_bgr = np.array([cam_gel_rgb[2], cam_gel_rgb[1], cam_gel_rgb[0]], dtype=np.float32)
    img = (img.astype(np.float32) * gel_bgr).clip(0, 255).astype(np.uint8)

    cv2.imwrite(os.path.join(static_dir, "probe_live.jpg"), img)
    os.remove(buffer_file)
    return True

def write_screen_capture(pixels, width, height, static_dir):
    """
    Writes raw Pygame/ModernGL screen buffers to a JPEG.
    """
    cap = np.frombuffer(pixels, dtype='u1').reshape(height, width, 3)[::-1]
    cv2.imwrite(os.path.join(static_dir, "probe_live.jpg"), cv2.cvtColor(cap, cv2.COLOR_RGB2BGR))
