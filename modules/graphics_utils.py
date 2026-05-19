"""
VOP Module:     graphics_utils.py
Description:    GL Pipeline management.
                Enforces #version 300 es and overrides ModernGL's default 330 requirement.
                Added vertical flip to OpenCV image loading to match OpenGL texture coords.
                TextureManager now keys per-layer file lists by layer name (pm/bp1/bp2)
                to support three independent optical layers.
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


import moderngl
import numpy as np
import os
import cv2

def init_render_pipeline():
    vert = """
    #version 300 es
    layout (location = 0) in vec2 in_vert;
    layout (location = 1) in vec2 in_tex;
    uniform mat4 mvp;
    out vec2 v_tex;
    void main() {
        gl_Position = mvp * vec4(in_vert, 0.0, 1.0);
        v_tex = in_tex;
    }
    """
    
    frag = """
    #version 300 es
    precision mediump float;
    uniform sampler2D TexUnit;
    uniform vec3 filter_color;
    uniform bool mono_mode; // <-- Added the uniform receiver
    
    in vec2 v_tex;
    out vec4 f_color;
    
    void main() {
        vec4 tex_col = texture(TexUnit, v_tex);
        
        // <-- Convert to grayscale if the toggle is active
        if (mono_mode) {
            float gray = dot(tex_col.rgb, vec3(0.299, 0.587, 0.114));
            tex_col.rgb = vec3(gray);
        }
        
        f_color = tex_col * vec4(filter_color, 1.0);
    }
    """
    
    ctx = moderngl.create_context(require=300)
    prog = ctx.program(vertex_shader=vert, fragment_shader=frag)
    
    # Initialize the mono uniform to a safe default
    if 'mono_mode' in prog:
        prog['mono_mode'].value = False

    verts = np.array([
        -1.0,  1.0, 0.0, 1.0,
         1.0,  1.0, 1.0, 1.0,
        -1.0, -1.0, 0.0, 0.0,
         1.0, -1.0, 1.0, 0.0
    ], dtype='f4')
    
    vbo = ctx.buffer(verts)
    vao = ctx.vertex_array(prog, [(vbo, '2f 2f', 'in_vert', 'in_tex')])
    
    return ctx, prog, vao

class TextureManager:
    """
    Per-layer image cache and texture loader for the engine.
    
    The VOP renders multiple optical layers (PM = Projection Mag, BP1/BP2 = 
    BiPack reels). Each layer has its own folder of source frames on disk and 
    its own playhead position. This class loads frames lazily on demand,
    converts them to GPU textures, and caches the result so the same gate
    frame isn't re-read from disk on every camera frame.
    
    Cache key is the full file path, which lets all three layers share the
    single self.cache dict without collisions - paths from different folders
    can never collide.
    """

    # Layer key -> folder name (relative to BASE_DIR). The folder names are 
    # fixed by the on-disk layout managed by vop.py's upload routes. Order in 
    # this dict is meaningless; it's used only for lookups.
    LAYER_FOLDERS = {
        'pm':  'ProjMag',
        'bp1': 'ProjBiPack1',
        'bp2': 'ProjBiPack2',
    }

    def __init__(self, ctx, proj_dir, job_data):
        """
        proj_dir is the ProjMag directory. We derive sibling folders for BP1 
        and BP2 from its parent (BASE_DIR). Caller doesn't need to know 
        anything about bipack folders - the layer layout is encoded here.
        """
        self.ctx = ctx
        self.cache = {}

        # 1x1 pure-white texture used as a pass-through stand-in whenever a 
        # layer is hidden (eye-toggle off) or has no source frames on disk. 
        # White is multiplicatively identity in the blend pipeline, so swapping
        # it in for a real layer texture cleanly removes that layer's 
        # contribution without changing any other render state.
        white = np.ones((1,1,3), dtype='uint8') * 255
        self.white_tex = ctx.texture((1,1), 3, white.tobytes())

        valid_exts = ('.png', '.jpg', '.tif', '.tiff')
        base_path = os.path.dirname(proj_dir)  # parent of ProjMag = repo BASE_DIR

        # Scan every layer's folder once at job-start. Files are stored sorted
        # so that the playhead index maps deterministically to a gate frame.
        # If a folder is missing (shouldn't happen because vop.py creates them
        # at boot) we fall back to an empty list - load() then returns the 
        # white pass-through texture.
        self.layer_files = {}
        for layer_key, folder_name in self.LAYER_FOLDERS.items():
            folder_path = os.path.join(base_path, folder_name)
            if os.path.exists(folder_path):
                self.layer_files[layer_key] = sorted([
                    os.path.join(folder_path, f) for f in os.listdir(folder_path)
                    if f.lower().endswith(valid_exts)
                ])
            else:
                self.layer_files[layer_key] = []

    def load(self, playhead, layer='pm'):
        """
        Returns (texture, aspect_ratio) for the requested layer at the given
        playhead position.
        
        layer: one of 'pm', 'bp1', 'bp2'. Anything else falls back to PM for 
            safety, so a typo in a caller can't crash the engine.
        
        If the layer has no frames on disk, returns the white pass-through 
        texture with a default 16:9 aspect ratio - the engine's render path
        special-cases white_tex to skip the geometry transform entirely.
        
        Bit-depth handling (phase 2 of issue #169):
            OpenCV preserves the source dtype when reading 16-bit TIFFs, so 
            cv2.imread returns either uint8 or uint16 arrays depending on 
            the file. We detect this and upload accordingly:
            - uint8  -> 3 bytes/pixel,  moderngl default 'f1' dtype 
                        (preserves existing SSS/MDS behavior exactly).
            - uint16 -> 6 bytes/pixel,  moderngl 'f2' half-float dtype.
                        The shader still samples in normalized [0.0, 1.0] 
                        so no shader change is needed; the GPU does the 
                        uint16 -> half-float conversion at upload time.
        """
        files = self.layer_files.get(layer, self.layer_files.get('pm', []))

        if not files:
            return self.white_tex, 1.777
            
        # Clamp the playhead to the available range. The JK printer logic in 
        # the interpolator can produce gate indices that overshoot the end of
        # a sequence (e.g. stepping past the last frame on a held shot); 
        # clamping here means those overshoots safely hold on the last frame
        # instead of crashing with an IndexError.
        idx = max(0, min(len(files)-1, int(playhead)))
        f_path = files[idx]
        
        if f_path in self.cache: 
            return self.cache[f_path]
        
        # cv2.IMREAD_UNCHANGED preserves both the alpha channel (for PNGs) 
        # AND the source bit depth (8 vs 16). Without this flag, OpenCV 
        # would auto-strip alpha AND silently downcast 16-bit TIFFs to 
        # uint8 - which is exactly the 8bpc ceiling phase 2 is removing.
        img = cv2.imread(f_path, cv2.IMREAD_UNCHANGED)
        if img is None: 
            return self.white_tex, 1.777

        # ----- Alpha premultiply (dtype-aware) ----------------------------
        # The original code assumed uint8 throughout. For 16-bit sources we 
        # need the same logic but with the alpha normalization scaled to the 
        # dtype's max value (255 for uint8, 65535 for uint16). dtype is 
        # preserved across the multiplication via .astype() at the end.
        if len(img.shape) == 3 and img.shape[2] == 4:
            # Source max value for normalization. For uint8 = 255, uint16 = 65535.
            # np.iinfo gives us the right constant for whichever dtype OpenCV 
            # handed us, with no risk of getting it wrong by hardcoding.
            src_max = float(np.iinfo(img.dtype).max)
            alpha_mask = img[:, :, 3] / src_max  # 0.0..1.0 multiplier
            # Apply premultiply, then cast back to the original dtype so the 
            # rest of the pipeline (and the texture upload below) sees the 
            # same uint8 or uint16 array it expected.
            img[:, :, :3] = (img[:, :, :3] * alpha_mask[:, :, np.newaxis]).astype(img.dtype)
            img = img[:, :, :3]  # strip alpha; engine pipeline is strictly 3-channel

        h, w = img.shape[:2]
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        
        # Flip vertically: OpenCV is (0,0)=top-left, OpenGL is (0,0)=bottom-left.
        img = cv2.flip(img, 0)
        
        # ----- Texture upload (dtype-aware) -------------------------------
        # moderngl's dtype param controls the GPU-side storage format:
        #   'f1' = 8-bit per channel  (default - 1 byte, integer-normalized)
        #   'f2' = 16-bit half-float per channel (2 bytes, preserves uint16 range)
        # The shader samples textures as normalized floats in [0.0, 1.0] in 
        # both cases, so no shader change is needed - only the precision of 
        # what gets sampled changes. uint16 sources keep their full range; 
        # uint8 sources continue to behave exactly as before phase 2.
        if img.dtype == np.uint16:
            # 16-bit RGB upload. components=3 (R,G,B), dtype='f2' (half-float).
            # Note: moderngl reads img.tobytes() in row-major C order; uint16 
            # serializes to little-endian on every platform we care about, 
            # which matches GL_HALF_FLOAT's expected byte order on the GPU.
            tex = self.ctx.texture((w, h), 3, img.tobytes(), dtype='f2')
        else:
            # 8-bit RGB upload. Matches the pre-phase-2 behavior exactly so 
            # SSS / MDS jobs continue producing bit-identical output.
            tex = self.ctx.texture((w, h), 3, img.tobytes())
        
        self.cache[f_path] = (tex, w/h)
        return tex, w/h

        def release(self):
            for t, a in self.cache.values(): 
                t.release()
            self.white_tex.release()