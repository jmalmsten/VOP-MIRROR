"""
VOP Module:     engine.py
Version:        v0.0.84-stable
Description:    Primary execution loop. Dependencies isolated to external modules.
                Includes decoupled EXP (Exposure Time in seconds) and SD (Smear Distance).
"""
import os
import sys
import json
import time
import argparse
import subprocess
import pygame

import interpolator
import vop_math as vmath
import camera_hardware as hw
import color_utils as cutil
import graphics_utils as gfx

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
    
    wp_dir = os.path.join(base_path, "WorkPrints")
    os.makedirs(wp_dir, exist_ok=True)

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
    
    ctx, prog, vao = gfx.init_render_pipeline()
    tex_mgr = gfx.TextureManager(ctx, proj_mag_dir, job_data)
    
    world_scale = float(job_data.get('coord_scale', 1.0))
    mono_active = (job_data.get('mono_mode') == 'on') 
    prog['mono_mode'].value = mono_active
    res_str = job_data.get('cam_res', '2028x1520')

    def execute_exposure(frame_num, is_preview=False):
        if not job_data.get('image'):
            log_audit("ERROR: No image selected in ProjMag. Execution aborted.")
            return

        playhead = timeline.calculate_playhead_at(frame_num) if tex_mgr.is_sequence else 0.0
        tex, aspect_ratio = tex_mgr.load(playhead)

        center_st = timeline.get_state(frame_num)
        
        # --- DECOUPLED EXPOSURE & SMEAR LOGIC ---
        # Note: 's' in the JSON key maps to EXP (Exposure Time in seconds)
        exp_sec = float(center_st['s'])  
        sd_frames = float(center_st['sd']) 
        ph_offset = float(center_st['ph']) 
        
        # Calculate mathematical start and end points on the timeline based ONLY on Smear Distance (SD).
        # If SD = 0, t_start and t_end equal frame_num, resulting in zero geometry movement.
        t_start = frame_num - (sd_frames * ph_offset)
        t_end = frame_num + (sd_frames * (1.0 - ph_offset))
        
        # Calculate the physical duration the camera shutter is open based ONLY on EXP.
        x_ms = exp_sec * 1000.0
        total_ms = x_ms + 1000.0
        
        # Calculate how many subframes to render during the exposure
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
            ctx.clear(0,0,0)
            ctx.viewport = (0, 0, WIDTH, HEIGHT)
            
            if 500.0 <= elapsed <= (500.0 + x_ms):
                idx = int(((elapsed - 500.0) / x_ms) * (len(path_cache) - 1))
                idx = max(0, min(len(path_cache)-1, idx))
                step = path_cache[idx]
                
                prog['filter_color'].write(step['c'])
                prog['mvp'].write(step['mvp'])
                tex.use()
                vao.render()
                
            pygame.display.flip()
        
        ctx.finish()
        cam_proc.wait() 
        
        avg_cg = (timeline.get_state(t_start)['cg'] + timeline.get_state(t_end)['cg']) / 2.0

        if is_preview:
            cutil.generate_sensor_preview(buf_f, static_dir, avg_cg, mono_active)
        else:
            tiff_flag = 8 if job_data.get('tiff_compression') == 'zip' else 1
            save_frame_async(buf_f, out_f, tiff_flag, avg_cg, frame_num, mono_active)

    if job_data.get('type') == 'preview':
        if not job_data.get('image'):
            log_audit("ERROR: No image selected. Cannot render synthetic probe.")
            pygame.quit()
            return

        frame_t = float(job_data.get('probe_frame', 1)) + float(job_data.get('probe_sub', 0))
        playhead = timeline.calculate_playhead_at(frame_t) if tex_mgr.is_sequence else 0.0
        tex, aspect_ratio = tex_mgr.load(playhead)

        st = timeline.get_state(frame_t)
        ctx.clear(0,0,0)
        ctx.viewport = (0, 0, WIDTH, HEIGHT)
        
        mvp = vmath.get_frustum_fit_matrix(
            float(job_data['fov']), aspect_ratio, world_scale, 
            st['p'], st['r'], WIDTH, HEIGHT
        )
        
        prog['filter_color'].write(st['c'].astype('f4'))
        prog['mvp'].write(mvp)
        tex.use()
        vao.render()
        
        pixels = ctx.screen.read(components=3)
        ctx.finish()
        cutil.write_screen_capture(pixels, WIDTH, HEIGHT, static_dir)
        
    elif job_data.get('type') == 'cam_preview':
        execute_exposure(float(job_data.get('probe_frame', 1)), is_preview=True)
        
    else:
        if os.path.exists("/tmp/vop_heartbeat"): 
            os.remove("/tmp/vop_heartbeat")
            
        all_frames = [k['f'] for track_keys in timeline.tracks.values() for k in track_keys]
        if not all_frames: return
        
        f_start, f_end = min(all_frames), max(all_frames)
        
        log_audit(f"Beginning Render Sequence: Frames {f_start} to {f_end}")
        for f in range(f_start, f_end + 1):
            execute_exposure(f)
            
        log_audit("Sequence Complete. Compiling FFmpeg Workprint...")
        
        fps = job_data.get('fps', '24')
        ts = int(time.time())
        out_mp4 = os.path.join(wp_dir, f"vop_wp_{ts}.mp4")
        
        ffmpeg_cmd = [
            "ffmpeg", "-y", 
            "-framerate", str(fps), 
            "-pattern_type", "glob", 
            "-i", os.path.join(cam_mag_dir, "*.tif"),
            "-c:v", "libx264", 
            "-pix_fmt", "yuv420p", 
            out_mp4
        ]
        
        try:
            subprocess.run(ffmpeg_cmd, check=True)
            log_audit(f"Workprint Saved: {out_mp4}")
        except Exception as e:
            log_audit(f"Workprint Compilation Failed: {e}")
            
    tex_mgr.release()
    pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    run_vop_engine(parser.parse_args().job)