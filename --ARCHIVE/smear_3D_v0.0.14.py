"""
VOP Module:     smear_3D_v0.0.14.py
Version:        v0.0.14
Description:    Phase II/III - True 16-bit Linear Restoration.
                - Implements 0.5s Black / X s Smear / 0.5s Black logic.
                - Restores 16-bit uncompressed TIFF workflow (~74MB).
"""
import os, sys, json, time, argparse, subprocess, shutil
import numpy as np
import moderngl
import pygame
import cv2
from pyrr import Matrix44

# Environment Configuration
os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
os.environ["SDL_VIDEO_KMSDRM_FORCE_MODE"] = "1"

# Timing Constant (The HDMI Latency Offset)
LATENCY_OFFSET_MS = 700.0 

# Shaders
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

    # Assets
    img_src = pygame.image.load(os.path.join(PRO_MAG, job['image'])).convert_alpha()
    tex = ctx.texture(img_src.get_size(), 4, pygame.image.tostring(img_src, "RGBA", True))
    tex.filter = (moderngl.LINEAR, moderngl.LINEAR)

    # Geometry
    vertices = np.array([-1,-1,0,0,0, 1,-1,0,1,0, -1,1,0,0,1, 1,1,0,1,1], dtype='f4')
    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    vbo = ctx.buffer(vertices)
    vao = ctx.vertex_array(prog, [(vbo, '3f 2f', 'in_position', 'in_texcoord')], mode=moderngl.TRIANGLE_STRIP)

    # Transform Data
    p1 = np.array([float(x) for x in job['p_start'].split(',') if x.strip()])
    p2 = np.array([float(x) for x in job['p_end'].split(',') if x.strip()])
    r1 = np.array([float(x) for x in job['r_start'].split(',') if x.strip()])
    r2 = np.array([float(x) for x in job['r_end'].split(',') if x.strip()])

    if is_preview:
        p_val = float(job.get('preview_p', 0.5))
        ctx.clear(0, 0, 0)
        proj = Matrix44.perspective_projection(float(job['fov']), WIDTH/HEIGHT, float(job['near']), float(job['far']))
        pos = p1 + (p_val * (p2 - p1)); rot = r1 + (p_val * (r2 - r1))
        model = Matrix44.from_translation(pos) * \
                Matrix44.from_x_rotation(np.radians(rot[0])) * \
                Matrix44.from_y_rotation(np.radians(rot[1])) * \
                Matrix44.from_z_rotation(np.radians(rot[2]))
        prog['mvp'].write((proj * model).astype('f4'))
        tex.use(); vao.render()
        pygame.display.flip(); time.sleep(3)
    else:
        # --- SMEAR MODE (0.5s + X + 0.5s) ---
        x_ms = float(job['smear']) * 1000.0
        total_exposure_ms = x_ms + 1000.0
        
        frame_num = str(job['frame']).zfill(4)
        output_file = os.path.join(CAM_MAG, f"latent_{frame_num}.tif")
        buffer_file = "/tmp/vop_capture.tif" # Buffer is now TIFF
        
        shutter_us = int(total_exposure_ms * 1000)
        
        # Triggering the True 16-bit Raw-Integrated Capture
        # Added --raw to force the 12-bit sensor data into the TIFF container
        cam_proc = subprocess.Popen([
            "rpicam-still", "-o", buffer_file, "--encoding", "png",
            "--shutter", str(shutter_us), "--gain", str(job['gain']),
            "--awbgains", f"{job['awb_r']},{job['awb_b']}", "--immediate", 
            "--denoise", "off", "-n"
        ])

        # Wait for HDMI Latency
        time.sleep(LATENCY_OFFSET_MS / 1000.0)

        anchor = time.time()
        while True:
            elapsed = (time.time() - anchor) * 1000
            if elapsed > total_exposure_ms: break
            
            ctx.clear(0,0,0) # The "Shutter" Black

            # Animation Logic (Delayed by 500ms)
            if 500.0 <= elapsed <= (500.0 + x_ms):
                p = (elapsed - 500.0) / x_ms
                proj = Matrix44.perspective_projection(float(job['fov']), WIDTH/HEIGHT, float(job['near']), float(job['far']))
                pos = p1 + (p * (p2 - p1)); rot = r1 + (p * (r2 - r1))
                model = Matrix44.from_translation(pos) * \
                        Matrix44.from_x_rotation(np.radians(rot[0])) * \
                        Matrix44.from_y_rotation(np.radians(rot[1])) * \
                        Matrix44.from_z_rotation(np.radians(rot[2]))
                prog['mvp'].write((proj * model).astype('f4'))
                tex.use(); vao.render()
            
            pygame.display.flip()
        
        ctx.clear(0,0,0); pygame.display.flip()
        cam_proc.wait()

        # --- THE 16-BIT COMPOSITE ---
        if os.path.exists(buffer_file):
            # Load with UNCHANGED to maintain bit depth
            new_img = cv2.imread(buffer_file, cv2.IMREAD_UNCHANGED)
            
            if os.path.exists(output_file):
                latent = cv2.imread(output_file, cv2.IMREAD_UNCHANGED)
                # cv2.add handles the 16-bit math natively
                combined = cv2.add(latent, new_img)
                # Save Uncompressed TIFF
                cv2.imwrite(output_file, combined, [cv2.IMWRITE_TIFF_COMPRESSION, 1])
            else:
                cv2.imwrite(output_file, new_img, [cv2.IMWRITE_TIFF_COMPRESSION, 1])
            
            os.remove(buffer_file)
            print("VOP_STATUS: COMPLETE")

    pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    args = parser.parse_args()
    run_vop_engine(args.job)