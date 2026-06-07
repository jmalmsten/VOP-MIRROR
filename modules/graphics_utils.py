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
    
    # FRAGMENT SHADER
    #
    # Samples the bound texture, optionally applies a source-slice
    # remap (BRK mode), optionally converts to grayscale, and
    # multiplies by the per-frame filter color (PG*CG combined gel).
    #
    # The slice remap is bracketed-mode specific. When slice_active
    # is true, the sampled texture color (assumed to represent a
    # normalized 16bpc source value in [0..1]) is linearly mapped
    # so that source value slice_low maps to screen 0.0 and
    # source value slice_high maps to screen 1.0. Values outside
    # [slice_low, slice_high] clip. This is what lets BRK use the
    # 8-bit projection panel to show a fine slice of the 16bpc
    # source range without losing precision to the panel's
    # quantization.
    #
    # When slice_active is false (default), the remap is bypassed
    # and tex_col passes through untouched. All non-BRK modes
    # (SSS, MDS, DRE) rely on this default - they never set
    # slice_active, so they get exactly the same fragment output
    # they did before this uniform existed.
    frag = """
    #version 300 es
    precision mediump float;
    uniform sampler2D TexUnit;
    uniform vec3 filter_color;
    uniform bool mono_mode;

    // BRK source-slice remap uniforms.
    // slice_active=false (default) bypasses the remap entirely,
    // making the shader behave identically to the pre-BRK build.
    // When true, slice_low / slice_high define the source range
    // that gets stretched to fill screen [0..1].
    uniform bool slice_active;
    uniform float slice_low;
    uniform float slice_high;

    in vec2 v_tex;
    out vec4 f_color;

    void main() {
        vec4 tex_col = texture(TexUnit, v_tex);

        // BRK SOURCE-SLICE REMAP
        // Active only when slice_active is set by the engine
        // (BRK execute path); off in all other modes.
        // Implemented per-channel because BRK source is RGB and
        // each channel undergoes the same remap independently.
        // The clamp at the end ensures pixels outside the slice
        // clip cleanly to 0 or 1 rather than producing negatives
        // or values >1 that would interact weirdly with the
        // filter multiply below.
        if (slice_active) {
            float slice_width = slice_high - slice_low;
            tex_col.rgb = clamp((tex_col.rgb - slice_low) / slice_width, 0.0, 1.0);
        }

        // MONOCHROME PATH (unchanged from before)
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
        
    # BRK slice-remap uniforms: initialize to passthrough defaults
    # so that any code path that doesn't explicitly set them
    # behaves identically to the pre-BRK shader. The engine's
    # BRK execute path will override these per-bracket. The
    # 'in prog' guards protect against drivers that strip
    # unused uniforms during shader compilation (unlikely with
    # an `if (slice_active)` branch keeping them referenced,
    # but defensive). If a uniform is missing, the default-
    # behavior path (slice_active=false) still holds because
    # missing uniforms in GLSL default to 0/false, which is
    # exactly our passthrough configuration.
    if 'slice_active' in prog:
        prog['slice_active'].value = False
    if 'slice_low' in prog:
        prog['slice_low'].value = 0.0
    if 'slice_high' in prog:
        prog['slice_high'].value = 1.0

    verts = np.array([
        -1.0,  1.0, 0.0, 1.0,
         1.0,  1.0, 1.0, 1.0,
        -1.0, -1.0, 0.0, 0.0,
         1.0, -1.0, 1.0, 0.0
    ], dtype='f4')
    
    vbo = ctx.buffer(verts)
    vao = ctx.vertex_array(prog, [(vbo, '2f 2f', 'in_vert', 'in_tex')])
    
    return ctx, prog, vao


def init_calibration_targets(ctx):
    """
    Build a SECOND, independent program + fullscreen quad that draws the
    framing/focus targets (issue #198): corner crosshairs at a 10% inset
    plus a centre moire (Siemens-star) focus pattern.

    Kept entirely separate from init_render_pipeline's textured-quad
    program so the alignment overlay never shares or disturbs the
    exposure/idle render state. It owns its own program and its own
    fullscreen quad buffer; the engine renders it in the idle branch only
    while the calibration sentinel file exists.

    Returns (cal_prog, cal_vao). Render cal_vao as a TRIANGLE_STRIP.
    """
    # VERTEX SHADER: plain fullscreen pass-through. No mvp - the quad is
    # already in NDC (-1..1), so we just forward position and hand the
    # 0..1 uv to the fragment shader to draw against.
    vert = """
    #version 300 es
    layout (location = 0) in vec2 in_vert;
    layout (location = 1) in vec2 in_tex;
    out vec2 v_tex;
    void main() {
        gl_Position = vec4(in_vert, 0.0, 1.0);
        v_tex = in_tex;
    }
    """

    # FRAGMENT SHADER: everything is procedural, so the targets stay
    # razor-sharp at any panel resolution with no texture to upload.
    # highp (not mediump) because the centre moire's atan/sin at fine
    # angles needs the precision to avoid shimmer artefacts of its own -
    # this matches the old standalone vop_setup_align.py which worked well.
    frag = """
    #version 300 es
    precision highp float;
    in vec2 v_tex;
    out vec4 f_col;

    // Panel width/height. Used to undo the UV stretch on non-square
    // panels so the centre target is a true circle, not an ellipse.
    uniform float u_aspect;

    void main() {
        vec2 uv = v_tex;
        vec3 col = vec3(0.0);

        // ---- CENTRE FOCUS / MOIRE TARGET ----
        // Centre the coords (-1..1) and stretch x by the panel aspect so
        // the radial pattern is circular. A dense 64-spoke grating creates
        // a strong moire shimmer that resolves into crisp, separate spokes
        // exactly at best focus - the classic optical-printer focus aid.
        vec2 c = (uv - 0.5) * 2.0;
        c.x *= u_aspect;
        float d = length(c);
        if (d < 0.35) {
            float a = atan(c.y, c.x);
            float spokes = step(0.0, sin(a * 64.0));
            // Fade the innermost few percent so the spokes don't collapse
            // into aliased mush right at the hub where they all converge.
            col += vec3(spokes * smoothstep(0.01, 0.04, d));
        }

        // ---- CORNER CROSSHAIRS (10% inset from each edge) ----
        // A '+' at each of the four corners. Their CENTRES (0.1 / 0.9 in
        // uv) are exactly what the feed-overlay boxes will target in
        // Slice 3, and those centres are aspect-independent, which is why
        // the crosshairs stay in plain uv space (only the centre circle
        // needs aspect correction). t = arm thickness, l = arm half-length.
        float t = 0.0015;
        float l = 0.04;
        vec2 p = vec2(0.1);   // inset fraction from the edges

        // Vertical arms: narrow in x, extended in y, at all four corners.
        bool vbar =
            (abs(uv.x - p.x)       < t && abs(uv.y - p.y)       < l) ||
            (abs(uv.x - (1.0-p.x)) < t && abs(uv.y - p.y)       < l) ||
            (abs(uv.x - p.x)       < t && abs(uv.y - (1.0-p.y)) < l) ||
            (abs(uv.x - (1.0-p.x)) < t && abs(uv.y - (1.0-p.y)) < l);

        // Horizontal arms: narrow in y, extended in x, at all four corners.
        bool hbar =
            (abs(uv.y - p.y)       < t && abs(uv.x - p.x)       < l) ||
            (abs(uv.y - (1.0-p.y)) < t && abs(uv.x - p.x)       < l) ||
            (abs(uv.y - p.y)       < t && abs(uv.x - (1.0-p.x)) < l) ||
            (abs(uv.y - (1.0-p.y)) < t && abs(uv.x - (1.0-p.x)) < l);

        if (vbar || hbar) col = vec3(1.0);

        f_col = vec4(col, 1.0);
    }
    """

    cal_prog = ctx.program(vertex_shader=vert, fragment_shader=frag)

    # Safe default so a render before the engine first sets it still
    # produces a circle on a square panel (and never divides by zero).
    if 'u_aspect' in cal_prog:
        cal_prog['u_aspect'].value = 1.0

    # Fullscreen quad. SAME [x, y, u, v] vertex layout and TRIANGLE_STRIP
    # winding as init_render_pipeline's quad, so the '2f 2f' format string
    # and attribute names line up identically - one less thing to diverge.
    verts = np.array([
        -1.0,  1.0, 0.0, 1.0,
         1.0,  1.0, 1.0, 1.0,
        -1.0, -1.0, 0.0, 0.0,
         1.0, -1.0, 1.0, 0.0
    ], dtype='f4')

    vbo = ctx.buffer(verts)
    cal_vao = ctx.vertex_array(cal_prog, [(vbo, '2f 2f', 'in_vert', 'in_tex')])

    return cal_prog, cal_vao


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
        #   'f2' = 16-bit half-float per channel (2 bytes)
        # The shader samples textures as normalized floats in [0.0, 1.0] in 
        # both cases, so no shader change is needed - only the precision of 
        # what gets sampled changes.
        if img.dtype == np.uint16:
            # IMPORTANT: uint16 and float16 are both 2 bytes per channel but 
            # have COMPLETELY different bit layouts. A uint16 value of 65535 
            # would, if reinterpreted as a float16, be +Inf - not 1.0. So we 
            # cannot just hand the uint16 buffer to moderngl with dtype='f2' 
            # and hope for the best (an earlier phase-2 implementation did 
            # exactly this and produced garbage on real 16-bit gradient 
            # sources - looked plausible on solid colors but wrong on ramps).
            # 
            # The fix: convert uint16 [0..65535] to actual half-float [0..1] 
            # in numpy, where we can see the math. We go via float32 as an 
            # intermediate because:
            #   1. Dividing uint16 by 65535.0 needs a float wide enough to 
            #      hold both operands without overflow. float32 has plenty 
            #      of headroom; float16 would overflow on the divisor.
            #   2. Doing the divide in float32 means the values we cast to 
            #      float16 are already in [0,1] - well within float16's 
            #      representable range, so the final cast is precision-loss 
            #      only (no overflow, no inf).
            # 
            # The cost is one full-image float32 buffer per cache-miss load. 
            # At 1080p this is 1920*1080*3*4 = ~24MB transient - cheap 
            # relative to the disk read we just did.
            img_norm = img.astype(np.float32) / 65535.0  # uint16 -> float32 [0,1]
            img_f16  = img_norm.astype(np.float16)        # float32 -> float16, same range
            tex = self.ctx.texture((w, h), 3, img_f16.tobytes(), dtype='f2')
        else:
            # 8-bit RGB upload. Matches the pre-phase-2 behavior exactly so 
            # SSS / MDS jobs with 8-bit sources continue producing 
            # bit-identical output.
            tex = self.ctx.texture((w, h), 3, img.tobytes())
        
        self.cache[f_path] = (tex, w/h)
        return tex, w/h

    def release(self):
        """
        Free all GPU textures owned by this manager. Called by 
        run_persistent_engine at end-of-task to release VRAM before 
        the next job's texture manager is created.
        
        Was buried inside load() due to a phase-2 indentation slip - 
        meaning every job from phase 2 through phase 3 was crashing 
        in cleanup with 'TextureManager has no attribute release', 
        but the crash happened AFTER the exposure produced output so 
        it appeared to work. Fixed here as part of phase 3 follow-up.
        """
        for t, a in self.cache.values(): 
            t.release()
        self.white_tex.release()