"""
VOP Module:     vop_math.py
Version:        v0.1.2
Description:    Centralized matrix projection logic.
                Stripped dynamic frustum fitting. Geometry scale is now strictly 
                driven by the static world_scale argument.
"""
#
###########################################################################
#
#                                   VOP
#                       Copyright (C) 2025  jmalmsten
#
#     This program is free software: you can redistribute it and/or modify 
#     it under the terms of the GNU Affero General Public License as 
#     published by the Free Software Foundation, either version 3 of the 
#     License, or (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful, but 
#     WITHOUT ANY WARRANTY; without even the implied warranty of 
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU 
#     Affero General Public License for more details.
#
#     You should have received a copy of the GNU Affero General Public 
#     License along with this program.  If not, see 
#     <http://www.gnu.org/licenses/>.
#
#     Source code for this application can be found at 
#     https://codeberg.org/jmalmsten-com/VOP
#
###########################################################################


import numpy as np
from pyrr import Matrix44

def get_frustum_fit_matrix(fov, aspect_ratio, world_scale, master_pos, master_rot, local_pos, local_rot, width, height):
    # 1. Perspective Projection Matrix
    # Defines the viewing volume based on the active FOV.
    proj = Matrix44.perspective_projection(float(fov), width/height, 0.1, 1000.0)
    
    # 2. Physical Geometry Scale
    # Base geometry is 1.0 units high. Width is defined by the image aspect ratio.
    # Multiplying by world_scale dictates the absolute physical size of the quad in 3D space.
    s_x = aspect_ratio * float(world_scale)
    s_y = 1.0 * float(world_scale)
    s_z = float(world_scale) 
    
    scale_mat = Matrix44.from_scale([s_x, s_y, s_z])
    
    # 3. Child Transform (Local Smear Space)
    loc_rot_x = Matrix44.from_x_rotation(np.radians(float(local_rot[0]) * 360.0))
    loc_rot_y = Matrix44.from_y_rotation(np.radians(float(local_rot[1]) * 360.0))
    loc_rot_z = Matrix44.from_z_rotation(np.radians(float(local_rot[2]) * 360.0))
    loc_trans = Matrix44.from_translation(local_pos)
    local_mat = loc_trans * (loc_rot_z * loc_rot_y * loc_rot_x)
    
    # 4. Parent Transform (Global Master Space)
    mst_rot_x = Matrix44.from_x_rotation(np.radians(float(master_rot[0]) * 360.0))
    mst_rot_y = Matrix44.from_y_rotation(np.radians(float(master_rot[1]) * 360.0))
    mst_rot_z = Matrix44.from_z_rotation(np.radians(float(master_rot[2]) * 360.0))
    mst_trans = Matrix44.from_translation(master_pos)
    master_mat = mst_trans * (mst_rot_z * mst_rot_y * mst_rot_x)
    
    # 5. Model Matrix Compilation & Final MVP
    model_mat = master_mat * local_mat * scale_mat
    mvp = proj * model_mat
    
    return mvp.astype('f4').tobytes()