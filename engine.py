"""
VOP Module:     engine.py
Version:        v0.0.36-stable
Description:    Phase V Engine. Segment-aware with hardened init.
"""
import os, sys, json, time, argparse, subprocess, threading
import numpy as np
import moderngl, pygame, cv2, rawpy
from pyrr import Matrix44
import color_utils as color 

os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
LATENCY_OFFSET_MS = 900.0 

VERTEX_SHADER = """
#version 300 es
precision highp float;
in vec3 in_position; in vec2 in_texcoord;
out vec2 v_texcoord;
uniform mat4 mvp;
void main() { gl_Position = mvp * vec4(in_position, 1.0); v_texcoord = in_texcoord; }
"""
FRAGMENT_SHADER = """
#version 300 es
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

def save_frame_async(buffer_file, output_file, tiff_flag):
    try:
        with rawpy.imread(buffer_file) as raw:
            img = cv2.cvtColor(raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16), cv2.COLOR_RGB2BGR)
        if os.path.exists(output_file):
            img = cv2.add(cv2.imread(output_file, cv2.IMREAD_UNCHANGED), img)
        cv2.imwrite(output_file, img, [cv2.IMWRITE_TIFF_COMPRESSION, tiff_flag])
        os.remove(buffer_file)
    except Exception as e: print(f"SAVE ERROR: {e}")

def run_vop_engine(job_path):
    with open(job_path, 'r') as f: job = json.load(f)
    user_home = os.path.expanduser(f"~{os.environ.get('SUDO_USER', 'admininja')}")
    cam_mag_dir, proj_mag_dir = os.path.join(user_home, "vop/CamMag"), os.path.join(user_home, "vop/ProjMag")
    
    pygame.init()
    screen = pygame.display.set_mode((0,0), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
    pygame.mouse.set_visible(False)
    WIDTH, HEIGHT = screen.get_size()
    ctx = moderngl.create_context(require=300)
    
    img_surface = pygame.image.load(os.path.join(proj_mag_dir, job['image'])).convert_alpha()
    tex = ctx.texture(img_surface.get_size(), 4, pygame.image.tostring(img_surface, "RGBA", True))
    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    vbo = ctx.buffer(np.array([-1,-1,0,0,0, 1,-1,0,1,0, -1,1,0,0,1, 1,1,0,1,1], dtype='f4'))
    vao = ctx.vertex_array(prog, [(vbo, '3f 2f', 'in_position', 'in_texcoord')], mode=moderngl.TRIANGLE_STRIP)

    p1, p2 = np.array([float(x) for x in job['p_start'].split(',')]), np.array([float(x) for x in job['p_end'].split(',')])
    r1, r2 = np.array([float(x) for x in job['r_start'].split(',')]), np.array([float(x) for x in job['r_end'].split(',')])

    if job.get('type') == 'preview':
        ctx.clear(0,0,0)
        proj = Matrix44.perspective_projection(float(job['fov']), WIDTH/HEIGHT, 0.1, 1000.0)
        model = Matrix44.from_translation(p1) * Matrix44.from_x_rotation(np.radians(r1[0])) * \
                Matrix44.from_y_rotation(np.radians(r1[1])) * Matrix44.from_z_rotation(np.radians(r1[2]))
        prog['filter_color'].write(np.array(color.get_perceptual_color(float(job['preview_p']), job['c_start'], job['c_end']), dtype='f4'))
        prog['mvp'].write((proj * model).astype('f4'))
        tex.use(); vao.render(); pygame.display.flip(); time.sleep(3)
    else:
        x_ms = float(job['smear']) * 1000.0; total_ms = x_ms + 1000.0
        output_file, buffer_file = os.path.join(cam_mag_dir, f"latent_{str(job['frame']).zfill(4)}.tif"), f"/tmp/vop_buf_{job['frame']}.dng"
        cam_proc = subprocess.Popen(["rpicam-still", "-o", buffer_file, "-r", "--shutter", str(int(total_ms * 1000)), "--gain", str(job['gain']), "--awbgains", f"{job['awb_r']},{job['awb_b']}", "--immediate", "--denoise", "off", "-n"])
        time.sleep(LATENCY_OFFSET_MS / 1000.0)
        anchor = time.time()
        while (time.time() - anchor) * 1000 < total_ms:
            elapsed = (time.time() - anchor) * 1000
            ctx.clear(0,0,0)
            if 500.0 <= elapsed <= (500.0 + x_ms):
                t = (elapsed - 500.0) / x_ms
                proj = Matrix44.perspective_projection(float(job['fov']), WIDTH/HEIGHT, 0.1, 1000.0)
                pos, rot = p1 + (t * (p2 - p1)), r1 + (t * (r2 - r1))
                model = Matrix44.from_translation(pos) * Matrix44.from_x_rotation(np.radians(rot[0])) * \
                        Matrix44.from_y_rotation(np.radians(rot[1])) * Matrix44.from_z_rotation(np.radians(rot[2]))
                prog['filter_color'].write(np.array(color.get_perceptual_color(t, job['c_start'], job['c_end']), dtype='f4'))
                prog['mvp'].write((proj * model).astype('f4'))
                tex.use(); vao.render()
            pygame.display.flip()
        ctx.finish(); cam_proc.wait()
        threading.Thread(target=save_frame_async, args=(buffer_file, output_file, 1 if job.get('tiff_compression') == 'zip' else 8)).start()
    pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--job", required=True)
    run_vop_engine(parser.parse_args().job)