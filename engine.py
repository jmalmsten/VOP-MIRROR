"""
VOP Module:     engine.py
Version:        v0.0.57-stable
Description:    Centered Previews & RAM-only LIME Previews.
"""
import os, sys, json, time, argparse, subprocess, threading
import numpy as np
import moderngl, pygame, cv2, rawpy
from pyrr import Matrix44
import camera_hardware as hw 

# Force Pi to use the correct display driver for fullscreen HDMI
os.environ["SDL_VIDEODRIVER"] = "kmsdrm"

def log_audit(msg): print(f"[{time.strftime('%H:%M:%S')}] AUDIT: {msg}")

def save_frame_async(buffer_file, output_file, tiff_flag):
    try:
        if not os.path.exists(buffer_file): return
        with rawpy.imread(buffer_file) as raw:
            img = cv2.cvtColor(raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16), cv2.COLOR_RGB2BGR)
        
        # L.I.M.E. logic: Stack multi-exposure into existing file if present
        if os.path.exists(output_file):
            existing = cv2.imread(output_file, cv2.IMREAD_UNCHANGED)
            if existing is not None and existing.shape == img.shape:
                img = cv2.add(existing, img)
        
        cv2.imwrite(output_file, img, [cv2.IMWRITE_TIFF_COMPRESSION, tiff_flag])
        if os.path.exists(buffer_file): os.remove(buffer_file)
    except Exception as e: log_audit(f"SAVE ERROR: {e}")

