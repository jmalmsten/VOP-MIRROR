"""
VOP Module:     engine.py
Version:        v0.1.9
Description:    Multiplicative Dual-World Engine.
                Forces GLES 3.0 profile prior to display initialization.
                Added contextual dark gray background for UI previews to visualize frustum bounds.
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
import cv2

import interpolator
import vop_math as vmath
import camera_hardware as hw
import color_utils as cutil
import graphics_utils as gfx

import traceback

os.environ["SDL_VIDEODRIVER"] = "kmsdrm"

def log_audit(msg): 
    print(f"[{time.strftime('%H:%M:%S')}] AUDIT (v0.1.9): {msg}", flush=True)

def run_vop_engine(job_path):
    
    with open(job_path, 'r') as f: 
        job_data = json.load(f)
    
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    static_dir = os.path.join(base_path, "static")
    cam_mag_dir = os.path.join(base_path, "CamMag")
    wp_dir = os.path.join(base_path, "WorkPrints")
    
    timeline = interpolator.Timeline(job_data)
    
    log_audit(f"Engine Starting | Job: {job_path} | Mode: {timeline.mode.upper()}")

    pygame.init()
    pygame.mouse.set_visible(False)
    
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_ES)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 0)
    
    WIDTH, HEIGHT = 1920, 1080
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
    
    ctx, prog, vao = gfx.init_render_pipeline()
    tex_mgr = gfx.TextureManager(ctx, os.path.join(base_path, "ProjMag"), job_data)

    # Initializing mono_mode
    mono_active = (job_data.get('mono_mode') == True)
    prog['mono_mode'].value = mono_active

    # Create an off-screen FBO for the BiPack layer to render into its own void
    bp_tex = ctx.texture((WIDTH, HEIGHT), 4)
    bp_fbo = ctx.framebuffer(color_attachments=[bp_tex])
    
    mag_scale = float(job_data.get('coord_scale', 1.0))
    bp_scale = float(job_data.get('bipack_coord_scale', 1.0))

    def render_dual_world(frame_num, t_norm, is_preview=False):
        if timeline.mode == 'mds':
            st = timeline.get_mds_state(float(frame_num), t_norm)
        else:
            st_base = timeline.get_state(frame_num)
            t_start = frame_num - (st_base['sd'] * st_base['ph'])
            t_end = frame_num + (st_base['sd'] * (1.0 - st_base['ph']))
            st = timeline.get_state(t_start + (t_end - t_start) * t_norm)

        ph_val = timeline.calculate_playhead_at(frame_num)
        
        tex_mag, asp_mag = tex_mgr.load(ph_val, is_bipack=False)
        tex_bp, asp_bp = tex_mgr.load(ph_val, is_bipack=True)

        bg_color = (0.1, 0.1, 0.1, 1.0) if is_preview else (0.0, 0.0, 0.0, 1.0)
        
        # --- PASS 1: RENDER BIPACK INTO OFF-SCREEN FBO ---
        bp_fbo.use()

        if tex_bp == tex_mgr.white_tex:
            # Bypass logic: If no BiPack is loaded, flood the FBO with pure white.
            # Because we later do a multiplicative blend, pure white is 100% transparent.
            # We skip the vao.render() entirely so keyframe data is ignored.
            bp_fbo.clear(1.0, 1.0, 1.0, 1.0)
        else:
            # Normal logic: Clear to black (opaque) and render the mask.
            bp_fbo.clear(0.0, 0.0, 0.0, 1.0)

            mvp_bp = vmath.get_frustum_fit_matrix(float(job_data.get('fov', 45)), asp_bp, bp_scale, 
                                                st['bp_p'], st['bp_r'], st['lbp_p'], st['lbp_r'], WIDTH, HEIGHT)
            prog['mvp'].write(mvp_bp)
            prog['filter_color'].write(np.array([1.0, 1.0, 1.0], dtype='f4'))
            tex_bp.use(0)
            vao.render(moderngl.TRIANGLE_STRIP)

        # --- PASS 2: RENDER MAG TO THE ACTUAL SCREEN ---
        ctx.screen.use()
        ctx.clear(*bg_color)

        if tex_mag == tex_mgr.white_tex:
            # Bypass logic: If no ProjMag image is loaded, force an Identity Matrix.
            # This makes the 1x1 white texture act as an infinite, unmoving backlight,
            # completely ignoring any leftover position/rotation keyframes.
            mvp_mag = np.eye(4, dtype='f4').tobytes()
        else:
            # Normal logic: Calculate the frustum matrix based on keyframes.
            mvp_mag = vmath.get_frustum_fit_matrix(float(job_data.get('fov', 45)), asp_mag, mag_scale,
                                                   st['p'], st['r'], st['lp'], st['lr'], WIDTH, HEIGHT)
        
        prog['mvp'].write(mvp_mag)
        prog['filter_color'].write(st['pg'].astype('f4'))
        tex_mag.use(0)
        vao.render(moderngl.TRIANGLE_STRIP)
        
        # --- PASS 3: MULTIPLY THE FBO OVER THE SCREEN ---
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = (moderngl.DST_COLOR, moderngl.ZERO)

        # Use a flat Identity Matrix to force the FBO quad to cover the entire screen
        prog['mvp'].write(np.eye(4, dtype='f4').tobytes())
        prog['filter_color'].write(np.array([1.0, 1.0, 1.0], dtype='f4'))
        bp_tex.use(0)
        vao.render(moderngl.TRIANGLE_STRIP)

        ctx.disable(moderngl.BLEND)

    def execute_exposure(frame_num, is_preview=False):
        st = timeline.get_state(frame_num)
        smr_ms = float(st['exp']) * 1000.0
        total_ms = smr_ms + 1000.0
        
        # Safely extract the black clip float (defautling to 0.0 if empty)
        raw_clip = job_data.get('black_clip', 0.0)
        black_clip = float(raw_clip) if raw_clip != "" else 0.0

        log_audit(f"Exposing Frame {frame_num} | Smear: {smr_ms}ms | Shutter Total: {total_ms}ms")
        
        buf_f = f"/tmp/vop_buf_{frame_num}.dng" if not is_preview else "/tmp/vop_prev_buf.dng"
        
        cam_proc = hw.trigger_capture(buf_f, total_ms + 700.0, job_data.get('gain', 1.0), 
                                      job_data.get('awb_r', 1.0), job_data.get('awb_b', 1.0), job_data.get('cam_res','2028x1520'))
        
        hw.wait_for_sensor_prime()

        anchor = time.time()
        while (time.time() - anchor) * 1000 < total_ms:
            elapsed = (time.time() - anchor) * 1000
            
            if 500.0 <= elapsed <= (500.0 + smr_ms):
                t_norm = (elapsed - 500.0) / max(1.0, smr_ms)
                render_dual_world(frame_num, t_norm, is_preview=False)
            else:
                ctx.clear(0.0, 0.0, 0.0, 1.0)
                
            pygame.display.flip()
        
        cam_proc.wait() 
        
        if is_preview:
            # Pass mono_active and black_clip down to the preview generator
            cutil.generate_sensor_preview(buf_f, static_dir, st['cg'], mono_active, black_clip)
        else:
            tiff_flag = 8 if job_data.get('tiff_compression') == 'zip' else 1
            out_f = os.path.join(cam_mag_dir, f"latent_{str(frame_num).zfill(4)}.tif")
            # Pass mono_active and black_clipdown to the stacking sequence
            cutil.process_and_stack_latent_image(buf_f, out_f, tiff_flag, st['cg'], mono_active, black_clip)

    task = job_data.get('type')
    
    if task == 'preview':
        # Pass is_preview=True to get the dark gray background
        render_dual_world(float(job_data.get('probe_frame', 1)), float(job_data.get('probe_sub', 0.5)), is_preview=True)
        ctx.finish()
        
        raw_bytes = ctx.screen.read(components=4)
        img_data = np.frombuffer(raw_bytes, dtype=np.uint8).reshape((HEIGHT, WIDTH, 4))
        img_data = cv2.flip(img_data, 0)
        img_data = cv2.cvtColor(img_data, cv2.COLOR_RGBA2BGR)
        
        out_file = os.path.join(static_dir, "probe_live.jpg")
        cv2.imwrite(out_file, img_data)
        
        pygame.display.flip()
        
    elif task == 'cam_preview':
        execute_exposure(float(job_data.get('probe_frame', 1)), is_preview=True)
    
    elif task == 'measure_noise':
        # Grab exposure time based on the current Probe frame
        probe_f = float(job_data.get('probe_frame', 1))
        st = timeline.get_state(probe_f)
        smr_ms = float(st['exp']) * 1000.0
        total_ms = smr_ms + 1000.0

        log_audit(f"Measuring Noise Floor | Simulating Frame {probe_f} ({total_ms}ms)")

        # Force pure black to the screen
        ctx.screen.use()
        ctx.clear(0.0, 0.0, 0.0, 1.0)
        pygame.display.flip()

        buf_f = "/tmp/vop_noise_buf.dng"
        cam_proc = hw.trigger_capture(buf_f, total_ms + 700.0, job_data.get('gain', 1.0),
                                      job_data.get('awb_r', 1.0), job_data.get('awb_b', 1.0),
                                      job_data.get('cam_res', '2028x1520'))
        
        hw.wait_for_sensor_prime()
        time.sleep(total_ms / 1000.0) # Wait out the physical exposure time
        cam_proc.wait()

        # Analyze the result
        noise_val = cutil.measure_noise_floor(buf_f, static_dir)
        log_audit(f">>> RECOMMENDED BLACK CLIP: {noise_val:.6f} <<<")

    elif task == 'execute':
        # Fix: Ensure we are calculating based on actual frame count, not frame index
        frames = sorted(list(set([k['f'] for k in timeline.tracks['pos']])))
        if frames:
            f_start, f_end = int(min(frames)), int(max(frames))
            total_frames = f_end - f_start + 1
            start_t = time.time()
            total_size_bytes = 0
            files_found = 0
            
            # --- INITIAL HEARTBEAT BEFORE LOOP ---
            with open("/tmp/vop_heartbeat", "w") as hbf:
                json.dump({
                    "current": 0,
                    "total": total_frames,
                    "eta": 0,
                    "est_mb": 0.0,
                    "msg": "PRIMING SENSOR..."
                }, hbf)

            for f in range(f_start, f_end + 1):
                execute_exposure(f)
                done = f - f_start + 1

                # 1. Time Estimation (Remaining)
                elapsed = time.time() - start_t
                avg_time = elapsed / done
                eta_sec = int(avg_time * (total_frames - done))

                # 2. File Size Estimation (Total Project Size)
                out_f = os.path.join(cam_mag_dir, f"latent_{str(f).zfill(4)}.tif")
                if os.path.exists(out_f):
                    total_size_bytes += os.path.getsize(out_f)
                    files_found += 1
                
                # Calculate avg based only on files we've successfully measured
                avg_size = total_size_bytes / max(1, files_found)
                # We project the total final size of the whole job
                total_proj_est_mb = (avg_size * total_frames) / (1024 * 1024)

                with open("/tmp/vop_heartbeat", "w") as hbf:
                    json.dump({
                        "current": done,        # Proper 0-100% progress
                        "total": total_frames,
                        "eta": eta_sec,
                        "est_mb": round(total_proj_est_mb, 1),
                        "msg": "EXPOSING"
                    }, hbf)

            # --- POST-PROCESS: GENERATE WORKPRINT MP4 ---
            # Once the frame sequence is fully written to disk, we wrap the TIFFs into a h.264 mp4.
            ts = int(time.time())
            out_mp4 = os.path.join(wp_dir, f"vop_wp_{ts}.mp4")

            # We use the 'glob' pattern type to gather all exposures in the CamMag directory.
            # libx264 + yuv420p ensures the resulting video is playable in all modern browsers.
            ffmpeg_cmd = [
                "ffmpeg", "-y",
                "-framerate", str(job_data.get('fps', 24)),
                "-pattern_type", "glob", "-i", os.path.join(cam_mag_dir, "*.tif"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p",
                out_mp4
            ]
            log_audit(f"Creating Workprint: {out_mp4}")
            subprocess.run(ffmpeg_cmd)
    tex_mgr.release()
    pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    try:
        run_vop_engine(parser.parse_args().job)
    except Exception as e:
        log_audit(f"CRITICAL ENGINE FAILURE: {e}")
        traceback.print_exc()
        sys.exit(1)