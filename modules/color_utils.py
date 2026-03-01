"""
VOP Module:     color_utils.py
Version:        v0.0.5
Description:    16-bit linear workspace modifications and latent image accumulation.
                This handles all the physical film simulations (BiPacking, Gels, LIME).
"""
# os is required to check if files exist and to delete temporary buffers.
import os
# cv2 (OpenCV) is the core library used for high-speed image array manipulation.
import cv2
# rawpy is a wrapper for LibRaw, allowing us to read the uncompressed Bayer data from DNGs.
import rawpy
# numpy is used to create color arrays for the gel multiplications.
import numpy as np

def process_and_stack_latent_image(buffer_file, output_file, tiff_flag, cam_gel_rgb, mono_forced):
    """
    The LIME Engine (Latent Image Multiple Exposure).
    Converts raw DNG to 16-bit TIFF, applies gel multiplication, and adds it to existing frames.
    """
    # Guard clause: If the camera failed to write the DNG, abort immediately to prevent crashes.
    if not os.path.exists(buffer_file):
        return False
        
    # Open the DNG file using rawpy.
    with rawpy.imread(buffer_file) as raw:
        # postprocess() debayers the raw data into a visible image.
        # gamma=(1,1) forces linear color (no contrast curve applied).
        # no_auto_bright=True prevents the library from arbitrarily changing the exposure.
        # output_bps=16 forces the data into 16-bit integers (0 to 65535) for maximum fidelity.
        # cvtColor switches the colors from RGB to BGR, which is OpenCV's required format.
        img = cv2.cvtColor(raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16), cv2.COLOR_RGB2BGR)
        
    if mono_forced:
        # If the user enabled monochrome, we convert to grayscale (which uses standard luminance weighting),
        # and then convert back to a 3-channel BGR image so our math arrays don't break.
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    # Convert the UI hex color into a BGR float array.
    gel_bgr = np.array([cam_gel_rgb[2], cam_gel_rgb[1], cam_gel_rgb[0]], dtype=np.float32)
    
    # Multiply the image array by the gel values. 
    # .clip(0, 65535) is crucial: it prevents integer overflow. Without it, a pixel that reaches 65536 
    # would wrap around to 0 (pure black), creating bizarre artifacts in bright spots.
    img = (img.astype(np.float32) * gel_bgr).clip(0, 65535).astype(np.uint16)

    # LIME Stack Logic: Check if the final output file already exists (e.g., this is Exposure 2 of 3).
    if os.path.exists(output_file):
        # IMREAD_UNCHANGED forces OpenCV to read the 16-bit file as 16-bit. 
        # Without it, OpenCV quietly downgrades the file to 8-bit.
        existing = cv2.imread(output_file, cv2.IMREAD_UNCHANGED)
        
        # Ensure the existing file matches our current resolution to prevent matrix shape crashes.
        if existing is not None and existing.shape == img.shape:
            # Mathematically sum the new exposure values onto the old ones.
            img = cv2.add(existing, img)
            
    # Write the final composite to disk. tiff_flag determines if it's uncompressed (1) or zipped (8).
    cv2.imwrite(output_file, img, [cv2.IMWRITE_TIFF_COMPRESSION, tiff_flag])
    
    # Delete the temporary DNG buffer.
    os.remove(buffer_file)
    
    # BUGFIX CLEANUP: Locate the dummy JPEG created by rpicam-still and delete it.
    # Without this, the /tmp/ ramdisk would eventually fill up with thousands of JPEGs, crashing the Pi.
    dummy_jpg = buffer_file.replace(".dng", ".jpg")
    if os.path.exists(dummy_jpg):
        os.remove(dummy_jpg)
        
    return True

def generate_sensor_preview(buffer_file, static_dir, cam_gel_rgb, mono_forced):
    """
    Generates an 8-bit JPEG preview directly from the sensor DNG for the web UI.
    This skips all the heavy 16-bit overhead for speed.
    """
    if not os.path.exists(buffer_file):
        return False
        
    with rawpy.imread(buffer_file) as raw:
        # Omitting output_bps defaults to 8-bit (0 to 255).
        img = cv2.cvtColor(raw.postprocess(gamma=(1,1), no_auto_bright=True), cv2.COLOR_RGB2BGR)
        
    if mono_forced:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

    gel_bgr = np.array([cam_gel_rgb[2], cam_gel_rgb[1], cam_gel_rgb[0]], dtype=np.float32)
    
    # Multiply and clip to the 8-bit maximum (255).
    img = (img.astype(np.float32) * gel_bgr).clip(0, 255).astype(np.uint8)

    # Write the JPEG into the Flask static directory so the browser can request it.
    cv2.imwrite(os.path.join(static_dir, "probe_live.jpg"), img)
    
    # Cleanup both the DNG and the Dummy JPEG.
    os.remove(buffer_file)
    dummy_jpg = buffer_file.replace(".dng", ".jpg")
    if os.path.exists(dummy_jpg):
        os.remove(dummy_jpg)
        
    return True

def write_screen_capture(pixels, width, height, static_dir):
    """
    Writes raw Pygame/ModernGL screen buffers to a JPEG.
    Used for UI probes when we just want to see the projector output without taking a physical photo.
    """
    # The raw buffer from the GPU is a 1D string of bytes. 
    # reshape() forces it into a 3D array (Height x Width x 3 RGB channels).
    # [::-1] flips the image vertically. OpenGL draws from the bottom-left up, 
    # but JPEGs are drawn from the top-left down.
    cap = np.frombuffer(pixels, dtype='u1').reshape(height, width, 3)[::-1]
    
    # Convert RGB to BGR and save.
    cv2.imwrite(os.path.join(static_dir, "probe_live.jpg"), cv2.cvtColor(cap, cv2.COLOR_RGB2BGR))