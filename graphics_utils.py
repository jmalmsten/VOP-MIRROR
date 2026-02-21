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
# The Vertex Shader executes once per vertex. It receives the 3D position and the texture coordinates.
# It multiplies the position by the MVP matrix to determine where the vertex lands on the 2D screen.
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

# The Fragment Shader executes once per pixel. It samples the bound texture and applies the Projector Gel.
FRAGMENT_SHADER = """#version 300 es
precision highp float; 
in vec2 v_tex; 
out vec4 f_col; 
uniform sampler2D texture0; 
uniform vec3 filter_color; 
uniform bool mono_mode;
void main() { 
    // Sample the pixel color from the image texture
    vec4 t = texture(texture0, v_tex); 
    // Multiply the sampled RGB values by the physical gel simulation color
    vec3 rgb = t.rgb * filter_color;
    
    if(mono_mode) {
        // Rec 709 luminance conversion weights
        float y = dot(rgb, vec3(0.2126, 0.7152, 0.0722));
        rgb = vec3(y);
    }
    // Output the final pixel color to the frame buffer
    f_col = vec4(rgb, t.a); 
}
"""

def init_render_pipeline():
    """
    Initializes the ModernGL context and returns the pipeline objects.
    """
    # Create the context requesting OpenGL ES 3.0, the native API for the Raspberry Pi 5.
    ctx = moderngl.create_context(require=300)
    
    # Compile the GLSL shaders into a GPU executable program.
    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    
    # Define a standard 2x2 Quad. 
    # Data structure: X, Y, Z, U, V.
    # U, V are the texture coordinates mapped to the vertices.
    vbo_data = np.array([-1,-1,0, 0,0,  1,-1,0, 1,0,  -1,1,0, 0,1,  1,1,0, 1,1], dtype='f4')
    
    # A Vertex Buffer Object (VBO) uploads the raw array data into VRAM.
    vbo = ctx.buffer(vbo_data)
    
    # A Vertex Array Object (VAO) tells the GPU how to read the VBO. 
    # '3f 2f' means: read 3 floats for position, then 2 floats for texture coordinates.
    # TRIANGLE_STRIP defines how the vertices connect to form the surface.
    vao = ctx.vertex_array(prog, [(vbo, '3f 2f', 'in_position', 'in_texcoord')], mode=moderngl.TRIANGLE_STRIP)
    
    return ctx, prog, vao

class TextureManager:
    """
    Handles sequential and static texture loading from the Mag directories.
    This class ensures we don't reload the same image from disk if it's already in VRAM.
    """
    def __init__(self, ctx, proj_mag_dir, job_data):
        self.ctx = ctx
        self.proj_mag_dir = proj_mag_dir
        self.is_sequence = (job_data.get('image') == 'SEQUENCE')
        self.target_image = job_data.get('image', '')
        
        # Pre-cache the file list if we are processing an image sequence.
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
        
        # Optimization: Do nothing if the requested texture is already active.
        if idx == self.current_idx and self.active_tex is not None:
            return self.active_tex, self.aspect_ratio
            
        # Release the old texture from VRAM to prevent memory leaks.
        if self.active_tex:
            self.active_tex.release()

        # Determine the file path based on sequence logic.
        if self.is_sequence and self.seq_files:
            # Clamp the index to prevent out-of-bounds array access if the timeline exceeds the source file count.
            clamped_idx = max(0, min(len(self.seq_files)-1, idx))
            path = self.seq_files[clamped_idx]
        else:
            path = os.path.join(self.proj_mag_dir, self.target_image)
            
        # Load the image using Pygame and calculate its aspect ratio.
        if os.path.exists(path):
            img_s = pygame.image.load(path).convert_alpha()
            iw, ih = img_s.get_size()
            self.aspect_ratio = float(iw)/float(ih) if ih > 0 else 1.0
        else:
            # Fallback to a tiny blank surface if the file is missing to prevent crashing.
            img_s = pygame.Surface((10,10))
            self.aspect_ratio = 1.0
            
        # Convert the Pygame surface to a byte string and upload it to the GPU as a texture.
        self.active_tex = self.ctx.texture(img_s.get_size(), 4, pygame.image.tostring(img_s, "RGBA", True))
        self.current_idx = idx
        
        return self.active_tex, self.aspect_ratio
        
    def release(self):
        # Clears the final texture from memory upon completion.
        if self.active_tex:
            self.active_tex.release()
