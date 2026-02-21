"""
VOP Module:     engine.py
Version:        v0.0.76-stable
Description:    Primary execution loop. Dependencies isolated to external modules.
"""
import os
import sys
import json
import time
import argparse
import glob
import numpy as np
import moderngl
import pygame

import interpolator
import vop_math as vmath
import camera_hardware as hw
import color_utils as cutil

os.environ["SDL_VIDEODRIVER"] = "kmsdrm"

def log_audit(msg): 
    print(f"[{time.strftime('%H:%M:%S')}] AUDIT: {msg}")

def save_frame_async(buffer_file, output_file, tiff_flag, cam_gel_rgb, frame_num, mono_forced):
    try:
        success = cutil.process_and_stack_latent_image(buffer_file, output_file, tiff_flag, cam_gel_rgb, mono_forced)
        if success:
            with open("/tmp/vop_heartbeat", "w") as f: 
                f.write(str(frame_num))
    except Exception as e: 
        log_audit(f"Save Error: {e}")

def run_vop_engine(job_path):
    with open(job_path, 'r') as f: 
        job_data = json.load(f)
        
    base_path = os.path.dirname(os.path.abspath(__file__))
    cam_mag_dir = os.path.join(base_path, "CamMag")
    proj_mag_dir = os.path.join(base_path, "ProjMag")
    static_dir = os.path.join(base_path, "static")

    timeline = interpolator.Timeline(job_data)

    pygame.init()
    screen = None
    for _ in range(5):
        try:
            screen = pygame.display.set_mode((0,0), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
            if screen: break
        except: 
            time.sleep(0.2)
            
    if not screen: 
        sys.exit(1)
        
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

    is_sequence = (job_data.get('image') == 'SEQUENCE')
    seq_files = sorted(glob.glob(os.path.join(proj_mag_dir, "frame_*.tif"))) if is_sequence else []
    current_src_idx = -1
    
    def load_texture(idx):
        if is_sequence and seq_files:
            idx = max(0, min(len(seq_files)-1, int(idx)))
            path = seq_files[idx]
        else:
            path = os.path.join(proj_mag_dir, job_data.get('image', ''))
            
        if os.path.exists(path):
            img_s = pygame.image.load(path).convert_alpha()
            iw, ih = img_s.get_size()
            ar = float(iw)/float(ih) if ih > 0 else 1.0
        else:
            img_s = pygame.Surface((10,10)); ar = 1.0
        
        return ctx.texture(img_s.get_size(), 4, pygame.image.tostring(img_s, "RGBA", True)), ar

    tex, aspect_ratio = load_texture(0)
    current_src_idx = 0
    
    world_scale = float(job_data.get('coord_scale', 1.0))
    mono_active = (job_data.get('mono_mode') == 'on') 
    prog['mono_mode'].value = mono_active
    res_str = job_data.get('cam_res', '2028x1520')

    def execute_exposure(frame_num, is_preview=False):
        nonlocal tex, aspect_ratio, current_src_idx, mono_active
        
        playhead = 0.0
        if is_sequence:
            playhead = timeline.calculate_playhead_at(frame_num)
            if int(playhead) != current_src_idx:
                tex.release()
                tex, aspect_ratio = load_texture(playhead)
                current_src_idx = int(playhead)

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
            
            mvp = vmath.get_frustum_fit_matrix(
                float(job_data['fov']), aspect_ratio, world_scale, 
                st['p'], st['r'], WIDTH, HEIGHT
            )
            
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
                prog['filter_color'].write(step['c']); prog['mvp'].write(step['mvp'])
                tex.use(); vao.render()
            pygame.display.flip()
        
        ctx.finish(); cam_proc.wait()
        avg_cg = (timeline.get_state(t_start)['cg'] + timeline.get_state(t_end)['cg']) / 2.0

        if is_preview:
            cutil.generate_sensor_preview(buf_f, static_dir, avg_cg, mono_active)
        else:
            tiff_flag = 8 if job_data.get('tiff_compression') == 'zip' else 1
            save_frame_async(buf_f, out_f, tiff_flag, avg_cg, frame_num, mono_active)

    if job_data.get('type') == 'preview':
        frame_t = float(job_data.get('probe_frame', 1)) + float(job_data.get('probe_sub', 0))
        
        if is_sequence:
            playhead = timeline.calculate_playhead_at(frame_t)
            if int(playhead) != current_src_idx:
                tex.release()
                tex, aspect_ratio = load_texture(playhead)
                current_src_idx = int(playhead)

        st = timeline.get_state(frame_t)
        ctx.clear(0,0,0); ctx.viewport = (0, 0, WIDTH, HEIGHT)
        
        mvp = vmath.get_frustum_fit_matrix(
            float(job_data['fov']), aspect_ratio, world_scale, 
            st['p'], st['r'], WIDTH, HEIGHT
        )
        
        prog['filter_color'].write(st['c'].astype('f4')); prog['mvp'].write(mvp)
        tex.use(); vao.render()
        pixels = ctx.screen.read(components=3); ctx.finish()
        cutil.write_screen_capture(pixels, WIDTH, HEIGHT, static_dir)
        
    elif job_data.get('type') == 'cam_preview':
        execute_exposure(float(job_data.get('probe_frame', 1)), is_preview=True)
    else:
        if os.path.exists("/tmp/vop_heartbeat"): 
            os.remove("/tmp/vop_heartbeat")
        all_frames = []
        for track_keys in timeline.tracks.values():
            for k in track_keys: all_frames.append(k['f'])
        if not all_frames: return
        f_start, f_end = min(all_frames), max(all_frames)
        for f in range(f_start, f_end + 1):
            execute_exposure(f)
            
    pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--job", required=True)
    run_vop_engine(parser.parse_args().job)
