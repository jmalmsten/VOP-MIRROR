"""
VOP Module:     color_utils.py
Version:        v0.0.4
Description:    16-bit linear workspace modifications and latent image accumulation.
                This module handles the simulation of physical optical filters and film layering.
"""
import os
# cv2 (OpenCV) is used for high-performance image matrix operations.
import cv2
# rawpy parses the raw Bayer data from DNG files.
import rawpy
import numpy as np

def process_and_stack_latent_image(buffer_file, output_file, tiff_flag, cam_gel_rgb, mono_forced):
    """
    Converts raw DNG to 16-bit TIFF, applies gel multiplication, and accumulates exposures.
    """
    # Guard clause to ensure we do not process a file that failed to write to disk.
    if not os.path.exists(buffer_file):
        return False
        
    # Open the DNG file. We strictly disable auto-brightness and force a linear gamma (1,1) 
    # to maintain true optical luminance values. We output as a 16-bit integer array.
    with rawpy.imread(buffer_file) as raw:
        img = cv2.cvtColor(raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16), cv2.COLOR_RGB2BGR)
        
    if mono_forced:
        # If monochrome is forced, collapse the color channels based on standard luminance weighting, 
        # then expand back to 3 channels so array shapes match the expected BGR format.
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    # Convert the UI hex color into a BGR float array. OpenCV defaults to BGR, not RGB.
    gel_bgr = np.array([cam_gel_rgb[2], cam_gel_rgb[1], cam_gel_rgb[0]], dtype=np.float32)
    
    # Apply the Camera Gel. This simulates a physical gel by multiplying the captured light values 
    # by the gel values. The result is clipped to 65535 (the maximum value for a 16-bit integer) 
    # to prevent integer overflow wrapping (e.g., 65536 turning into 0), then cast back to uint16.
    img = (img.astype(np.float32) * gel_bgr).clip(0, 65535).astype(np.uint16)

    # LIME Logic (Latent Image Multiple Exposure).
    # If a latent frame already exists on disk for this frame number, load it and use cv2.add 
    # to mathematically sum the new exposure values onto the old ones, simulating multiple exposures 
    # on the same frame of physical film.
    if os.path.exists(output_file):
        existing = cv2.imread(output_file, cv2.IMREAD_UNCHANGED)
        if existing is not None and existing.shape == img.shape:
            img = cv2.add(existing, img)
            
    # Write the final composite to disk using the defined TIFF compression flag.
    cv2.imwrite(output_file, img, [cv2.IMWRITE_TIFF_COMPRESSION, tiff_flag])
    
    # Remove the temporary DNG buffer to free disk space.
    os.remove(buffer_file)
    return True

def generate_sensor_preview(buffer_file, static_dir, cam_gel_rgb, mono_forced):
    """
    Generates an 8-bit JPEG preview directly from the sensor DNG.
    This skips the 16-bit overhead specifically for real-time UI probe updates.
    """
    if not os.path.exists(buffer_file):
        return False
        
    # Standard 8-bit post-processing for immediate visual review.
    with rawpy.imread(buffer_file) as raw:
        img = cv2.cvtColor(raw.postprocess(gamma=(1,1), no_auto_bright=True), cv2.COLOR_RGB2BGR)
        
    if mono_forced:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    gel_bgr = np.array([cam_gel_rgb[2], cam_gel_rgb[1], cam_gel_rgb[0]], dtype=np.float32)
    
    # Multiply the 8-bit image array by the gel values, clipping to the 8-bit maximum (255).
    img = (img.astype(np.float32) * gel_bgr).clip(0, 255).astype(np.uint8)

    # Write out a standard JPEG to the static directory where the Flask web server can serve it to the UI.
    cv2.imwrite(os.path.join(static_dir, "probe_live.jpg"), img)
    os.remove(buffer_file)
    return True

def write_screen_capture(pixels, width, height, static_dir):
    """
    Writes raw Pygame/ModernGL screen buffers to a JPEG.
    Used for projecting probes without triggering the physical camera.
    """
    # Convert the raw byte buffer from the GPU back into a 3D numpy array.
    # The [::-1] operation flips the image vertically, as OpenGL's origin (0,0) is at the bottom-left, 
    # whereas standard image formats originate from the top-left.
    cap = np.frombuffer(pixels, dtype='u1').reshape(height, width, 3)[::-1]
    cv2.imwrite(os.path.join(static_dir, "probe_live.jpg"), cv2.cvtColor(cap, cv2.COLOR_RGB2BGR))
