"""
VOP Module:     vop_math.py
Version:        v0.1.0
Description:    Centralized matrix projection logic.
                Split Local and Master transforms to fix parent-child hierarchy issues.
"""
import numpy as np
from pyrr import Matrix44

def get_frustum_fit_matrix(fov, aspect_ratio, world_scale, master_pos, master_rot, local_pos, local_rot, width, height):
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
    
    # 1. Child Transform (Local Smear Space)
    loc_rot_x = Matrix44.from_x_rotation(np.radians(float(local_rot[0]) * 360.0))
    loc_rot_y = Matrix44.from_y_rotation(np.radians(float(local_rot[1]) * 360.0))
    loc_rot_z = Matrix44.from_z_rotation(np.radians(float(local_rot[2]) * 360.0))
    loc_trans = Matrix44.from_translation(local_pos)
    local_mat = loc_trans * (loc_rot_z * loc_rot_y * loc_rot_x)
    
    # 2. Parent Transform (Global Master Space)
    mst_rot_x = Matrix44.from_x_rotation(np.radians(float(master_rot[0]) * 360.0))
    mst_rot_y = Matrix44.from_y_rotation(np.radians(float(master_rot[1]) * 360.0))
    mst_rot_z = Matrix44.from_z_rotation(np.radians(float(master_rot[2]) * 360.0))
    mst_trans = Matrix44.from_translation(master_pos)
    master_mat = mst_trans * (mst_rot_z * mst_rot_y * mst_rot_x)
    
    # 3. Model Matrix Compilation
    model_mat = master_mat * local_mat * scale_mat
    mvp = proj * model_mat
    
    return mvp.astype('f4').tobytes()