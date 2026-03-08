"""
VOP Module:     engine.py
Version:        v0.0.98-stable
Description:    Primary execution loop. 
                Appended the 700ms sync offset to the physical camera shutter argument
                to prevent the camera from closing before the delayed render loop finishes.
"""
import os
import sys
import json
import time
import argparse
import subprocess
import pygame
import numpy as np
import moderngl

import interpolator
import vop_math as vmath
import camera_hardware as hw
import color_utils as cutil
import graphics_utils as gfx

os.environ["SDL_VIDEODRIVER"] = "kmsdrm"

def log_audit(msg): 
    print(f"[{time.strftime('%H:%M:%S')}] AUDIT: {msg}")

def run_vop_engine(job_path):
    with open(job_path, 'r') as f: 
        job_data = json.load(f)
        
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cam_mag_dir = os.path.join(base_path, "CamMag")
    proj_mag_dir = os.path.join(base_path, "ProjMag")
    static_dir = os.path.join(base_path, "static")
    wp_dir = os.path.join(base_path, "WorkPrints")

    timeline = interpolator.Timeline(job_data)

    pygame.init()
    pygame.mouse.set_visible(False)
    
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_ES)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 0)
    
    WIDTH, HEIGHT = 1920, 1080
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
    
    ctx, prog, vao = gfx.init_render_pipeline()
    tex_mgr = gfx.TextureManager(ctx, proj_mag_dir, job_data)
    
    world_scale = float(job_data.get('coord_scale', 1.0))
    res_str = job_data.get('cam_res', '2028x1520')

    def execute_exposure(frame_num, is_preview=False):
        playhead = timeline.calculate_playhead_at(frame_num)
        tex, aspect_ratio = tex_mgr.load(playhead)
        st = timeline.get_state(frame_num)

        smear_sec = float(st['exp'])  
        x_ms = smear_sec * 1000.0
        
        # Render Loop bounds: 500ms header + smear + 500ms tail.
        total_ms = x_ms + 1000.0
        
        # We explicitly add the 700ms sensor sleep offset to the camera argument. 
        # This keeps the shutter open just long enough to capture the end of the delayed render loop.
        cam_shutter_ms = total_ms + 700.0
        
        sd_frames = float(st.get('sd', 1.0))
        ph_offset = float(st.get('ph', 0.5))
        
        t_start = frame_num - (sd_frames * ph_offset)
        t_end = frame_num + (sd_frames * (1.0 - ph_offset))
        
        buf_f = f"/tmp/vop_buf_{frame_num}.dng" if not is_preview else "/tmp/vop_prev_buf.dng"
        
        cam_proc = hw.trigger_capture(buf_f, cam_shutter_ms, job_data.get('gain', 1.0), 
                                      job_data.get('awb_r', 1.0), job_data.get('awb_b', 1.0), res_str)
        
        hw.wait_for_sensor_prime()

        anchor = time.time()
        while (time.time() - anchor) * 1000 < total_ms:
            elapsed = (time.time() - anchor) * 1000
            ctx.clear(0, 0, 0, 1.0)
            
            if 500.0 <= elapsed <= (500.0 + x_ms):
                t_norm = (elapsed - 500.0) / max(1.0, x_ms)
                
                if timeline.mode == 'mds':
                    st_sub = timeline.get_mds_state(float(frame_num), t_norm)
                else:
                    t_frame = t_start + (t_end - t_start) * t_norm
                    st_sub = timeline.get_state(t_frame)

                mvp = vmath.get_frustum_fit_matrix(
                    float(job_data.get('fov', 45)), aspect_ratio, world_scale, 
                    st_sub['p'], st_sub['r'], 
                    st_sub.get('lp', np.zeros(3, 'f4')), st_sub.get('lr', np.zeros(3, 'f4')),
                    WIDTH, HEIGHT
                )
                
                prog['filter_color'].write(st_sub['pg'].astype('f4'))
                prog['mvp'].write(mvp)
                tex.use(0)
                vao.render(moderngl.TRIANGLE_STRIP)
                
            pygame.display.flip()
        
        ctx.finish()
        cam_proc.wait() 

        if is_preview:
            cutil.generate_sensor_preview(buf_f, static_dir, st['cg'])
        else:
            tiff_flag = 8 if job_data.get('tiff_compression') == 'zip' else 1
            out_f = os.path.join(cam_mag_dir, f"latent_{str(frame_num).zfill(4)}.tif")
            cutil.process_and_stack_latent_image(buf_f, out_f, tiff_flag, st['cg'], False)

    task = job_data.get('type')
    
    if task == 'preview':
        frame_t = float(job_data.get('probe_frame', 1))
        t_norm = float(job_data.get('probe_sub', 0.5))
        
        tex, aspect_ratio = tex_mgr.load(0.0)
        
        if timeline.mode == 'mds':
            st = timeline.get_mds_state(frame_t, t_norm)
        else:
            sd = timeline.get_state(frame_t).get('sd', 1.0)
            ph = timeline.get_state(frame_t).get('ph', 0.5)
            t_start = frame_t - (sd * ph)
            t_end = frame_t + (sd * (1.0 - ph))
            st = timeline.get_state(t_start + (t_end - t_start) * t_norm)
            
        mvp = vmath.get_frustum_fit_matrix(
            float(job_data.get('fov', 45)), aspect_ratio, world_scale, 
            st['p'], st['r'], 
            st.get('lp', np.zeros(3, 'f4')), st.get('lr', np.zeros(3, 'f4')),
            WIDTH, HEIGHT
        )
        
        fbo_tex = ctx.texture((WIDTH, HEIGHT), 4)
        fbo = ctx.framebuffer(color_attachments=[fbo_tex])
        fbo.use()
        fbo.clear(0, 0, 0, 1.0)
        prog['filter_color'].write(st['pg'].astype('f4'))
        prog['mvp'].write(mvp)
        tex.use(0)
        vao.render(moderngl.TRIANGLE_STRIP)
        ctx.finish() 
        pixels = fbo.read(components=4)
        fbo.release()
        fbo_tex.release()
        
        ctx.screen.use()
        ctx.screen.clear(0, 0, 0, 1.0)
        prog['filter_color'].write(st['pg'].astype('f4'))
        prog['mvp'].write(mvp)
        tex.use(0)
        vao.render(moderngl.TRIANGLE_STRIP)
        pygame.display.flip()
        ctx.finish()
        
        cutil.write_screen_capture(pixels, WIDTH, HEIGHT, static_dir)
        
    elif task == 'cam_preview':
        execute_exposure(float(job_data.get('probe_frame', 1)), is_preview=True)
        
    elif task == 'execute':
        all_frames = [k['f'] for k in timeline.tracks['pos']] if timeline.tracks['pos'] else []
        if all_frames:
            f_start, f_end = int(min(all_frames)), int(max(all_frames))
            
            with open("/tmp/vop_heartbeat", "w") as hbf:
                json.dump({"current": f_start, "total": f_end, "eta": 0, "est_mb": 0, "msg": "PREPARING"}, hbf)
                
            start_time = time.time()
            
            for f in range(f_start, f_end + 1):
                execute_exposure(f)
                
                frames_done = f - f_start + 1
                elapsed = time.time() - start_time
                fps_rate = frames_done / elapsed if elapsed > 0 else 0
                rem_frames = f_end - f
                eta_sec = int(rem_frames / fps_rate) if fps_rate > 0 else 0
                est_mb = frames_done * 15 
                
                with open("/tmp/vop_heartbeat", "w") as hbf:
                    json.dump({"current": f, "total": f_end, "eta": eta_sec, "est_mb": est_mb, "msg": "RENDERING"}, hbf)
                    
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
                log_audit(f"FFmpeg compile failed: {e}")

    tex_mgr.release()
    pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    try:
        run_vop_engine(parser.parse_args().job)
    except Exception as e:
        log_audit(f"Engine Exception: {e}")
        sys.exit(1)