"""
VOP Module:         smear_3D_v0.0.11.py
Version:            v0.0.11
VOP Version:        v0.3.1
Description:        3D Smear Engine updated to read JSON job files from the VOP API.
"""
import os
import sys
import json
import time
import argparse
import datetime
import subprocess
import numpy as np
import moderngl
import pygame
from pyrr import Matrix44

# --- Atomic environment setup ---
os.environ["SDL_VIDEODRIVER"]             = "kmsdrm"
os.environ["SDL_VIDEO_KMSDRM_FORCE_MODE"] = "1"
os.environ["SDL_DRM_DEVICE"]              = "/dev/dri/card0"

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

def run_vop_engine(job_path):
    # 1. Load the Job
    try:
        with open(job_path, 'r') as f:
            job = json.load(f)
    except Exception as e:
        print(f"CRITICAL: Failed to load job file: {e}")
        sys.exit(1)

    # 2. Setup Directories
    PRO_MAG = os.path.expanduser("~/vop/ProjMag")
    if not os.path.exists(PRO_MAG):
        os.makedirs(PRO_MAG)
    CAM_MAG = os.path.expanduser("~/vop/CamMag")
    if not os.path.exists(CAM_MAG):
        os.makedirs(CAM_MAG)

    # 3. GPU Init
    pygame.init()
    pygame.mouse.set_visible(False)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 1)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_ES)

    try: 
        screen = pygame.display.set_mode((0,0), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
        WIDTH, HEIGHT = screen.get_size()
        ctx = moderngl.create_context(require=310)
    except Exception as e:
        print(f"FATAL GPU ERROR: {e}")
        pygame.quit()
        return

    # 4. Load Image Texture
    img_path = os.path.join(PRO_MAG, job['image'])
    if not os.path.exists(img_path):
        print(f"ERROR: Image not found at {img_path}")
        pygame.quit()
        return

    img_src = pygame.image.load(img_path).convert_alpha()
    tex = ctx.texture(img_src.get_size(), 4, pygame.image.tostring(img_src, "RGBA", True))
    tex.filter = (moderngl.LINEAR, moderngl.LINEAR)

    # 5. Geometry Setup (3D Plane)
    # Positions (x, y, z) and TexCoords (u, v)
    vertices = np.array([
        -1.0, -1.0,  0.0,  0.0, 0.0,
         1.0, -1.0,  0.0,  1.0, 0.0,
        -1.0,  1.0,  0.0,  0.0, 1.0,
         1.0,  1.0,  0.0,  1.0, 1.0,
    ], dtype='f4')

    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    vbo = ctx.buffer(vertices)
    vao = ctx.vertex_array(prog, [(vbo, '3f 2f', 'in_position', 'in_texcoord')], mode=moderngl.TRIANGLE_STRIP)

    # Parse Transforms
    p1 = np.array([float(x) for x in job['pos_start'].split(',')])
    p2 = np.array([float(x) for x in job['pos_end'].split(',')])
    r1 = np.array([float(x) for x in job['rot_start'].split(',')])
    r2 = np.array([float(x) for x in job['rot_end'].split(',')])
    s1 = float(job.get('scale_start', 1.0))
    s2 = float(job.get('scale_end', 1.0))   

    # 6. Capture Timing & Execution
    timestamp = datetime.datetime.now().strftime("%H%M%S")
    output_file = os.path.join(CAM_MAG, f"VOP_PHASE1_{timestamp}.jpg")

    duration_ms = float(job['smear_duration']) * 1000.0
    shutter_us = int((duration_ms +1000) * 1000) # Buffer for capture lead-in (relying on the monitors black screen phase for actual timing)

    # Trigger Camera
    cam_proc = subprocess.Popen([
        "rpicam-still", "-o", output_file,
        "--shutter", str(shutter_us),
        "--gain",    str(job.get('gain', 1.0)),
        "--immediate",
        "--awbgains", "3.18,1.45",
        "-n"
    ])

    print(f"STARTING {job['smear_duration']}s SMEAR...")
    anchor = time.time()

    while True:
        elapsed = (time.time() - anchor) * 1000
        if elapsed > (duration_ms + 2500):
            break # Loop safety buffer
        ctx.clear(0, 0, 0)

        # Mapping 0.0-1.0 over duration (offset by 1.5s for shutter lead)
        p =  (elapsed - 1500.0) / duration_ms

        if 0.0 <= p <= 1.0:
            # Perspective Projection 
            proj = Matrix44.perspective_projection(job['fov'], WIDTH/HEIGHT, 0.1, 1000.0) # 0.1 and 1000.0 beng near and far clipping

            # Interpolate state
            pos_v   = p1 + (p * (p2 - p1))
            rot_v   = r1 + (p * (r2 - r1))
            scale_v = s1 + (p * (s2 - s1))

            # Build Model Matrix
            model = Matrix44.from_translation(pos_v) * \
                    Matrix44.from_x_rotation(np.radians(rot_v[0])) * \
                    Matrix44.from_y_rotation(np.radians(rot_v[1])) * \
                    Matrix44.from_z_rotation(np.radians(rot_v[2])) * \
                    Matrix44.from_scale((scale_v, scale_v, scale_v))

            prog['mvp'].write((proj * model).astype('f4'))
            tex.use()
            vao.render()

        pygame.display.flip()
    
    print("SMEAR FINISHED. WAITING FOR CAMERA...")
    cam_proc.wait()
    print(f"COMPLETE: {output_file}")
    pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    args = parser.parse_args()
    run_vop_engine(args.job)