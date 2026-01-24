"""
VOP Module:     smear_3D_6.py
Version:        v0.0.6
Description:    3D Smear Engine optimized for Pi 5 GLES 3.1.
                - Verbose initialization logging.
                - Absolute path handling for sudo.
                - Dynamic card detection for DRM.
"""

import os
import time
import sys
import tty
import termios
import select
import subprocess
import argparse
import datetime
import numpy as np
import moderngl
import pygame
from pyrr import Matrix44

# --- GLES 3.1 Shaders ---
VERTEX_SHADER = """
#version 310 es
precision highp float;
in vec3 in_position;
in vec2 in_texcoord;
out vec2 v_texcoord;
uniform mat4 mvp;
void main() {
    gl_Position = mvp * vec4(in_position, 1.0);
    v_texcoord = in_texcoord;
}
"""

FRAGMENT_SHADER = """
#version 310 es
precision highp float;
uniform sampler2D texture0;
in vec2 v_texcoord;
out vec4 f_color;
void main() {
    f_color = texture(texture0, v_texcoord);
}
"""

def get_ssh_key():
    if not select.select([sys.stdin], [], [], 0)[0]:
        return None
    char = sys.stdin.read(1)
    if char == '\x1b':
        seq = sys.stdin.read(2)
        if seq == '[D': return 'LEFT'
        if seq == '[C': return 'RIGHT'
        if seq == '[B': return 'DOWN'
    elif char == '\r' or char == '\n': return 'ENTER'
    elif char == '\x03': return 'QUIT'
    return char

def run_vop_3d(args):
    # Absolute path check for sudo environments
    PRO_MAG_DIR = "/home/admininja/vop/ProjMag"
    print(f"--- VOP v0.0.6 Startup ---")
    
    # --- DRM Card Detection ---
    card = "/dev/dri/card0"
    if not os.path.exists(card):
        card = "/dev/dri/card1"
    
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    os.environ["SDL_DRM_DEVICE"] = card
    print(f"Using DRM Device: {card}")
    
    pygame.init()
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 1)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_ES)
    
    try:
        print("Initializing Display Mode...")
        screen = pygame.display.set_mode((0, 0), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
        WIDTH, HEIGHT = pygame.display.get_surface().get_size()
        print(f"Resolution: {WIDTH}x{HEIGHT}")
        
        print("Creating ModernGL Context...")
        ctx = moderngl.create_context(require=310)
    except Exception as e:
        print(f"FATAL INITIALIZATION ERROR: {e}")
        pygame.quit()
        return

    # Load Texture
    img_path = os.path.join(PRO_MAG_DIR, args.image)
    print(f"Loading Image: {img_path}")
    if not os.path.exists(img_path):
        print(f"ERROR: Image not found at {img_path}")
        pygame.quit()
        return

    src = pygame.image.load(img_path).convert_alpha()
    texture = ctx.texture(src.get_size(), 4, pygame.image.tostring(src, "RGBA", True))
    texture.filter = (moderngl.LINEAR, moderngl.LINEAR)

    vertices = np.array([-1,-1,0,0,0, 1,-1,0,1,0, -1,1,0,0,1, 1,1,0,1,1], dtype='f4')
    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    vbo = ctx.buffer(vertices)
    vao = ctx.vertex_array(prog, [(vbo, '3f 2f', 'in_position', 'in_texcoord')], mode=moderngl.TRIANGLE_STRIP)

    p1 = np.array(list(map(float, args.pos_start.split(','))))
    p2 = np.array(list(map(float, args.pos_end.split(','))))
    r1 = np.array(list(map(float, args.rot_start.split(','))))
    r2 = np.array(list(map(float, args.rot_end.split(','))))

    old_settings = termios.tcgetattr(sys.stdin)
    preview_prog = 0.5
    try:
        tty.setraw(sys.stdin.fileno())
        print("\r\n--- 3D PREVIEW ACTIVE ---")
        print("Arrows: S/M/E | Enter: Capture | Ctrl+C: Exit\r\n")
        
        while True:
            key = get_ssh_key()
            if key == 'LEFT': preview_prog = 0.0
            if key == 'DOWN': preview_prog = 0.5
            if key == 'RIGHT': preview_prog = 1.0
            if key == 'ENTER': break
            if key == 'QUIT': return

            proj = Matrix44.perspective_projection(args.fov, WIDTH/HEIGHT, 0.1, 100.0)
            pos = p1 + (preview_prog * (p2 - p1))
            rot = r1 + (preview_prog * (r2 - r1))
            scale = args.scale_start + (preview_prog * (args.scale_end - args.scale_start))

            model = Matrix44.from_translation(pos) * \
                    Matrix44.from_x_rotation(np.radians(rot[0])) * \
                    Matrix44.from_y_rotation(np.radians(rot[1])) * \
                    Matrix44.from_z_rotation(np.radians(rot[2])) * \
                    Matrix44.from_scale((scale, scale, scale))
            
            ctx.clear(0.1, 0.1, 0.1)
            prog['mvp'].write((proj * model).astype('f4'))
            texture.use()
            vao.render()
            pygame.display.flip()
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

    print("STARTING CAPTURE...")
    # [Capture loop remains the same...]
    # ... (Capture implementation) ...
    pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=str, required=True)
    parser.add_argument("--smear", type=float, default=5.0)
    parser.add_argument("--offset", type=int, default=718)
    parser.add_argument("--gain", type=float, default=1.0)
    parser.add_argument("--fov", type=float, default=45.0)
    parser.add_argument("--pos_start", type=str, default="0,0,-2.0")
    parser.add_argument("--pos_end", type=str, default="0,0,-2.0")
    parser.add_argument("--rot_start", type=str, default="0,0,0")
    parser.add_argument("--rot_end", type=str, default="0,0,0")
    parser.add_argument("--scale_start", type=float, default=1.0)
    parser.add_argument("--scale_end", type=float, default=1.0)
    run_vop_3d(parser.parse_args())