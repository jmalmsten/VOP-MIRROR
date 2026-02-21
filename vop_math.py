"""
VOP Module:     vop_math.py
Version:        v0.0.2
Description:    Centralized matrix projection and spatial transformation logic.
                This module handles the linear algebra required to map 3D coordinates
                into the 2D optical projection space.
"""
# numpy is imported for high-performance numerical operations, specifically trigonometric 
# conversions (degrees to radians) and handling arrays which pyrr requires.
import numpy as np
# pyrr provides optimized 3D mathematics functions, specifically 4x4 matrices used in OpenGL.
from pyrr import Matrix44

def get_frustum_fit_matrix(fov, aspect_ratio, world_scale, position, rotation, width, height):
    """
    Constructs the Model-View-Projection (MVP) matrix.
    Enforces containment scaling: Height = World Scale, Width = World Scale * Aspect Ratio.
    
    Arguments:
        fov (float): Field of View in degrees.
        aspect_ratio (float): The width/height ratio of the loaded image texture.
        world_scale (float): The arbitrary scaling factor defined by the user.
        position (list/array): The 3D translation coordinates [X, Y, Z].
        rotation (list/array): The 3D rotation angles in degrees [Pitch, Yaw, Roll].
        width (int): The rendering window pixel width.
        height (int): The rendering window pixel height.
    """
    # 1. Perspective Projection Matrix
    # Creates a standard projection matrix mapping 3D space to the 2D screen.
    # The near plane is 0.1 and far plane is 1000.0 to prevent Z-clipping of normal operations.
    proj = Matrix44.perspective_projection(float(fov), width/height, 0.1, 1000.0)
    
    # 2. Containment Logic (Frustum Fit)
    # Convert FOV from degrees to radians because numpy's trigonometric functions require radians.
    fov_rad = np.radians(float(fov))
    
    # Calculate the half-height of the visible frustum at a distance of Z = 1.0.
    frustum_h = np.tan(fov_rad / 2.0)
    # Calculate the corresponding half-width by multiplying the height by the canvas aspect ratio.
    frustum_w = frustum_h * (width / height)
    
    # Define the baseline scale for the object. 
    # Y (Height) strictly matches the user's world_scale.
    base_s_y = world_scale
    # X (Width) is scaled by the image's inherent aspect ratio to prevent stretching.
    base_s_x = world_scale * aspect_ratio
    
    # The fit_factor ensures the image does not bleed outside the horizontal boundaries 
    # of the projection frustum when the image is exceptionally wide.
    fit_factor = 1.0
    if base_s_x > frustum_w:
        # If the image width exceeds the frustum width, reduce the fit_factor proportionally.
        fit_factor = frustum_w / base_s_x
        
    # Apply the final containment factor to the X and Y scales.
    s_x = base_s_x * fit_factor
    s_y = base_s_y * fit_factor
    # Z-scale is kept uniform to the world_scale, though it is largely irrelevant for a flat 2D quad.
    s_z = world_scale 
    
    # 3. Matrix Transformations
    # Create individual 4x4 matrices for each discrete transformation.
    scale_mat = Matrix44.from_scale([s_x, s_y, s_z])
    translate_mat = Matrix44.from_translation(position)
    rot_x = Matrix44.from_x_rotation(np.radians(rotation[0]))
    rot_y = Matrix44.from_y_rotation(np.radians(rotation[1]))
    rot_z = Matrix44.from_z_rotation(np.radians(rotation[2]))
    
    # Combine the transformations by multiplying the matrices.
    # Note: Matrix multiplication is non-commutative. The standard order is T * R * S
    # (Scale first, then Rotate, then Translate relative to the origin).
    model = translate_mat * rot_x * rot_y * rot_z * scale_mat
    
    # Multiply the Projection matrix by the Model matrix to get the final MVP matrix.
    # Return it explicitly as a 32-bit float ('f4') array, which is required by the GLSL shader.
    return (proj * model).astype('f4')
