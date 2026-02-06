"""
VOP Module:     smear_3D_v0.0.17.py
Version:        v0.0.17
Description:    Phase III - High-Fidelity 16-bit Linear Engine.
                - Dynamic user path detection (No hardcoded usernames).
                - Uses rawpy to extract 12-bit sensor data to 16-bit arrays.
                - 0.5s Black / X s Smear / 0.5s Black shutter logic.
"""
import os, sys, json, time, argparse, subprocess
import numpy as np
import moderngl
import pygame
import cv2
import rawpy
from pyrr import Matrix44

# Environment Configuration
os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
os.environ["SDL_VIDEO_KMSDRM_FORCE_MODE"] = "1"
LATENCY_OFFSET_MS = 700.0 

# --- DYNAMIC PATH LOGIC ---
def get_vop_paths():
    """Finds the VOP directory relative to the current user home."""
    # Logic: Look for the real user if using sudo, otherwise use the current home.
    user_home = os.path.expanduser(f"~{os.environ.get('SUDO_USER', '')}")
    base_dir = os.path.join(user_home, "vop")
    return {
        "PRO_MAG": os.path.join(base_dir, "ProjMag"),
        "CAM_MAG": os.path.join(base_dir, "CamMag")
    }

# --- SHADERS ---
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

def develop_dng_to_16bit(path):
    """Bypasses ISP to get 16-bit Linear RGB from DNG."""
    with rawpy.imread(path) as raw:
        # gamma(1,1) = Linear; output_bps=16 = True 16-bit depth
        rgb = raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16)
    # Convert RGB to BGR for OpenCV
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

def run_vop_engine(job_path):
    with open(job_path, 'r') as f:
        job = json.load(f)

    is_preview = job.get('type') == 'preview'
    paths = get_vop_paths()

    # Hardware Init
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
        print(f"CRITICAL: DRM_LOCK_FAILED - {e}")
        pygame.quit(); sys.exit(1)

    # Texture Loading
    img_path = os.path.join(paths["PRO_MAG"], job['image'])
    img_src = pygame.image.load(img_path).convert_alpha()
    tex = ctx.texture(img_src.get_size(), 4, pygame.image.tostring(img_src, "RGBA", True))
    tex.filter = (moderngl.LINEAR, moderngl.LINEAR)

    # Rendering Prep
    vertices = np.array([-1,-1,0,0,0, 1,-1,0,1,0, -1,1,0,0,1, 1,1,0,1,1], dtype='f4')
    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    vbo = ctx.buffer(vertices)
    vao = ctx.vertex_array(prog, [(vbo, '3f 2f', 'in_position', 'in_texcoord')], mode=moderngl.TRIANGLE_STRIP)

    # Parse Transforms
    p1 = np.array([float(x) for x in job['p_start'].split(',') if x.strip()])
    p2 = np.array([float(x) for x in job['p_end'].split(',') if x.strip()])
    r1 = np.array([float(x) for x in job['r_start'].split(',') if x.strip()])
    r2 = np.array([float(x) for x in job['r_end'].split(',') if x.strip()])

    if is_preview:
        p_val = float(job.get('preview_p', 0.5))
        ctx.clear(0, 0, 0)
        proj = Matrix44.perspective_projection(float(job['fov']), WIDTH/HEIGHT, 0.1, 1000.0)
        pos = p1 + (p_val * (p2 - p1)); rot = r1 + (p_val * (r2 - r1))
        model = Matrix44.from_translation(pos) * Matrix44.from_x_rotation(np.radians(rot[0])) * \
                Matrix44.from_y_rotation(np.radians(rot[1])) * Matrix44.from_z_rotation(np.radians(rot[2]))
        prog['mvp'].write((proj * model).astype('f4'))
        tex.use(); vao.render()
        pygame.display.flip(); time.sleep(3)
    else:
        # --- SMEAR MODE (0.5s + X + 0.5s) ---
        x_ms = float(job['smear']) * 1000.0
        total_exposure_ms = x_ms + 1000.0
        output_file = os.path.join(paths["CAM_MAG"], f"latent_{str(job['frame']).zfill(4)}.tif")
        buffer_file = "/tmp/vop_capture.dng"
        
        shutter_us = int(total_exposure_ms * 1000)
        cam_proc = subprocess.Popen([
            "rpicam-still", "-o", buffer_file, "-r",
            "--shutter", str(shutter_us), "--gain", str(job['gain']),
            "--awbgains", f"{job['awb_r']},{job['awb_b']}", "--immediate", "--denoise", "off", "-n"
        ])

        # Apply HDMI Latency offset
        time.sleep(LATENCY_OFFSET_MS / 1000.0)
        
        anchor = time.time()
        while True:
            elapsed = (time.time() - anchor) * 1000
            if elapsed > total_exposure_ms: break
            
            ctx.clear(0,0,0)
            if 500.0 <= elapsed <= (500.0 + x_ms):
                p = (elapsed - 500.0) / x_ms
                proj = Matrix44.perspective_projection(float(job['fov']), WIDTH/HEIGHT, 0.1, 1000.0)
                pos = p1 + (p * (p2 - p1)); rot = r1 + (p * (r2 - r1))
                model = Matrix44.from_translation(pos) * \
                        Matrix44.from_x_rotation(np.radians(rot[0])) * \
                        Matrix44.from_y_rotation(np.radians(rot[1])) * \
                        Matrix44.from_z_rotation(np.radians(rot[2]))
                prog['mvp'].write((proj * model).astype('f4'))
                tex.use(); vao.render()
            
            pygame.display.flip()
        
        # Cleanup and finalize file
        ctx.clear(0,0,0); pygame.display.flip()
        cam_proc.wait()

        # --- 16-BIT RAW DEVELOP & STACK ---
        if os.path.exists(buffer_file):
            new_img_16 = develop_dng_to_16bit(buffer_file)
            
            if os.path.exists(output_file):
                latent = cv2.imread(output_file, cv2.IMREAD_UNCHANGED)
                combined = cv2.add(latent, new_img_16)
                cv2.imwrite(output_file, combined, [cv2.IMWRITE_TIFF_COMPRESSION, 1])
            else:
                cv2.imwrite(output_file, new_img_16, [cv2.IMWRITE_TIFF_COMPRESSION, 1])
            
            os.remove(buffer_file)
            print("VOP_STATUS: COMPLETE")

    pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    args = parser.parse_args()
    run_vop_engine(args.job)