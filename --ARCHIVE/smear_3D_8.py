"""
VOP Module:     smear_3D_8.py
Version:        v0.0.8
Description:    3D Smear Engine optimized for Pi 5 GLES 3.1.
                - Atomic initialization (Flags set before imports).
                - Forced KMSDRM Master Lock.
"""
import os
import sys

# MUST happen before pygame/moderngl imports
os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
os.environ["SDL_VIDEO_KMSDRM_FORCE_MODE"] = "1"
os.environ["SDL_DRM_DEVICE"] = "/dev/dri/card0"

print("--- ATOMIC STARTUP CHECK ---")

try:
    import time
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
    print("--- LIBRARIES LOADED ---")
except Exception as e:
    print(f"CRITICAL IMPORT ERROR: {e}")
    sys.exit(1)

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
    PRO_MAG_DIR = "/home/admininja/vop/ProjMag"
    CAM_MAG_DIR = "/home/admininja/vop/CamMag"
    
    if not os.path.exists(CAM_MAG_DIR):
        os.makedirs(CAM_MAG_DIR)

    print("Initializing Pygame (KMSDRM)...")
    pygame.init()
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 1)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_ES)
    
    try:
        print("Opening Display...")
        screen = pygame.display.set_mode((0, 0), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
        WIDTH, HEIGHT = pygame.display.get_surface().get_size()
        print(f"Display OK: {WIDTH}x{HEIGHT}")
        
        ctx = moderngl.create_context(require=310)
        print("GPU Context OK.")
    except Exception as e:
        print(f"FATAL GPU ERROR: {e}")
        pygame.quit()
        return

    # Load Texture
    img_path = os.path.join(PRO_MAG_DIR, args.image)
    if not os.path.exists(img_path):
        print(f"ERROR: {img_path} not found.")
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
    # [Capture logic]
    timestamp = datetime.datetime.now().strftime("%H%M%S")
    output_file = os.path.join(CAM_MAG_DIR, f"VOP_3D_{timestamp}.jpg")
    anchor = time.time()
    captured = False
    total_ms = args.smear * 1000.0
    
    while True:
        elapsed = (time.time() - anchor) * 1000
        if elapsed > (total_ms + 2000): break
        ctx.clear(0, 0, 0)
        
        start_trigger = 1000.0 + 500.0
        if start_trigger <= elapsed < (start_trigger + total_ms):
            p = (elapsed - start_trigger) / total_ms
            proj = Matrix44.perspective_projection(args.fov, WIDTH/HEIGHT, 0.1, 100.0)
            pos = p1 + (p * (p2 - p1))
            rot = r1 + (p * (r2 - r1))
            scale = args.scale_start + (p * (args.scale_end - args.scale_start))
            model = Matrix44.from_translation(pos) * \
                    Matrix44.from_x_rotation(np.radians(rot[0])) * \
                    Matrix44.from_y_rotation(np.radians(rot[1])) * \
                    Matrix44.from_z_rotation(np.radians(rot[2])) * \
                    Matrix44.from_scale((scale, scale, scale))
            prog['mvp'].write((proj * model).astype('f4'))
            texture.use()
            vao.render()
        
        pygame.display.flip()

        if not captured and elapsed >= (1000.0 - args.offset):
            shutter = int((total_ms + 1000) * 1000)
            subprocess.Popen(["rpicam-still", "-o", output_file, "--shutter", str(shutter), "--gain", str(args.gain), "--immediate", "-n"])
            captured = True

    print(f"DONE. Result: {output_file}")
    pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--smear", type=float, default=5.0)
    parser.add_argument("--offset", type=int, default=718)
    parser.add_argument("--gain", type=float, default=1.0)
    parser.add_argument("--fov", type=float, default=45.0)
    parser.add_argument("--pos_start", default="0,0,-2.0")
    parser.add_argument("--pos_end", default="0,0,-2.0")
    parser.add_argument("--rot_start", default="0,0,0")
    parser.add_argument("--rot_end", default="0,0,0")
    parser.add_argument("--scale_start", type=float, default=1.0)
    parser.add_argument("--scale_end", type=float, default=1.0)
    run_vop_3d(parser.parse_args())