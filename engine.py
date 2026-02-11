"""
VOP Module:     engine.py
Version:        v0.0.64-stable
Description:    Fixed N-Key sequence range logic.
"""
import os, sys, json, time, argparse, subprocess, threading
import numpy as np
import moderngl, pygame, cv2, rawpy
from pyrr import Matrix44
import camera_hardware as hw 
import interpolator

os.environ["SDL_VIDEODRIVER"] = "kmsdrm"

def log_audit(msg): print(f"[{time.strftime('%H:%M:%S')}] AUDIT: {msg}")

def save_frame_async(buffer_file, output_file, tiff_flag, cam_gel_rgb, frame_num, mono_forced):
    try:
        if not os.path.exists(buffer_file): return
        with rawpy.imread(buffer_file) as raw:
            img = cv2.cvtColor(raw.postprocess(gamma=(1,1), no_auto_bright=True, output_bps=16), cv2.COLOR_RGB2BGR)
        
        if mono_forced:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

        img = (img.astype(np.float32) * [cam_gel_rgb[2], cam_gel_rgb[1], cam_gel_rgb[0]]).clip(0, 65535).astype(np.uint16)

        if os.path.exists(output_file):
            existing = cv2.imread(output_file, cv2.IMREAD_UNCHANGED)
            if existing is not None and existing.shape == img.shape:
                img = cv2.add(existing, img)
        
        cv2.imwrite(output_file, img, [cv2.IMWRITE_TIFF_COMPRESSION, tiff_flag])
        if os.path.exists(buffer_file): os.remove(buffer_file)
        with open("/tmp/vop_heartbeat", "w") as f: f.write(str(frame_num))
    except Exception as e: log_audit(f"Save Error: {e}")

