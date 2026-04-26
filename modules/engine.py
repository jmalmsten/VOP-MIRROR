"""
VOP Module:     engine.py
Version:        v0.1.9
Description:    Multiplicative Dual-World Engine.
                Forces GLES 3.0 profile prior to display initialization.
                Added contextual dark gray background for UI previews to visualize frustum bounds.
"""
#
###########################################################################
#
#                                   VOP
#                       Copyright (C) 2025  jmalmsten
#
#     This program is free software: you can redistribute it and/or modify 
#     it under the terms of the GNU Affero General Public License as 
#     published by the Free Software Foundation, either version 3 of the 
#     License, or (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful, but 
#     WITHOUT ANY WARRANTY; without even the implied warranty of 
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU 
#     Affero General Public License for more details.
#
#     You should have received a copy of the GNU Affero General Public 
#     License along with this program.  If not, see 
#     <http://www.gnu.org/licenses/>.
#
#     Source code for this application can be found at 
#     https://codeberg.org/jmalmsten-com/VOP
#
###########################################################################


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
import signal

os.environ["SDL_VIDEODRIVER"] = "kmsdrm"

def handle_sigterm(signum, frame):
    """Catches the Panic/Kill signal and gracefully releases the DRM master"""
    log_audit("Caught SIGTERM! Releasing KMSDRM hardware lock...")
    pygame.quit()
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)

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
    
    # Hardware Init: Aggressive KMSDRM lock acquisition
    WIDTH, HEIGHT = 1920, 1080
    
    try:
        # Attempt 1: Standard grab of the DRM master lock
        screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
    except pygame.error:
        # If the idle screen hasn't fully released the lock, wait and try a "Hail Mary"
        log_audit("Hardware busy, retrying KMSDRM lock in 1s...")
        time.sleep(1.0)
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
        
        raw_clip = job_data.get('black_clip', 0.0)
        black_clip = float(raw_clip) if raw_clip != "" else 0.0

        log_audit(f"Exposing Frame {frame_num} | Smear: {smr_ms}ms | Shutter Total: {total_ms}ms")
        
        buf_f = f"/tmp/vop_buf_{frame_num}.dng" if not is_preview else "/tmp/vop_prev_buf.dng"
        
        cam_proc = hw.trigger_capture(buf_f, total_ms + hw.PRIME_WAIT_MS, job_data.get('gain', 1.0), 
                                    job_data.get('awb_r', 1.0), job_data.get('awb_b', 1.0), job_data.get('cam_res','2028x1520'))
        
        hw.wait_for_sensor_prime()

        anchor = time.time()
        frame_rendered = False  # Safety net for sub-VSync smear durations

        while (time.time() - anchor) * 1000 < total_ms:
            pygame.event.pump()
            elapsed = (time.time() - anchor) * 1000

            in_window = 500.0 <= elapsed <= (500.0 + smr_ms)
            missed_window = (elapsed > 500.0) and not frame_rendered

            if in_window or missed_window:
                clamped_elapsed = min(elapsed, 500.0 + smr_ms)
                t_norm = (clamped_elapsed - 500.0) / max(1.0, smr_ms)
                render_dual_world(frame_num, t_norm, is_preview=False)
                frame_rendered = True
            else:
                ctx.clear(0.0, 0.0, 0.0, 1.0)

            ctx.finish()  # Flush GPU before swap — ensures camera sees rendered frame, not stale buffer
            pygame.display.flip()
        
        cam_proc.wait()
        
        if is_preview:
            cutil.generate_sensor_preview(buf_f, static_dir, st['cg'], mono_active, black_clip)
        else:
            tiff_flag = 8 if job_data.get('tiff_compression') == 'zip' else 1
            out_f = os.path.join(cam_mag_dir, f"latent_{str(frame_num).zfill(4)}.tif")
            cutil.process_and_stack_latent_image(buf_f, static_dir, out_f, tiff_flag, st['cg'], mono_active, black_clip)

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
        cam_proc = hw.trigger_capture(buf_f, total_ms + hw.PRIME_WAIT_MS, job_data.get('gain', 1.0),
                                      job_data.get('awb_r', 1.0), job_data.get('awb_b', 1.0),
                                      job_data.get('cam_res', '2028x1520'))
        
        hw.wait_for_sensor_prime()
        time.sleep(total_ms / 1000.0) # Wait out the physical exposure time
        cam_proc.wait()

        # Analyze the result
        noise_val = cutil.measure_noise_floor(buf_f, static_dir)
        log_audit(f">>> RECOMMENDED BLACK CLIP: {noise_val:.6f} <<<")
    
    elif task == 'map_hot_pixels':
        probe_f = float(job_data.get('probe_frame', 1))
        st = timeline.get_state(probe_f)
        smr_ms = float(st['exp']) * 1000.0
        total_ms = smr_ms + 1000.0

        log_audit(f"Mapping Hot Pixels | Frame {probe_f} ({total_ms}ms)")

        ctx.screen.use()
        ctx.clear(0.0, 0.0, 0.0, 1.0)
        pygame.display.flip()

        buf_f = "/tmp/vop_hp_buf.dng"
        cam_proc = hw.trigger_capture(buf_f, total_ms + hw.PRIME_WAIT_MS, job_data.get('gain', 1.0),
                                      job_data.get('awb_r', 1.0), job_data.get('awb_b', 1.0),
                                      job_data.get('cam_res', '2028x1520'))
        
        hw.wait_for_sensor_prime()
        time.sleep(total_ms /1000.0)
        cam_proc.wait()
        
        hp_count = cutil.map_hot_pixels(buf_f, static_dir)
        if hp_count >= 0:
            log_audit(f">>> MAPPED {hp_count} HOT PIXELS <<<")
        else:
            log_audit(f">>> LENS CAP CHECK FAILED. ABORTED. <<<")

    elif task == 'idle':
        log_audit("Entering Hardware-Accelerated Idle Mode")

        img_path = os.path.join(base_path, "graphics", "branding.png")
        if not os.path.exists(img_path):
            log_audit(f"Missing branding.png at {img_path}")
            sys.exit(1)
        
        # Load image and flip vertically (ModernGL expects the origin at the bottom-left)
        logo_surface = pygame.image.load(img_path).convert_alpha()
        logo_surface= pygame.transform.flip(logo_surface, False, True)
        logo_data = pygame.image.tostring(logo_surface, "RGBA", False)

        logo_w, logo_h = logo_surface.get_size()
        tex_logo = ctx.texture((logo_w, logo_h), 4, logo_data)

        asp_logo = logo_w / logo_h
        x, y = 0.0, 0.37
        dx, dy = 0.00125, 0.00115

        running = True
        while running:
            # Prevent Pi CPU lockup
            pygame.event.pump()

            x += dx
            y += dy
            if x <= -0.8 or x >= 0.8: dx *= -1
            if y <= -0.8 or y >= 0.8: dy *= -1

            ctx.screen.use()
            ctx.clear(0.0, 0.0, 0.0, 1.0)

            # Construct a basic translation & scale matrix for 2D orthographic mapping
            mvp = np.eye(4, dtype='f4')
            mvp[0, 0] = 0.4 * asp_logo / (1920/1080)    # Scale X and maintain aspect ratio
            mvp[1, 1] = 0.4                             # Scale y
            mvp[3, 0] = x                               # Translate X
            mvp[3, 1] = y                               # Translate y

            prog['mvp'].write(mvp.tobytes())
            prog['filter_color'].write(np.array([1.0, 1.0, 1.0], dtype='f4'))
            tex_logo.use(0)
            vao.render(moderngl.TRIANGLE_STRIP)

            pygame.display.flip()
            time.sleep(1 / 60) # Cap at 60 fps - prevents CPU lockup and runaway speed

    elif task == 'execute':
        # Fix: Ensure we are calculating based on actual frame count, not frame index
        frames = sorted({k['f'] for k in timeline.tracks['pos']})
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
    elif task == 'lab_invert':
        # --- LAB/INVERT Task: Processes all latent frames into negative colors
        log_audit("Starting LAB/INVERT on CamMag")

        # Grab all TIFFs in the CamMag directory and sort them sequentially
        tiffs = sorted([f for f in os.listdir(cam_mag_dir) if f.endswith(".tif")])
        total_frames = len(tiffs)

        if total_frames > 0:
            # Respect the user's compression preference from the current job state
            tiff_flag = 8 if job_data.get('tiff_compression') == 'zip' else 1
            start_t = time.time()

            for i, f in enumerate(tiffs):
                filepath = os.path.join(cam_mag_dir, f)

                # Load the frame natively as a 16-bit unsigned integer array
                img = cv2.imread(filepath, cv2.IMREAD_UNCHANGED)
                if img is not None and img.dtype == np.uint16:
                    # Mathematical Inversion: 65535 is the absolute peak of 16-bit linear space.
                    # Subtracting the pixel value from peak inverts the linear curve.
                    inverted = 65535 - img

                    # Overwrite the original file with the inverted array
                    cv2.imwrite(filepath, inverted, [cv2.IMWRITE_TIFF_COMPRESSION, tiff_flag])
                
                # Calculate time estimation for the UI heartbeat
                elapsed = time.time() - start_t
                done = i + 1
                avg_time = elapsed / done
                eta_sec = int(avg_time* (total_frames - done))

                # Update the heartbeat file so the web UI progress bar advances
                with open("/tmp/vop_heartbeat", "w") as hbf:
                    json.dump({
                        "current": done,
                        "total": total_frames,
                        "eta": eta_sec, 
                        "est_mb": 0.0, # Not actively generating new file sizes here
                        "msg": "Processing LAB/INVERT"
                    }, hbf)
            
            log_audit(f"LAB/INVERT Complete: Processed {total_frames} frames.")
        else:
            log_audit("LAB/INVERT aborted: No frames found in CamMag.")

    tex_mgr.release()
    pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", required=True)
    exit_code = 1 # Assume failure unless we succeed
    try:
        run_vop_engine(parser.parse_args().job)
        exit_code = 0 # engine completed without throwing
    except Exception as e:
        log_audit(f"CRITICAL ENGINE FAILURE: {e}")
        traceback.print_exc()
    finally:
        # This guarantees the hardware DRM lock is released no matter what happens
        pygame.quit()
        sys.exit(exit_code)