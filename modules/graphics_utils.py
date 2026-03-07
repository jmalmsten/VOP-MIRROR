"""
VOP Module:     graphics_utils.py
Version:        v0.0.7
Description:    Encapsulates ModernGL context, shaders, and texture caching.
                Corrected UV mapping to render right-side up.
"""
import os
import pygame
import moderngl
import numpy as np

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
void main() { 
    vec4 base = texture(texture0, v_tex);
    f_col = vec4(base.rgb * filter_color, base.a);
}
"""

def init_render_pipeline():
    ctx = moderngl.create_context(require=300)
    
    ctx.pack_alignment = 1
    ctx.unpack_alignment = 1
    ctx.enable(moderngl.BLEND) 
    
    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    
    # GROUND TRUTH FIX: Corrected UVs to match Pygame's vertical flip
    vertices = np.array([
        # X,   Y,   Z,     U,   V
        -1.0,  1.0, 0.0,   0.0, 1.0,  # Top-Left
        -1.0, -1.0, 0.0,   0.0, 0.0,  # Bottom-Left
         1.0,  1.0, 0.0,   1.0, 1.0,  # Top-Right
         1.0, -1.0, 0.0,   1.0, 0.0   # Bottom-Right
    ], dtype='f4')
    
    vbo = ctx.buffer(vertices.tobytes())
    vao = ctx.vertex_array(prog, [(vbo, '3f 2f', 'in_position', 'in_texcoord')])
    
    return ctx, prog, vao

class TextureManager:
    def __init__(self, ctx, proj_mag_dir, job_data):
        self.ctx = ctx
        self.proj_mag_dir = proj_mag_dir
        self.target_image = job_data.get('image', '')
        self.active_tex = None
        self.aspect_ratio = 1.0

    def load(self, playhead=0.0):
        if self.active_tex: 
            self.active_tex.release()

        path = os.path.join(self.proj_mag_dir, self.target_image)
        
        if os.path.exists(path):
            img_s = pygame.image.load(path).convert_alpha()
            iw, ih = img_s.get_size()
            self.aspect_ratio = float(iw) / float(ih) if ih > 0 else 1.0
        else:
            img_s = pygame.Surface((100, 100), pygame.SRCALPHA)
            img_s.fill((255, 0, 255, 255))
            self.aspect_ratio = 1.0
            
        self.active_tex = self.ctx.texture(img_s.get_size(), 4, pygame.image.tostring(img_s, "RGBA", True))
        return self.active_tex, self.aspect_ratio

    def release(self):
        if self.active_tex: 
            self.active_tex.release()