def run_vop_engine(job_path):
    with open(job_path, 'r') as f: job_data = json.load(f)
    base_path = os.path.dirname(os.path.abspath(__file__))
    cam_mag_dir = os.path.join(base_path, "CamMag")
    proj_mag_dir = os.path.join(base_path, "ProjMag")
    static_dir = os.path.join(base_path, "static")

    # Initialize Timeline
    timeline = interpolator.Timeline(job_data)

    pygame.init()
    screen = None
    for _ in range(5):
        try:
            screen = pygame.display.set_mode((0,0), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
            if screen: break
        except: time.sleep(0.2)
    if not screen: sys.exit(1)
    
    pygame.mouse.set_visible(False)
    WIDTH, HEIGHT = screen.get_size()
    ctx = moderngl.create_context(require=300)

    prog = ctx.program(
        vertex_shader="""#version 300 es
            in vec3 in_position; in vec2 in_texcoord; out vec2 v_tex; uniform mat4 mvp;
            void main() { gl_Position = mvp * vec4(in_position, 1.0); v_tex = in_texcoord; }""",
        fragment_shader="""#version 300 es
            precision highp float; in vec2 v_tex; out vec4 f_col; uniform sampler2D texture0; uniform vec3 filter_color; uniform bool mono_mode;
            void main() { 
                vec4 t = texture(texture0, v_tex); 
                vec3 rgb = t.rgb * filter_color;
                if(mono_mode) {
                    float y = dot(rgb, vec3(0.2126, 0.7152, 0.0722));
                    rgb = vec3(y);
                }
                f_col = vec4(rgb, t.a); 
            }"""
    )
    vbo = ctx.buffer(np.array([-1,-1,0,0,0, 1,-1,0,1,0, -1,1,0,0,1, 1,1,0,1,1], dtype='f4'))
    vao = ctx.vertex_array(prog, [(vbo, '3f 2f', 'in_position', 'in_texcoord')], mode=moderngl.TRIANGLE_STRIP)

    img_path = os.path.join(proj_mag_dir, job_data['image'])
    img_s = pygame.image.load(img_path).convert_alpha() if os.path.exists(img_path) else pygame.Surface((10,10))
    tex = ctx.texture(img_s.get_size(), 4, pygame.image.tostring(img_s, "RGBA", True))
    
    mono_active = (job_data.get('mono_mode') == 'on')
    prog['mono_mode'].value = mono_active
    res_str = job_data.get('cam_res', '2028x1520')

    def execute_exposure(frame_num, is_preview=False):
        center_st = timeline.get_state(frame_num)
        smear_len = center_st['s']
        shutter_ph = center_st['ph']
        
        t_start = frame_num - (smear_len * shutter_ph)
        t_end = frame_num + (smear_len * (1.0 - shutter_ph))
        
        x_ms = float(center_st['s']) * 1000.0
        total_ms = x_ms + 1000.0

        num_steps = int(x_ms / 16.666) + 1
        path_cache = []
        for i in range(num_steps):
            t_norm = i / max(1, num_steps - 1)
            t_frame = t_start + (t_end - t_start) * t_norm
            st = timeline.get_state(t_frame)
            
            proj = Matrix44.perspective_projection(float(job_data['fov']), WIDTH/HEIGHT, 0.1, 1000.0)
            model = Matrix44.from_translation(st['p']) * \
                    Matrix44.from_x_rotation(np.radians(st['r'][0])) * \
                    Matrix44.from_y_rotation(np.radians(st['r'][1])) * \
                    Matrix44.from_z_rotation(np.radians(st['r'][2]))
            mvp = (proj * model).astype('f4')
            path_cache.append({'mvp': mvp, 'c': st['c'].astype('f4')})
        
        buf_f = f"/tmp/vop_buf_{frame_num}.dng" if not is_preview else "/tmp/vop_prev_buf.dng"
        out_f = os.path.join(cam_mag_dir, f"latent_{str(frame_num).zfill(4)}.tif")
        
        cam_proc = hw.trigger_capture(buf_f, total_ms, job_data['gain'], job_data['awb_r'], job_data['awb_b'], res_str)
        hw.wait_for_sensor_prime()

        anchor = time.time()
        while (time.time() - anchor) * 1000 < total_ms:
            elapsed = (time.time() - anchor) * 1000
            ctx.clear(0,0,0); ctx.viewport = (0, 0, WIDTH, HEIGHT)
            
            if 500.0 <= elapsed <= (500.0 + x_ms):
                idx = int(((elapsed - 500.0) / x_ms) * (len(path_cache) - 1))
                idx = max(0, min(len(path_cache)-1, idx))
                step = path_cache[idx]
                
                prog['filter_color'].write(step['c'])
                prog['mvp'].write(step['mvp'])
                tex.use(); vao.render()
            pygame.display.flip()
        
        ctx.finish(); cam_proc.wait()

        avg_cg = (timeline.get_state(t_start)['cg'] + timeline.get_state(t_end)['cg']) / 2.0

        if is_preview:
            with rawpy.imread(buf_f) as raw:
                img = cv2.cvtColor(raw.postprocess(gamma=(1,1), no_auto_bright=True), cv2.COLOR_RGB2BGR)
            if mono_active:
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
            img = (img.astype(np.float32) * [avg_cg[2], avg_cg[1], avg_cg[0]]).clip(0, 255).astype(np.uint8)
            cv2.imwrite(os.path.join(static_dir, "probe_live.jpg"), img)
            if os.path.exists(buf_f): os.remove(buf_f)
        else:
            save_frame_async(buf_f, out_f, 8 if job_data.get('tiff_compression') == 'zip' else 1, avg_cg, frame_num, mono_active)

    if job_data.get('type') == 'preview':
        # Point-in-time probe
        frame_t = float(job_data.get('probe_frame', 1)) + float(job_data.get('probe_sub', 0))
        st = timeline.get_state(frame_t)
        ctx.clear(0,0,0); ctx.viewport = (0, 0, WIDTH, HEIGHT)
        proj = Matrix44.perspective_projection(float(job_data['fov']), WIDTH/HEIGHT, 0.1, 1000.0)
        model = Matrix44.from_translation(st['p']) * \
                Matrix44.from_x_rotation(np.radians(st['r'][0])) * \
                Matrix44.from_y_rotation(np.radians(st['r'][1])) * \
                Matrix44.from_z_rotation(np.radians(st['r'][2]))
        prog['filter_color'].write(st['c'].astype('f4'))
        prog['mvp'].write((proj * model).astype('f4'))
        tex.use(); vao.render()
        pixels = ctx.screen.read(components=3); ctx.finish()
        cap = np.frombuffer(pixels, dtype='u1').reshape(HEIGHT, WIDTH, 3)[::-1]
        cv2.imwrite(os.path.join(static_dir, "probe_live.jpg"), cv2.cvtColor(cap, cv2.COLOR_RGB2BGR))
        
    elif job_data.get('type') == 'cam_preview':
        execute_exposure(float(job_data.get('probe_frame', 1)), is_preview=True)

    else:
        # Sequence Execution
        if os.path.exists("/tmp/vop_heartbeat"): os.remove("/tmp/vop_heartbeat")
        
        # DYNAMIC RANGE LOGIC
        if not timeline.keys:
            print("CRITICAL: No keys found in timeline.")
            return

        f_start = timeline.keys[0]['f']
        f_end = timeline.keys[-1]['f']
        
        for f in range(f_start, f_end + 1):
            execute_exposure(f)
            
    pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--job", required=True)
    run_vop_engine(parser.parse_args().job)