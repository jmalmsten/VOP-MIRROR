"""
VOP Module:     vop_math.py
Version:        v0.0.9
Description:    Centralized matrix projection logic.
                Enforced 360.0 multiplier for normalized rotation inputs.
"""
import numpy as np
from pyrr import Matrix44

def get_frustum_fit_matrix(fov, aspect_ratio, world_scale, position, rotation, width, height):
    proj = Matrix44.perspective_projection(float(fov), width/height, 0.1, 1000.0)
    
    fov_rad = np.radians(float(fov))
    frustum_h = 2.0 * np.tan(fov_rad / 2.0)
    frustum_w = frustum_h * (width / height)
    
    base_s_y = 1.0
    base_s_x = aspect_ratio
    
    fit_factor = 1.0
    if base_s_x > frustum_w:
        fit_factor = frustum_w / base_s_x
        
    s_x = base_s_x * fit_factor * world_scale
    s_y = base_s_y * fit_factor * world_scale
    s_z = world_scale 
    
    scale_mat = Matrix44.from_scale([s_x, s_y, s_z])
    translate_mat = Matrix44.from_translation(position)
    
    # Normalization: 1.0 input = 360.0 degrees. 0.25 input = 90.0 degrees.
    rot_x = Matrix44.from_x_rotation(np.radians(float(rotation[0]) * 360.0))
    rot_y = Matrix44.from_y_rotation(np.radians(float(rotation[1]) * 360.0))
    rot_z = Matrix44.from_z_rotation(np.radians(float(rotation[2]) * 360.0))
    
    model_mat = translate_mat * (rot_z * rot_y * rot_x) * scale_mat
    mvp = proj * model_mat
    
    return mvp.astype('f4').tobytes()