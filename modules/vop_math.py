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


def get_frustum_fit_matrix(fov, aspect_ratio, world_scale, master_pos, master_rot, local_pos, local_rot, width, height, par_x=1.0, par_y=1.0):
    # 1. Perspective Projection Matrix
    # Defines the viewing volume based on the active FOV.
    proj = Matrix44.perspective_projection(float(fov), width/height, 0.1, 1000.0)
    
    # 1b. ANAMORPHIC SQUEEZE
    # Apply a non-uniform scale in clip space (post-multiplied onto the projection
    # matrix) so the rendered geometry is pre-distorted on the HDMI screen. The
    # camera then captures the squeezed image, and the NLE unsqueezes it in post
    # using the same PAR metadata we write to the ProRes container.
    #
    # The convention is: PAR = pixel_width : pixel_height. So:
    #   PAR > 1 (wide pixels, e.g. 4:3 -> 1.333):
    #       NLE will stretch X horizontally in post -> we squeeze X here by 1/PAR.
    #   PAR < 1 (tall pixels, e.g. 1:1.24):
    #       NLE will stretch Y vertically in post -> we squeeze Y here by PAR.
    #
    # We always clamp to <=1.0 so the squeezed image stays inside the existing
    # 1920x1080 frame (we never grow past the edges). The unsqueezed-axis stays
    # at 1.0, leaving black bars on the screen that the NLE will discard via
    # the unsqueeze. PAR == 1 collapses cleanly to identity (no-op).
    px = float(par_x) if float(par_x) > 0 else 1.0
    py = float(par_y) if float(par_y) > 0 else 1.0
    par = px / py
    sx_anam = min(1.0, 1.0 / par)   # <=1.0 always
    sy_anam = min(1.0, par)         # <=1.0 always
    anam_scale = Matrix44.from_scale([sx_anam, sy_anam, 1.0])
    proj = anam_scale * proj  # bake the squeeze into the projection
    
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