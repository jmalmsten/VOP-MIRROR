"""
VOP Module:     engine.py
Version:        v0.0.24-stable
Description:    Phase III Engine. Restored AWB Gains and Shutter Handshake.
"""
import os, sys, json, time, argparse, subprocess
import numpy as np
import moderngl, pygame, cv2, rawpy
from pyrr import Matrix44
import color_utils as color 

os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
LATENCY_OFFSET_MS = 700.0 

# Shaders (GLSL 300 ES for Pi 5 Driver)
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

def get_vop_paths():
    user_home = os.path.expanduser(f"~{os.environ.get('SUDO_USER', '')}")
    base_dir = os.path.join(user_home, "vop")
    return {"PRO_MAG": os.path.join(base_dir, "ProjMag"), "CAM_MAG": os.path.join(base_dir, "CamMag")}

def develop_dng_to_16bit(path):
    with rawpy.imread(path) as raw:
        rgb = raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

def run_vop_engine(job_path):
    with open(job_path, 'r') as f: job = json.load(f)
    is_preview = job.get('type') == 'preview'
    paths = get_vop_paths()

    pygame.init()
    pygame.mouse.set_visible(False)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 0)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_ES)
    
    screen = pygame.display.set_mode((0,0), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
    WIDTH, HEIGHT = screen.get_size()
    ctx = moderngl.create_context(require=300)

    # Texture Loading
    img_path = os.path.join(paths["PRO_MAG"], job['image'])
    img_src = pygame.image.load(img_path).convert_alpha()
    tex = ctx.texture(img_src.get_size(), 4, pygame.image.tostring(img_src, "RGBA", True))

    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    vbo = ctx.buffer(np.array([-1,-1,0,0,0, 1,-1,0,1,0, -1,1,0,0,1, 1,1,0,1,1], dtype='f4'))
    vao = ctx.vertex_array(prog, [(vbo, '3f 2f', 'in_position', 'in_texcoord')], mode=moderngl.TRIANGLE_STRIP)

    p1 = np.array([float(x) for x in job['p_start'].split(',')])
    p2 = np.array([float(x) for x in job['p_end'].split(',')])
    r1 = np.array([float(x) for x in job['r_start'].split(',')])
    r2 = np.array([float(x) for x in job['r_end'].split(',')])

    if is_preview:
        t = float(job.get('preview_p', 0.5))
        ctx.clear(0,0,0)
        proj = Matrix44.perspective_projection(float(job['fov']), WIDTH/HEIGHT, 0.1, 1000.0)
        pos = p1 + (t * (p2 - p1)); rot = r1 + (t * (r2 - r1))
        model = Matrix44.from_translation(pos) * Matrix44.from_x_rotation(np.radians(rot[0])) * \
                Matrix44.from_y_rotation(np.radians(rot[1])) * Matrix44.from_z_rotation(np.radians(rot[2]))
        
        # Oklab transition
        col = color.get_perceptual_color(t, job['c_start'], job['c_end'])
        prog['filter_color'].write(np.array(col, dtype='f4'))
        prog['mvp'].write((proj * model).astype('f4'))
        tex.use(); vao.render()
        pygame.display.flip(); time.sleep(3)
    else:
        # --- SMEAR EXECUTION ---
        x_ms = float(job['smear']) * 1000.0
        total_exposure_ms = x_ms + 1000.0 # 500ms black header/tail
        output_file = os.path.join(paths["CAM_MAG"], f"latent_{str(job['frame']).zfill(4)}.tif")
        buffer_file = "/tmp/vop_capture.dng"
        
        shutter_us = int(total_exposure_ms * 1000)
        
        # Parallel Camera Launch (RESTORED v0.0.17 CMD)
        cam_proc = subprocess.Popen([
            "rpicam-still", "-o", buffer_file, "-r",
            "--shutter", str(shutter_us), "--gain", str(job['gain']),
            "--awbgains", f"{job['awb_r']},{job['awb_b']}", "--immediate", "--denoise", "off", "-n"
        ])

        time.sleep(LATENCY_OFFSET_MS / 1000.0)
        anchor = time.time()
        while True:
            elapsed = (time.time() - anchor) * 1000
            if elapsed > total_exposure_ms: break
            
            ctx.clear(0,0,0)
            if 500.0 <= elapsed <= (500.0 + x_ms):
                t = (elapsed - 500.0) / x_ms
                proj = Matrix44.perspective_projection(float(job['fov']), WIDTH/HEIGHT, 0.1, 1000.0)
                pos = p1 + (t * (p2 - p1)); rot = r1 + (t * (r2 - r1))
                model = Matrix44.from_translation(pos) * Matrix44.from_x_rotation(np.radians(rot[0])) * \
                        Matrix44.from_y_rotation(np.radians(rot[1])) * Matrix44.from_z_rotation(np.radians(rot[2]))
                
                # Oklab color smear
                col = color.get_perceptual_color(t, job['c_start'], job['c_end'])
                prog['filter_color'].write(np.array(col, dtype='f4'))
                prog['mvp'].write((proj * model).astype('f4'))
                tex.use(); vao.render()
            
            pygame.display.flip()
        
        ctx.clear(0,0,0); pygame.display.flip()
        cam_proc.wait()

        # --- 16-BIT DEVELOP & BIPACK ---
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
    parser = argparse.ArgumentParser(); parser.add_argument("--job", required=True)
    run_vop_engine(parser.parse_args().job)