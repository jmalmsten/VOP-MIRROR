"""
VOP Module:     smear_3D_v0.0.18.py
Version:        v0.0.18
Description:    Merged Phase III - 3D Transforms + Perceptual Color Smear.
"""
import os, sys, json, time, argparse, subprocess
import numpy as np
import moderngl, pygame, cv2, rawpy
from pyrr import Matrix44
import vop_color_v0.0.1 as vop_color

os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
LATENCY_OFFSET_MS = 700.0 

VERTEX_SHADER = """
#version 310 es
precision highp float;
in vec3 in_position; in vec2 in_texcoord;
out vec2 v_texcoord;
uniform mat4 mvp;
void main() { gl_Position = mvp * vec4(in_position, 1.0); v_texcoord = in_texcoord; }
"""
FRAGMENT_SHADER = """
#version 310 es
precision highp float;
uniform sampler2D texture0;
uniform vec3 filter_color;
in vec2 v_texcoord;
out vec4 f_color;
void main() {
    vec4 tex = texture(texture0, v_texcoord);
    f_color = vec4(tex.rgb * filter_color, tex.a);
}
"""

def get_vop_paths():
    user_home = os.path.expanduser(f"~{os.environ.get('SUDO_USER', '')}")
    base_dir = os.path.join(user_home, "vop")
    return {"PRO_MAG": os.path.join(base_dir, "ProjMag"), "CAM_MAG": os.path.join(base_dir, "CamMag")}

def run_vop_engine(job_path):
    with open(job_path, 'r') as f: job = json.load(f)
    is_preview = job.get('type') == 'preview'
    paths = get_vop_paths()

    pygame.init()
    screen = pygame.display.set_mode((0,0), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
    WIDTH, HEIGHT = screen.get_size()
    ctx = moderngl.create_context(require=310)

    # Texture
    img_path = os.path.join(paths["PRO_MAG"], job['image'])
    img_src = pygame.image.load(img_path).convert_alpha()
    tex = ctx.texture(img_src.get_size(), 4, pygame.image.tostring(img_src, "RGBA", True))
    
    # Prep Shaders
    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    vbo = ctx.buffer(np.array([-1,-1,0,0,0, 1,-1,0,1,0, -1,1,0,0,1, 1,1,0,1,1], dtype='f4'))
    vao = ctx.vertex_array(prog, [(vbo, '3f 2f', 'in_position', 'in_texcoord')], mode=moderngl.TRIANGLE_STRIP)

    # Parse 3D & Color
    p1 = np.array([float(x) for x in job['p_start'].split(',')])
    p2 = np.array([float(x) for x in job['p_end'].split(',')])
    r1 = np.array([float(x) for x in job['r_start'].split(',')])
    r2 = np.array([float(x) for x in job['r_end'].split(',')])
    c1, c2 = job['c_start'], job['c_end']

    # --- RENDER LOOP ---
    x_ms = float(job['smear']) * 1000.0
    total_ms = x_ms + 1000.0 if not is_preview else 0
    p_val = float(job.get('preview_p', 0.5))

    if not is_preview:
        shutter_us = int(total_ms * 1000)
        cam_proc = subprocess.Popen(["rpicam-still", "-o", "/tmp/vop.dng", "-r", "--shutter", str(shutter_us), "-n"])
        time.sleep(LATENCY_OFFSET_MS / 1000.0)

    anchor = time.time()
    while True:
        elapsed = (time.time() - anchor) * 1000
        if not is_preview and elapsed > total_ms: break
        
        ctx.clear(0,0,0)
        t = p_val if is_preview else (elapsed - 500.0) / x_ms
        if 0.0 <= t <= 1.0:
            proj = Matrix44.perspective_projection(float(job['fov']), WIDTH/HEIGHT, 0.1, 1000.0)
            pos = p1 + (t * (p2 - p1)); rot = r1 + (t * (r2 - r1))
            model = Matrix44.from_translation(pos) * Matrix44.from_x_rotation(np.radians(rot[0])) * \
                    Matrix44.from_y_rotation(np.radians(rot[1])) * Matrix44.from_z_rotation(np.radians(rot[2]))
            
            # PHASE III: Calculate Color Filter
            current_col = vop_color.get_perceptual_color(t, c_start, c_end)
            prog['filter_color'].write(np.array(current_col, dtype='f4'))
            prog['mvp'].write((proj * model).astype('f4'))
            tex.use(); vao.render()
        
        pygame.display.flip()
        if is_preview: time.sleep(3); break

    pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--job", required=True)
    run_vop_engine(parser.parse_args().job)