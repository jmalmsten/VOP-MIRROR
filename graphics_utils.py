"""
VOP Module:     graphics_utils.py
Version:        v0.0.2
Description:    Encapsulates ModernGL context, shaders, and texture caching.
                Extracting this keeps the massive strings of GLSL code out of the main engine.
"""
import os
import glob
# Pygame handles the creation of the invisible window and loading images from disk.
import pygame
# ModernGL is a Pythonic wrapper for OpenGL 3+ core profiles.
import moderngl
import numpy as np

# --- GLSL Shaders ---
# The Vertex Shader executes on the GPU once for every corner of our 2D shape (4 times total).
# It multiplies the shape's coordinates by our MVP matrix to warp/move the shape on screen.
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

# The Fragment Shader executes on the GPU once for every single pixel drawn to the screen.
# This is where we simulate the physical Projector Gel by altering the colors.
FRAGMENT_SHADER = """#version 300 es
precision highp float; 
in vec2 v_tex; 
out vec4 f_col; 
uniform sampler2D texture0; 
uniform vec3 filter_color; 
uniform bool mono_mode;
void main() { 
    // Sample the exact color of the image file at this specific pixel.
    vec4 t = texture(texture0, v_tex); 
    
    // Multiply the image color by our custom gel color (ProjGel).
    vec3 rgb = t.rgb * filter_color;
    
    // If monochrome is enabled, crush the colors using standard human-eye weighting.
    if(mono_mode) {
        float y = dot(rgb, vec3(0.2126, 0.7152, 0.0722));
        rgb = vec3(y);
    }
    
    // Output the final color to the projector.
    f_col = vec4(rgb, t.a); 
}
"""

def init_render_pipeline():
    """
    Initializes the ModernGL context and returns the pipeline objects.
    """
    # Create the context requesting OpenGL ES 3.0, which is the native 3D API for the Raspberry Pi 5.
    ctx = moderngl.create_context(require=300)
    
    # Compile the raw text GLSL shaders into an executable program on the GPU.
    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    
    # Define a standard 2x2 flat Square. 
    # Each row is a corner point. Format: [X, Y, Z, U, V]
    # XYZ is the 3D position in space. UV is the 2D mapping coordinate for the image texture.
    vbo_data = np.array([
        -1,-1,0, 0,0,  # Bottom Left
         1,-1,0, 1,0,  # Bottom Right
        -1, 1,0, 0,1,  # Top Left
         1, 1,0, 1,1   # Top Right
    ], dtype='f4')
    
    # A Vertex Buffer Object (VBO) uploads the raw array data from System RAM into GPU VRAM.
    vbo = ctx.buffer(vbo_data)
    
    # A Vertex Array Object (VAO) instructs the GPU on how to decode the VBO string of numbers.
    # '3f 2f' tells the GPU: "The first 3 floats are the position, the next 2 floats are the UV mapping."
    vao = ctx.vertex_array(prog, [(vbo, '3f 2f', 'in_position', 'in_texcoord')], mode=moderngl.TRIANGLE_STRIP)
    
    return ctx, prog, vao

class TextureManager:
    """
    Handles sequential and static texture loading from the disk into the GPU.
    This acts as a cache so we don't accidentally waste time reloading the same image twice.
    """
    def __init__(self, ctx, proj_mag_dir, job_data):
        self.ctx = ctx
        self.proj_mag_dir = proj_mag_dir
        
        # Check if the user selected 'SEQUENCE' from the UI dropdown instead of a single file.
        self.is_sequence = (job_data.get('image') == 'SEQUENCE')
        self.target_image = job_data.get('image', '')
        
        if self.is_sequence:
            # If sequence, scan the ProjMag folder and alphabetically sort all .tif files into a list.
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
        # Convert the incoming float playhead to a strict integer index.
        idx = int(idx_float)
        
        # Cache Check: If the requested frame is already loaded, immediately return it.
        if idx == self.current_idx and self.active_tex is not None:
            return self.active_tex, self.aspect_ratio
            
        # Free up the GPU memory used by the previous frame to prevent memory leaks.
        if self.active_tex:
            self.active_tex.release()

        # Determine the correct file path to load.
        if self.is_sequence and self.seq_files:
            # Clamp the index to ensure we don't try to load an array item that doesn't exist
            # (e.g., asking for frame 100 when there are only 50 files).
            clamped_idx = max(0, min(len(self.seq_files)-1, idx))
            path = self.seq_files[clamped_idx]
        else:
            path = os.path.join(self.proj_mag_dir, self.target_image)
            
        # Load the image using Pygame.
        if os.path.exists(path):
            img_s = pygame.image.load(path).convert_alpha()
            iw, ih = img_s.get_size()
            # Calculate the aspect ratio (width divided by height) for the math module to use later.
            self.aspect_ratio = float(iw)/float(ih) if ih > 0 else 1.0
        else:
            # Fallback: If a file goes missing, load a tiny 10x10 black square instead of crashing the engine.
            img_s = pygame.Surface((10,10))
            self.aspect_ratio = 1.0
            
        # Convert the Pygame image into a byte string and push it into the GPU VRAM.
        self.active_tex = self.ctx.texture(img_s.get_size(), 4, pygame.image.tostring(img_s, "RGBA", True))
        self.current_idx = idx
        
        return self.active_tex, self.aspect_ratio
        
    def release(self):
        # Cleans up the final texture when the engine shuts down.
        if self.active_tex:
            self.active_tex.release()