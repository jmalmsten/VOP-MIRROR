"""
VOP Module:     smear_3D_v0.0.12.py
Version:        v0.0.12
Description:    Phase II Engine - Fixed 16-bit Linear.
                Hard-manual camera lock and uncompressed TIFF output.
"""
import os, sys, json, time, argparse, subprocess, shutil
import numpy as np
import moderngl
import pygame
import cv2
from pyrr import Matrix44

# Atomic Setup
os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
os.environ["SDL_VIDEO_KMSDRM_FORCE_MODE"] = "1"
os.environ["SDL_DRM_DEVICE"] = "/dev/dri/card0"

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
    with open(job_path, 'r') as f:
        job = json.load(f)

    is_preview = job.get('type') == 'preview'
    PRO_MAG = os.path.expanduser("~/vop/ProjMag")
    CAM_MAG = os.path.expanduser("~/vop/CamMag")

    pygame.init()
    pygame.mouse.set_visible(False)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 1)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_ES)
    
    screen = pygame.display.set_mode((0,0), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
    WIDTH, HEIGHT = screen.get_size()
    ctx = moderngl.create_context(require=310)

    # Pre-clear screen to kill any ghost cursors or desktop fragments
    ctx.clear(0, 0, 0)
    pygame.display.flip()

    img_path = os.path.join(PRO_MAG, job['image'])
    img_src = pygame.image.load(img_path).convert_alpha()
    tex = ctx.texture(img_src.get_size(), 4, pygame.image.tostring(img_src, "RGBA", True))
    tex.filter = (moderngl.LINEAR, moderngl.LINEAR)

    vertices = np.array([-1,-1,0,0,0, 1,-1,0,1,0, -1,1,0,0,1, 1,1,0,1,1], dtype='f4')
    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    vbo = ctx.buffer(vertices)
    vao = ctx.vertex_array(prog, [(vbo, '3f 2f', 'in_position', 'in_texcoord')], mode=moderngl.TRIANGLE_STRIP)

    p1 = np.array([float(x) for x in job['p_start'].split(',') if x.strip()])
    p2 = np.array([float(x) for x in job['p_end'].split(',') if x.strip()])
    r1 = np.array([float(x) for x in job['r_start'].split(',') if x.strip()])
    r2 = np.array([float(x) for x in job['r_end'].split(',') if x.strip()])

    if is_preview:
        p_val = float(job.get('preview_p', 0.5))
        ctx.clear(0, 0, 0)
        proj = Matrix44.perspective_projection(float(job['fov']), WIDTH/HEIGHT, float(job['near']), float(job['far']))
        pos = p1 + (p_val * (p2 - p1))
        rot = r1 + (p_val * (r2 - r1))
        model = Matrix44.from_translation(pos) * Matrix44.from_x_rotation(np.radians(rot[0])) * \
                Matrix44.from_y_rotation(np.radians(rot[1])) * Matrix44.from_z_rotation(np.radians(rot[2]))
        prog['mvp'].write((proj * model).astype('f4'))
        tex.use(); vao.render()
        pygame.display.flip()
        time.sleep(3)
    else:
        # --- SMEAR MODE: MANUAL LOCK ---
        duration_ms = float(job['smear']) * 1000.0
        frame_num = str(job['frame']).zfill(4)
        output_file = os.path.join(CAM_MAG, f"latent_{frame_num}.tif")
        buffer_file = "/tmp/vop_capture.png"

        shutter_us = int(duration_ms * 1000)
        
        # We use strict manual controls: 
        # Gain 1.0, No Denoise, No Auto-WB, No Metadata.
        cam_proc = subprocess.Popen([
            "rpicam-still", "-o", buffer_file, "--encoding", "png",
            "--shutter", str(shutter_us), "--gain", "1.0",
            "--awbgains", "1.0,1.0", "--immediate", "--denoise", "off", "-n"
        ])

        anchor = time.time()
        while True:
            elapsed = (time.time() - anchor) * 1000
            if elapsed > (duration_ms + 500): break
            
            ctx.clear(0,0,0)
            p = elapsed / duration_ms
            
            if 0.0 <= p <= 1.0:
                proj = Matrix44.perspective_projection(float(job['fov']), WIDTH/HEIGHT, float(job['near']), float(job['far']))
                pos = p1 + (p * (p2 - p1)); rot = r1 + (p * (r2 - r1))
                model = Matrix44.from_translation(pos) * Matrix44.from_x_rotation(np.radians(rot[0])) * \
                        Matrix44.from_y_rotation(np.radians(rot[1])) * Matrix44.from_z_rotation(np.radians(rot[2]))
                prog['mvp'].write((proj * model).astype('f4'))
                tex.use(); vao.render()
            pygame.display.flip()
        
        cam_proc.wait()

        # --- UNCOMPRESSED 16-BIT SAVE ---
        if os.path.exists(buffer_file):
            new_exposure = cv2.imread(buffer_file, cv2.IMREAD_UNCHANGED)
            if os.path.exists(output_file):
                latent = cv2.imread(output_file, cv2.IMREAD_UNCHANGED)
                combined = cv2.add(latent, new_exposure)
                # Flag 1 = No Compression -> Ensures the 75MB size
                cv2.imwrite(output_file, combined, [cv2.IMWRITE_TIFF_COMPRESSION, 1])
            else:
                cv2.imwrite(output_file, new_exposure, [cv2.IMWRITE_TIFF_COMPRESSION, 1])
            os.remove(buffer_file)

    pygame.quit()