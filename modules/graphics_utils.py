"""
VOP Module:     graphics_utils.py
Description:    GL Pipeline management.
                Enforces #version 300 es and overrides ModernGL's default 330 requirement.
                Added vertical flip to OpenCV image loading to match OpenGL texture coords.
"""
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
    in vec2 v_tex;
    out vec4 f_color;
    void main() {
        vec4 tex_col = texture(TexUnit, v_tex);
        f_color = tex_col * vec4(filter_color, 1.0);
    }
    """
    
    # Override ModernGL's default requirement of 330
    ctx = moderngl.create_context(require=300)
    
    prog = ctx.program(vertex_shader=vert, fragment_shader=frag)
    
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
    def __init__(self, ctx, proj_dir, job_data):
        self.ctx = ctx
        self.proj_dir = proj_dir
        self.bp_dir = os.path.join(os.path.dirname(proj_dir), "ProjBiPack")
        self.cache = {}
        
        white = np.ones((1,1,3), dtype='uint8') * 255
        self.white_tex = ctx.texture((1,1), 3, white.tobytes())

    def load(self, playhead, is_bipack=False):
        dir_path = self.bp_dir if is_bipack else self.proj_dir
        if not os.path.exists(dir_path): 
            return self.white_tex, 1.777
            
        files = sorted([f for f in os.listdir(dir_path) if f.lower().endswith(('.png','.jpg','.tif','.tiff'))])
        if not files: 
            return self.white_tex, 1.777
            
        idx = max(0, min(len(files)-1, int(playhead)))
        f_path = os.path.join(dir_path, files[idx])
        
        if f_path in self.cache: 
            return self.cache[f_path]
        
        img = cv2.imread(f_path)
        if img is None: 
            return self.white_tex, 1.777
            
        h, w = img.shape[:2]
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        
        # CRITICAL FIX: Flip image vertically to align OpenCV (0,0 top-left) 
        # with OpenGL (0,0 bottom-left) texture coordinates
        img = cv2.flip(img, 0)
        
        tex = self.ctx.texture((w, h), 3, img.tobytes())
        self.cache[f_path] = (tex, w/h)
        return tex, w/h

    def release(self):
        for t, a in self.cache.values(): 
            t.release()
        self.white_tex.release()