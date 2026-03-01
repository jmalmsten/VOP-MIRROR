"""
VOP Module:     vop_math.py
Version:        v0.0.3
Description:    Centralized matrix projection and spatial transformation logic.
                By keeping all linear algebra here, we prevent "Math Creep" in the main engine.
"""

# NumPy is the standard Python library for high-performance numerical arrays.
# We need it here primarily for its trigonometric functions (like converting degrees to radians).
import numpy as np

# Pyrr is a 3D mathematics library heavily optimized for OpenGL.
# Matrix44 specifically handles the 4x4 matrices required to translate, rotate, and scale 3D objects.
from pyrr import Matrix44

def get_frustum_fit_matrix(fov, aspect_ratio, world_scale, position, rotation, width, height):
    """
    Constructs the final Model-View-Projection (MVP) matrix.
    This function guarantees that the projected image never crops, by dynamically
    scaling the 2x2 OpenGL quad to fit inside the camera's invisible viewing pyramid (the frustum).
    """
    
    # --- 1. THE PROJECTION MATRIX ---
    # This creates the "lens" of our virtual 3D camera.
    # float(fov): The Field of View in degrees. Wider FOV = more perspective distortion.
    # width/height: The aspect ratio of the physical display (the projector).
    # 0.1, 1000.0: The near and far clipping planes. Objects closer than 0.1 or further than 1000 vanish.
    proj = Matrix44.perspective_projection(float(fov), width/height, 0.1, 1000.0)
    
    # --- 2. THE FRUSTUM FIT LOGIC ---
    # We need to know exactly how wide and tall the "viewing window" is at a distance of Z = 1.0.
    # First, convert degrees to radians because np.tan requires radians.
    fov_rad = np.radians(float(fov))
    
    # The tangent of half the FOV gives us the exact half-height of the visible space.
    frustum_h = np.tan(fov_rad / 2.0)
    
    # We multiply that half-height by the window's aspect ratio to get the half-width.
    frustum_w = frustum_h * (width / height)
    
    # Establish our base scaling. 
    # The Y-axis (Height) is locked directly to the user's world_scale parameter.
    base_s_y = world_scale
    # The X-axis (Width) is scaled by the image's inherent aspect ratio to prevent the image from stretching.
    base_s_x = world_scale * aspect_ratio
    
    # fit_factor is our safety net against horizontal cropping.
    fit_factor = 1.0
    
    # If our calculated object width (base_s_x) is wider than the viewing window (frustum_w)...
    if base_s_x > frustum_w:
        # ...we shrink the fit_factor by the exact percentage it is over-sized.
        fit_factor = frustum_w / base_s_x
        
    # Apply the final safety scaling to both X and Y.
    s_x = base_s_x * fit_factor
    s_y = base_s_y * fit_factor
    # Z-scale is kept uniform, though scaling the Z-axis of a flat 2D image does nothing visually.
    s_z = world_scale 
    
    # --- 3. THE MODEL MATRIX ---
    # We create individual 4x4 matrices for every spatial property.
    scale_mat = Matrix44.from_scale([s_x, s_y, s_z])
    translate_mat = Matrix44.from_translation(position)
    
    # Rotations must be converted to radians for Pyrr.
    rot_x = Matrix44.from_x_rotation(np.radians(rotation[0])) # Pitch (Tilt up/down)
    rot_y = Matrix44.from_y_rotation(np.radians(rotation[1])) # Yaw (Pan left/right)
    rot_z = Matrix44.from_z_rotation(np.radians(rotation[2])) # Roll (Spin like a wheel)
    
    # Combine the transformations by multiplying the matrices together.
    # MATRIX MULTIPLICATION ORDER MATTERS! 
    # Translate * Rotate * Scale ensures the object rotates around its own center, not the world origin.
    model = translate_mat * rot_x * rot_y * rot_z * scale_mat
    
    # Multiply the Projection (Lens) by the Model (Position/Rotation/Scale).
    # .astype('f4') converts the 64-bit float matrix down to a 32-bit float array, which GLSL requires.
    return (proj * model).astype('f4')