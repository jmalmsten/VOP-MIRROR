"""
VOP Module:     graphics_utils.py
Version:        v0.0.1
Description:    Encapsulates ModernGL context, shaders, and texture management.
"""
import os
import glob
import pygame
import moderngl
import numpy as np

# --- GLSL Shaders ---
VERTEX_SHADER = """#version 300 es
in vec3 in_position; 
in vec2 in_texcoord; 
out vec2 v_tex; 
uniform mat4 mvp;
void main() { 
    gl_Position = mvp * vec4(in_position, 1.0); 
    v_tex = in_texcoord; 
}
"""

FRAGMENT_SHADER = """#version 300 es
precision highp float; 
in vec2 v_tex; 
out vec4 f_col; 
uniform sampler2D texture0; 
uniform vec3 filter_color; 
uniform bool mono_mode;
void main() { 
    vec4 t = texture(texture0, v_tex); 
    vec3 rgb = t.rgb * filter_color;
    if(mono_mode) {
        float y = dot(rgb, vec3(0.2126, 0.7152, 0.0722));
        rgb = vec3(y);
    }
    f_col = vec4(rgb, t.a); 
}
"""

def init_render_pipeline():
    """
    Initializes the ModernGL context and returns the pipeline objects.
    """
    ctx = moderngl.create_context(require=300)
    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    
    # Standard 2x2 Quad (Z=0, normalized coords)
    vbo_data = np.array([-1,-1,0, 0,0,  1,-1,0, 1,0,  -1,1,0, 0,1,  1,1,0, 1,1], dtype='f4')
    vbo = ctx.buffer(vbo_data)
    vao = ctx.vertex_array(prog, [(vbo, '3f 2f', 'in_position', 'in_texcoord')], mode=moderngl.TRIANGLE_STRIP)
    
    return ctx, prog, vao

class TextureManager:
    """
    Handles sequential and static texture loading from the Mag directories.
    """
    def __init__(self, ctx, proj_mag_dir, job_data):
        self.ctx = ctx
        self.proj_mag_dir = proj_mag_dir
        self.is_sequence = (job_data.get('image') == 'SEQUENCE')
        self.target_image = job_data.get('image', '')
        
        if self.is_sequence:
            self.seq_files = sorted(glob.glob(os.path.join(self.proj_mag_dir, "frame_*.tif")))
        else:
            self.seq_files = []
            
        self.current_idx = -1
        self.active_tex = None
        self.aspect_ratio = 1.0

    def load(self, idx_float):
        """
        Loads the requested frame index into VRAM. Returns (texture, aspect_ratio).
        """
        idx = int(idx_float)
        if idx == self.current_idx and self.active_tex is not None:
            return self.active_tex, self.aspect_ratio
            
        if self.active_tex:
            self.active_tex.release()

        if self.is_sequence and self.seq_files:
            clamped_idx = max(0, min(len(self.seq_files)-1, idx))
            path = self.seq_files[clamped_idx]
        else:
            path = os.path.join(self.proj_mag_dir, self.target_image)
            
        if os.path.exists(path):
            img_s = pygame.image.load(path).convert_alpha()
            iw, ih = img_s.get_size()
            self.aspect_ratio = float(iw)/float(ih) if ih > 0 else 1.0
        else:
            img_s = pygame.Surface((10,10))
            self.aspect_ratio = 1.0
            
        self.active_tex = self.ctx.texture(img_s.get_size(), 4, pygame.image.tostring(img_s, "RGBA", True))
        self.current_idx = idx
        
        return self.active_tex, self.aspect_ratio
        
    def release(self):
        if self.active_tex:
            self.active_tex.release()