def run_vop_engine(job_path):
    with open(job_path, 'r') as f: job = json.load(f)
    base_path = os.path.dirname(os.path.abspath(__file__))
    cam_mag_dir = os.path.join(base_path, "CamMag")
    proj_mag_dir = os.path.join(base_path, "ProjMag")
    static_dir = os.path.join(base_path, "static")

    pygame.init()
    pygame.mouse.set_visible(False)
    screen = pygame.display.set_mode((0,0), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
    WIDTH, HEIGHT = screen.get_size()
    ctx = moderngl.create_context(require=300)

    # Load Projection Texture
    img_path = os.path.join(proj_mag_dir, job['image'])
    img_s = pygame.image.load(img_path).convert_alpha() if os.path.exists(img_path) else pygame.Surface((10,10))
    tex = ctx.texture(img_s.get_size(), 4, pygame.image.tostring(img_s, "RGBA", True))
    
    prog = ctx.program(
        vertex_shader="""#version 300 es
            in vec3 in_position; in vec2 in_texcoord; out vec2 v_tex; uniform mat4 mvp;
            void main() { gl_Position = mvp * vec4(in_position, 1.0); v_tex = in_texcoord; }""",
        fragment_shader="""#version 300 es
            precision highp float; in vec2 v_tex; out vec4 f_col; uniform sampler2D texture0; uniform vec3 filter_color;
            void main() { vec4 t = texture(texture0, v_tex); f_col = vec4(t.rgb * filter_color, t.a); }"""
    )
    vbo = ctx.buffer(np.array([-1,-1,0,0,0, 1,-1,0,1,0, -1,1,0,0,1, 1,1,0,1,1], dtype='f4'))
    vao = ctx.vertex_array(prog, [(vbo, '3f 2f', 'in_position', 'in_texcoord')], mode=moderngl.TRIANGLE_STRIP)

    res_str = job.get('cam_res', '2028x1520')

    # PREVIEW LOGIC (Probe or Single Capture)
    if job.get('type') in ['preview', 'cam_preview']:
        ctx.clear(0,0,0)
        ctx.viewport = (0, 0, WIDTH, HEIGHT)
        
        p = np.array([float(x) for x in job['p_start'].split(',')])
        r = np.array([float(x) for x in job['r_start'].split(',')])
        c = np.array(job['c_start'])
        proj = Matrix44.perspective_projection(float(job['fov']), WIDTH/HEIGHT, 0.1, 1000.0)
        model = Matrix44.from_translation(p) * Matrix44.from_x_rotation(np.radians(r[0])) * \
                Matrix44.from_y_rotation(np.radians(r[1])) * Matrix44.from_z_rotation(np.radians(r[2]))
        
        prog['filter_color'].write(c.astype('f4'))
        prog['mvp'].write((proj * model).astype('f4'))
        tex.use(); vao.render()

        if job['type'] == 'preview':
            pixels = ctx.screen.read(components=3); ctx.finish()
            cap = np.frombuffer(pixels, dtype='u1').reshape(HEIGHT, WIDTH, 3)[::-1]
            cv2.imwrite(os.path.join(static_dir, "probe_live.jpg"), cv2.cvtColor(cap, cv2.COLOR_RGB2BGR))
        else:
            x_ms = float(job['smear']) * 1000.0
            buf_f = "/tmp/vop_ram_preview.dng"
            cam_proc = hw.trigger_capture(buf_f, x_ms+1000, job['gain'], job['awb_r'], job['awb_b'], res_str)
            hw.wait_for_sensor_prime()
            pygame.display.flip()
            cam_proc.wait()
            
            with rawpy.imread(buf_f) as raw:
                img = cv2.cvtColor(raw.postprocess(gamma=(1,1), no_auto_bright=True), cv2.COLOR_RGB2BGR)
            
            # RAM L.I.M.E. Merge: Overlay current capture on top of disk version for preview
            target_f = os.path.join(cam_mag_dir, f"latent_{str(job.get('probe_frame','0001')).zfill(4)}.tif")
            if os.path.exists(target_f):
                disk_img = cv2.imread(target_f)
                if disk_img is not None:
                    disk_img = cv2.resize(disk_img, (img.shape[1], img.shape[0]))
                    img = cv2.add(img, disk_img)
            cv2.imwrite(os.path.join(static_dir, "probe_live.jpg"), img)
            if os.path.exists(buf_f): os.remove(buf_f)
    
    # SEQUENCE EXECUTION LOGIC
    else:
        frames = job.get('sequence', [job])
        for frame_job in frames:
            p1, p2 = [np.array([float(x) for x in frame_job[k].split(',')]) for k in ['p_start', 'p_end']]
            r1, r2 = [np.array([float(x) for x in frame_job[k].split(',')]) for k in ['r_start', 'r_end']]
            c1, c2 = np.array(frame_job['c_start']), np.array(frame_job['c_end'])
            
            x_ms = float(frame_job['smear']) * 1000.0
            total_ms = x_ms + 1000.0
            out_f = os.path.join(cam_mag_dir, f"latent_{str(frame_job['frame']).zfill(4)}.tif")
            buf_f = f"/tmp/vop_buf_{frame_job['frame']}.dng"
            
            cam_proc = hw.trigger_capture(buf_f, total_ms, job['gain'], job['awb_r'], job['awb_b'], res_str)
            hw.wait_for_sensor_prime()
            
            anchor = time.time()
            while (time.time() - anchor) * 1000 < total_ms:
                elapsed = (time.time() - anchor) * 1000
                ctx.clear(0,0,0); ctx.viewport = (0, 0, WIDTH, HEIGHT)
                if 500.0 <= elapsed <= (500.0 + x_ms):
                    t = (elapsed - 500.0) / x_ms
                    proj = Matrix44.perspective_projection(float(job['fov']), WIDTH/HEIGHT, 0.1, 1000.0)
                    pos, rot = p1 + (t * (p2 - p1)), r1 + (t * (r2 - r1))
                    model = Matrix44.from_translation(pos) * Matrix44.from_x_rotation(np.radians(rot[0])) * \
                            Matrix44.from_y_rotation(np.radians(rot[1])) * Matrix44.from_z_rotation(np.radians(rot[2]))
                    prog['filter_color'].write((c1 + (c2 - c1) * t).astype('f4'))
                    prog['mvp'].write((proj * model).astype('f4'))
                    tex.use(); vao.render()
                pygame.display.flip()
            
            ctx.finish(); cam_proc.wait()
            threading.Thread(target=save_frame_async, args=(buf_f, out_f, 8 if job.get('tiff_compression') == 'zip' else 1)).start()
    pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--job", required=True)
    run_vop_engine(parser.parse_args().job)