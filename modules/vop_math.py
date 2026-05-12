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


# Added rot_order parameter. Defaults to "XYZ" which reproduces the
# previous hardcoded Z*Y*X composition exactly — so old jobs render
# identically when rot_order is absent.
def get_frustum_fit_matrix(fov, aspect_ratio, world_scale, master_pos, master_rot, local_pos, local_rot, width, height, par_x=1.0, par_y=1.0, rot_order="XYZ"):    # 1. Perspective Projection Matrix
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
    # Build per-axis rotation matrices for the local transform. The tuple
    # local_rot is (pitch, roll, yaw) = (X, Y, Z), with 1.0 meaning a full
    # 360° rotation around that axis.
    loc_rot_x = Matrix44.from_x_rotation(np.radians(float(local_rot[0]) * 360.0))
    loc_rot_y = Matrix44.from_y_rotation(np.radians(float(local_rot[1]) * 360.0))
    loc_rot_z = Matrix44.from_z_rotation(np.radians(float(local_rot[2]) * 360.0))
    loc_trans = Matrix44.from_translation(local_pos)
    
    # 4. Parent Transform (Global Master Space)
    # Same axis matrices, but for the master (parent) frame. Built up the
    # same way; the only difference between local and master is which
    # position/rotation tuple feeds them and which gets multiplied first
    # in step 5.
    mst_rot_x = Matrix44.from_x_rotation(np.radians(float(master_rot[0]) * 360.0))
    mst_rot_y = Matrix44.from_y_rotation(np.radians(float(master_rot[1]) * 360.0))
    mst_rot_z = Matrix44.from_z_rotation(np.radians(float(master_rot[2]) * 360.0))
    mst_trans = Matrix44.from_translation(master_pos)
    
    # 4b. Rotation Order Composition
    # The rot_order string (e.g. "XYZ", "ZYX") is read left-to-right as
    # "first axis applied to the vertex, then second, then third" — this
    # is the Maya/Blender/glTF convention. In matrix math, "applied first
    # to a vertex" means the RIGHTMOST factor in the product, because
    # transforms compose right-to-left when multiplied onto a column
    # vector. So "XYZ" -> Z * Y * X, "ZYX" -> X * Y * Z, etc.
    #
    # We sanitize the input: uppercase it, then fall back to "XYZ" if it
    # isn't one of the six valid permutations. This means malformed or
    # missing rot_order values cleanly reproduce the original behavior
    # rather than crashing mid-render.
    order = (rot_order or "XYZ").upper()
    valid_orders = {"XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX"}
    if order not in valid_orders:
        order = "XYZ"
    
    # Lookup tables keyed by the user-facing order string. The value is a
    # function that takes the three axis matrices (x, y, z) and returns
    # the composed rotation in the matrix-multiplication order needed to
    # achieve that read-order. Using lambdas keeps this declarative and
    # easy to verify against the table in the source comments above.
    loc_compose = {
        "XYZ": lambda x, y, z: z * y * x,  # apply X first, then Y, then Z
        "XZY": lambda x, y, z: y * z * x,  # apply X first, then Z, then Y
        "YXZ": lambda x, y, z: z * x * y,  # apply Y first, then X, then Z
        "YZX": lambda x, y, z: x * z * y,  # apply Y first, then Z, then X
        "ZXY": lambda x, y, z: y * x * z,  # apply Z first, then X, then Y
        "ZYX": lambda x, y, z: x * y * z,  # apply Z first, then Y, then X
    }
    
    # Compose the local and master rotation matrices using the same
    # rotation order for both. The local and master frames share the
    # rot_order setting — there is only one project-wide setting; it
    # would be confusing if the parent and child interpreted Euler
    # tuples differently.
    local_rot_mat = loc_compose[order](loc_rot_x, loc_rot_y, loc_rot_z)
    master_rot_mat = loc_compose[order](mst_rot_x, mst_rot_y, mst_rot_z)
    
    local_mat = loc_trans * local_rot_mat
    master_mat = mst_trans * master_rot_mat
    
    # 5. Model Matrix Compilation & Final MVP
    model_mat = master_mat * local_mat * scale_mat
    mvp = proj * model_mat
    
    return mvp.astype('f4').tobytes()