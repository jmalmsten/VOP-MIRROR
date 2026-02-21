"""
VOP Module:     vop_math.py
Version:        v0.0.2
Description:    Centralized matrix projection and spatial transformation logic.
"""
import numpy as np
from pyrr import Matrix44

def get_frustum_fit_matrix(fov, aspect_ratio, world_scale, position, rotation, width, height):
    """
    Constructs the Model-View-Projection (MVP) matrix.
    Enforces containment scaling: Height = World Scale, Width = World Scale * Aspect Ratio.
    """
    proj = Matrix44.perspective_projection(float(fov), width/height, 0.1, 1000.0)
    
    fov_rad = np.radians(float(fov))
    frustum_h = np.tan(fov_rad / 2.0)
    frustum_w = frustum_h * (width / height)
    
    base_s_y = world_scale
    base_s_x = world_scale * aspect_ratio
    
    fit_factor = 1.0
    if base_s_x > frustum_w:
        fit_factor = frustum_w / base_s_x
        
    s_x = base_s_x * fit_factor
    s_y = base_s_y * fit_factor
    s_z = world_scale 
    
    scale_mat = Matrix44.from_scale([s_x, s_y, s_z])
    translate_mat = Matrix44.from_translation(position)
    rot_x = Matrix44.from_x_rotation(np.radians(rotation[0]))
    rot_y = Matrix44.from_y_rotation(np.radians(rotation[1]))
    rot_z = Matrix44.from_z_rotation(np.radians(rotation[2]))
    
    model = translate_mat * rot_x * rot_y * rot_z * scale_mat
    
    return (proj * model).astype('f4')
