"""
VOP Module:     engine.py
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
import traceback
import signal
import datetime

import interpolator
import vop_math as vmath
import camera_hardware as hw
import color_utils as cutil
import graphics_utils as gfx

# Force Pygame to bypass X11 and use the hardware framebuffer directly
os.environ["SDL_VIDEODRIVER"] = "kmsdrm"

# The IPC command file written by vop.py
COMMAND_FILE = "/tmp/vop_cmd.json"

def handle_sigterm(signum, frame):
    """
    Catches the Kill signal (sent when the VOP service restarts or stops).
    Gracefully releases the DRM master so the terminal/OS can have the screen back.
    """
    log_audit("Caught SIGTERM! Releasing KMSDRM hardware lock...")
    pygame.quit()
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)

def log_audit(msg): 
    print(f"[{time.strftime('%H:%M:%S')}] AUDIT (v0.2.6): {msg}", flush=True)

def validate_black_clip(raw_clip):
    """
    Coerces and sanity-checks the noise crusher input.

    Returns a float in the range [0.0-1.0]. Anything <=0 disables the crusher.
    Values >= 1.0 would crush the entire 16-bit range to black, so we refusee
    them and warn loudly. This is a guardrail against the classic "missing
    decimal point"  pasted-value mistake (e.g. typing 003704 instead of 0.003704
    yields 3704.0 which silently nukes every captured photo to pure black)
    """
    try:
        val = float(raw_clip) if raw_clip != "" else 0.0
    
    except (TypeError, ValueError):
        log_audit(f"WARNING: Nosie Crusher value {val} is unreasonable (must be 0.0 - 1.0). "
                  f"Did you mayhaps forget the leading decimal? Disabling crusher for this"
                  f"exposure.")
        return 0.0
    if val < 0.0
        log_audit(f"WARNING: Noise Crusher value {val} is negative. Treating as 0.0.")
        return 0.0
    
    return val

def run_persistent_engine():
    """
    Main loop for the persistent GPU engine. It acquires the hardware lock once 
    at boot, runs the idle animation continuously, and polls for IPC commands.
    """
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    static_dir = os.path.join(base_path, "static")
    cam_mag_dir = os.path.join(base_path, "CamMag")
    wp_dir = os.path.join(base_path, "WorkPrints")
    
    log_audit("Engine Starting | Mode: PERSISTENT IPC DAEMON")

    pygame.init()
    pygame.mouse.set_visible(False)
    
    # Force GLES 3.0 profile for Pi 4 VideoCore VI compatibility
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_ES)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
    pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 0)
    
    WIDTH, HEIGHT = 1920, 1080
    
    # ---------------------------------------------------------
    # PERSISTENT HARDWARE INITIALIZATION
    # We grab the KMSDRM lock here once. We never let it go.
    # ---------------------------------------------------------
    try:
        screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
    except pygame.error:
        log_audit("Hardware busy, retrying KMSDRM lock in 1s...")
        time.sleep(1.0)
        screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
    
    ctx, prog, vao = gfx.init_render_pipeline()

    # Pre-allocate an off-screen Framebuffer Object (FBO) for the BiPack mask.
    # This persists in GPU memory for the entire lifecycle of the daemon.
    bp_tex = ctx.texture((WIDTH, HEIGHT), 4)
    bp_fbo = ctx.framebuffer(color_attachments=[bp_tex])

    # ---------------------------------------------------------
    # IDLE SCREEN ASSET SETUP
    # Load the logo into VRAM once at boot to save CPU cycles later
    # ---------------------------------------------------------
    img_path = os.path.join(base_path, "graphics", "branding.png")
    if not os.path.exists(img_path):
        log_audit(f"Missing branding.png at {img_path}")
        sys.exit(1)
        
    logo_surface = pygame.image.load(img_path).convert_alpha()
    logo_surface = pygame.transform.flip(logo_surface, False, True)
    logo_data = pygame.image.tostring(logo_surface, "RGBA", False)
    logo_w, logo_h = logo_surface.get_size()
    
    tex_logo = ctx.texture((logo_w, logo_h), 4, logo_data)
    asp_logo = logo_w / logo_h
    
    # Starting vectors for the bouncing logo
    idle_x, idle_y = 0.0, 0.37
    idle_dx, idle_dy = 0.00225, 0.00215

    # ---------------------------------------------------------
    # MAIN IPC LOOP
    # ---------------------------------------------------------
    while True:
        # Mandatory housekeeping to prevent underlying SDL2 queue overflow (CPU 100% lockup)
        pygame.event.pump()

        # Check if vop.py has dispatched a new command
        if os.path.exists(COMMAND_FILE):
            try:
                with open(COMMAND_FILE, 'r') as f:
                    job_data = json.load(f)
            except json.JSONDecodeError:
                # Catch partial file writes. The next frame (16ms later) will read it successfully.
                time.sleep(0.016)
                continue

            task = job_data.get('type')

            if task == 'panic':
                log_audit("Panic received. Flushing command and returning to idle.")
                os.remove(COMMAND_FILE)
                continue

            log_audit(f"IPC Command Received: {task.upper()}")

            # ---------------------------------------------------------
            # JOB STATE HYDRATION
            # Hydrate the timeline and texture manager for this specific task
            # ---------------------------------------------------------
            timeline = interpolator.Timeline(job_data)
            tex_mgr = gfx.TextureManager(ctx, os.path.join(base_path, "ProjMag"), job_data)

            mono_active = (job_data.get('mono_mode') == True)
            prog['mono_mode'].value = mono_active

            mag_scale = float(job_data.get('coord_scale', 1.0))
            bp_scale = float(job_data.get('bipack_coord_scale', 1.0))

            # Announce rendering state to the UI via the heartbeat file
            with open("/tmp/vop_heartbeat", "w") as hbf:
                json.dump({"status": "rendering", "msg": f"Starting {task}...", "current": 0, "total": 1, "eta": 0, "est_mb": 0.0}, hbf)

            # ---------------------------------------------------------
            # NESTED RENDER FUNCTIONS
            # Defined inside the execution block so they securely inherit 
            # the current job_data, timeline, and tex_mgr states.
            # ---------------------------------------------------------
            def render_dual_world(frame_num, t_norm, is_preview=False):
                if timeline.mode == 'mds':
                    st = timeline.get_mds_state(float(frame_num), t_norm)
                else:
                    st_base = timeline.get_state(frame_num)
                    t_start = frame_num - (st_base['sd'] * st_base['ph'])
                    t_end = frame_num + (st_base['sd'] * (1.0 - st_base['ph']))
                    st = timeline.get_state(t_start + (t_end - t_start) * t_norm)

                # Resolve playhead positions independently for each optical layer.
                # The ProjMag and BiPack run on separate JK printer tracks - so a job
                # could, for example, hold the projmag still while reverse running the
                # bipack, just like a real optical printer's two independently-clocked
                # magazine heads.
                ph_pm = timeline.calculate_playhead_at(frame_num, layer='pm')
                ph_bp = timeline.calculate_playhead_at(frame_num, layer='bp')

                tex_mag, asp_mag = tex_mgr.load(ph_pm, is_bipack=False)
                tex_bp,  asp_bp  = tex_mgr.load(ph_bp, is_bipack=True)

                bg_color = (0.1, 0.1, 0.1, 1.0) if is_preview else (0.0, 0.0, 0.0, 1.0)
                
                # PASS 1: RENDER BIPACK INTO OFF-SCREEN FBO
                bp_fbo.use()
                if tex_bp == tex_mgr.white_tex:
                    bp_fbo.clear(1.0, 1.0, 1.0, 1.0)
                else:
                    bp_fbo.clear(0.0, 0.0, 0.0, 1.0)
                    mvp_bp = vmath.get_frustum_fit_matrix(float(job_data.get('fov', 45)), asp_bp, bp_scale, 
                                                        st['bp_p'], st['bp_r'], st['lbp_p'], st['lbp_r'], WIDTH, HEIGHT)
                    prog['mvp'].write(mvp_bp)
                    prog['filter_color'].write(np.array([1.0, 1.0, 1.0], dtype='f4'))
                    tex_bp.use(0)
                    vao.render(moderngl.TRIANGLE_STRIP)

                # PASS 2: RENDER MAG TO THE ACTUAL SCREEN
                ctx.screen.use()
                ctx.clear(*bg_color)
                if tex_mag == tex_mgr.white_tex:
                    mvp_mag = np.eye(4, dtype='f4').tobytes()
                else:
                    mvp_mag = vmath.get_frustum_fit_matrix(float(job_data.get('fov', 45)), asp_mag, mag_scale,
                                                        st['p'], st['r'], st['lp'], st['lr'], WIDTH, HEIGHT)
                
                prog['mvp'].write(mvp_mag)
                prog['filter_color'].write(st['pg'].astype('f4'))
                tex_mag.use(0)
                vao.render(moderngl.TRIANGLE_STRIP)
                
                # PASS 3: MULTIPLY THE FBO OVER THE SCREEN
                ctx.enable(moderngl.BLEND)
                ctx.blend_func = (moderngl.DST_COLOR, moderngl.ZERO)
                prog['mvp'].write(np.eye(4, dtype='f4').tobytes())
                prog['filter_color'].write(np.array([1.0, 1.0, 1.0], dtype='f4'))
                bp_tex.use(0)
                vao.render(moderngl.TRIANGLE_STRIP)
                ctx.disable(moderngl.BLEND)

            def execute_exposure(frame_num, is_preview=False):
                st = timeline.get_state(frame_num)
                smr_ms = float(st['exp']) * 1000.0
                total_ms = smr_ms + 1000.0
                
                black_clip = validate_black_clip(job_data.get('black_clip', 0.0))

                buf_f = f"/tmp/vop_buf_{frame_num}.dng" if not is_preview else "/tmp/vop_prev_buf.dng"
                # ---------------------------------------------------------
                # VRAM PRE-CACHING
                # Execute disk I/O and allocate textures into GPU memory 
                # before the precision hardware timing loop begins. This prevents
                # the main thread from stalling during the first frame render.
                # ---------------------------------------------------------

                ph_pm = timeline.calculate_playhead_at(frame_num, layer='pm')
                ph_bp = timeline.calculate_playhead_at(frame_num, layer='bp')
                tex_mgr.load(ph_pm, is_bipack=False)
                tex_mgr.load(ph_bp, is_bipack=True)

                # ---------------------------------------------------------
                # PRE-EXPOSURE BLACKOUT
                # Force the GPU to dump the idle screen and push pure black to the 
                # HDMI monitor. This guarantees the physical room is dark before 
                # the camera sensor powers up and opens its shutter.
                # ---------------------------------------------------------
                ctx.screen.use()
                ctx.clear(0.0, 0.0, 0.0, 1.0)
                ctx.finish()
                pygame.display.flip()
                
                t_trigger = time.time()
                log_audit(f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] EXPOSURE {frame_num} | Triggering libcamera")
                
                cam_proc = hw.trigger_capture(buf_f, total_ms , job_data.get('gain', 1.0), 
                                              job_data.get('awb_r', 1.0), job_data.get('awb_b', 1.0), job_data.get('cam_res','2028x1520'))
                
                hw.wait_for_sensor_prime()

                anchor = time.time()
                boot_delay = (anchor - t_trigger) * 1000
                log_audit(f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] EXPOSURE {frame_num} | Wait complete. Boot delay: {boot_delay:.1f}ms")
                log_audit(f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] EXPOSURE {frame_num} | Starting HDMI sequence (500ms pre-roll)")

                frame_rendered = False

                while (time.time() - anchor) * 1000 < total_ms:
                    pygame.event.pump()
                    elapsed = (time.time() - anchor) * 1000

                    in_window = 500.0 <= elapsed <= (500.0 + smr_ms)
                    missed_window = (elapsed > 500.0) and not frame_rendered

                    if in_window or missed_window:
                        if not frame_rendered:
                             log_audit(f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] EXPOSURE {frame_num} | First image frame rendered at {elapsed:.1f}ms")

                        clamped_elapsed = min(elapsed, 500.0 + smr_ms)
                        t_norm = (clamped_elapsed - 500.0) / max(1.0, smr_ms)
                        render_dual_world(frame_num, t_norm, is_preview=False)
                        frame_rendered = True
                    else:
                        # OPTICAL SHUTTER ENFORCEMENT
                        # Draw a physical black quad to force the GPU to swap the buffer
                        ctx.screen.use()
                        ctx.clear(0.0, 0.0, 0.0, 1.0)
                        prog['mvp'].write(np.eye(4, dtype='f4').tobytes())
                        prog['filter_color'].write(np.array([0.0, 0.0, 0.0], dtype='f4'))
                        tex_mgr.white_tex.use(0)
                        vao.render(moderngl.TRIANGLE_STRIP)

                    ctx.finish()  
                    pygame.display.flip()
                
                # ---------------------------------------------------------
                # POST-EXPOSURE BLACKOUT
                # Guarantee the screen drops to black by forcing geometry
                # ---------------------------------------------------------
                ctx.screen.use()
                ctx.clear(0.0, 0.0, 0.0, 1.0)
                prog['mvp'].write(np.eye(4, dtype='f4').tobytes())
                prog['filter_color'].write(np.array([0.0, 0.0, 0.0], dtype='f4'))
                tex_mgr.white_tex.use(0)
                vao.render(moderngl.TRIANGLE_STRIP)
                ctx.finish()
                pygame.display.flip()
                # ---------------------------------------------------------
                
                log_audit(f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] EXPOSURE {frame_num} | HDMI sequence complete. Waiting for camera file IO.")
                cam_proc.wait()
                
                if is_preview:
                    cutil.generate_sensor_preview(buf_f, static_dir, st['cg'], mono_active, black_clip)
                else:
                    tiff_flag = 8 if job_data.get('tiff_compression') == 'zip' else 1
                    out_f = os.path.join(cam_mag_dir, f"latent_{str(frame_num).zfill(4)}.tif")
                    cutil.process_and_stack_latent_image(buf_f, static_dir, out_f, tiff_flag, st['cg'], mono_active, black_clip)

            # ---------------------------------------------------------
            # TASK ROUTING & EXECUTION
            # ---------------------------------------------------------
            try:
                if task == 'preview':
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
                    probe_f = float(job_data.get('probe_frame', 1))
                    st = timeline.get_state(probe_f)
                    smr_ms = float(st['exp']) * 1000.0
                    total_ms = smr_ms + 1000.0

                    log_audit(f"Measuring Noise Floor | Simulating Frame {probe_f} ({total_ms}ms)")

                    ctx.screen.use()
                    ctx.clear(0.0, 0.0, 0.0, 1.0)
                    pygame.display.flip()

                    buf_f = "/tmp/vop_noise_buf.dng"
                    cam_proc = hw.trigger_capture(buf_f, total_ms + hw.PRIME_WAIT_MS, job_data.get('gain', 1.0),
                                                  job_data.get('awb_r', 1.0), job_data.get('awb_b', 1.0),
                                                  job_data.get('cam_res', '2028x1520'))
                    hw.wait_for_sensor_prime()
                    time.sleep(total_ms / 1000.0) 
                    cam_proc.wait()

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

                elif task == 'execute':
                    frames = sorted({k['f'] for k in timeline.tracks['pos']})
                    if frames:
                        f_start, f_end = int(min(frames)), int(max(frames))
                        total_frames = f_end - f_start + 1
                        start_t = time.time()
                        total_size_bytes = 0
                        files_found = 0
                        
                        with open("/tmp/vop_heartbeat", "w") as hbf:
                            json.dump({
                                "current": 0, "total": total_frames, "eta": 0, "est_mb": 0.0, "msg": "PRIMING SENSOR..."
                            }, hbf)

                        for f in range(f_start, f_end + 1):
                            execute_exposure(f)
                            done = f - f_start + 1

                            elapsed = time.time() - start_t
                            avg_time = elapsed / done
                            eta_sec = int(avg_time * (total_frames - done))

                            out_f = os.path.join(cam_mag_dir, f"latent_{str(f).zfill(4)}.tif")
                            if os.path.exists(out_f):
                                total_size_bytes += os.path.getsize(out_f)
                                files_found += 1
                            
                            avg_size = total_size_bytes / max(1, files_found)
                            total_proj_est_mb = (avg_size * total_frames) / (1024 * 1024)

                            with open("/tmp/vop_heartbeat", "w") as hbf:
                                json.dump({
                                    "current": done, "total": total_frames, "eta": eta_sec, "est_mb": round(total_proj_est_mb, 1), "msg": "EXPOSING"
                                }, hbf)

                        ts = int(time.time())
                        out_mp4 = os.path.join(wp_dir, f"vop_wp_{ts}.mp4")

                        ffmpeg_cmd = [
                            "ffmpeg", "-y", "-framerate", str(job_data.get('fps', 24)),
                            "-pattern_type", "glob", "-i", os.path.join(cam_mag_dir, "*.tif"),
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", out_mp4
                        ]
                        log_audit(f"Creating Workprint: {out_mp4}")
                        subprocess.run(ffmpeg_cmd)

                elif task == 'lab_invert':
                    log_audit("Starting LAB/INVERT on CamMag")
                    tiffs = sorted([f for f in os.listdir(cam_mag_dir) if f.endswith(".tif")])
                    total_frames = len(tiffs)

                    if total_frames > 0:
                        tiff_flag = 8 if job_data.get('tiff_compression') == 'zip' else 1
                        start_t = time.time()

                        for i, f in enumerate(tiffs):
                            filepath = os.path.join(cam_mag_dir, f)
                            img = cv2.imread(filepath, cv2.IMREAD_UNCHANGED)
                            if img is not None and img.dtype == np.uint16:
                                inverted = 65535 - img
                                cv2.imwrite(filepath, inverted, [cv2.IMWRITE_TIFF_COMPRESSION, tiff_flag])
                            
                            elapsed = time.time() - start_t
                            done = i + 1
                            avg_time = elapsed / done
                            eta_sec = int(avg_time* (total_frames - done))

                            with open("/tmp/vop_heartbeat", "w") as hbf:
                                json.dump({
                                    "current": done, "total": total_frames, "eta": eta_sec, "est_mb": 0.0, "msg": "Processing LAB/INVERT"
                                }, hbf)
                        
                        log_audit(f"LAB/INVERT Complete: Processed {total_frames} frames.")
                    else:
                        log_audit("LAB/INVERT aborted: No frames found in CamMag.")

            except Exception as e:
                log_audit(f"CRITICAL ERROR during {task.upper()}: {e}")
                traceback.print_exc()
            
            # ---------------------------------------------------------
            # TASK CLEANUP
            # ---------------------------------------------------------
            tex_mgr.release() # Free system RAM and VRAM utilized by the specific job
            os.remove(COMMAND_FILE) # Signal vop.py that the block is clear
            log_audit(f"Task {task.upper()} Complete. Returning to Idle.")

        else:
            # ---------------------------------------------------------
            # DEFAULT FALLBACK: HARDWARE IDLE SCREEN
            # Executes cleanly at 60fps if no command file is present
            # ---------------------------------------------------------
            idle_x += idle_dx
            idle_y += idle_dy
            
            if idle_x <= -0.8 or idle_x >= 0.8: idle_dx *= -1
            if idle_y <= -0.8 or idle_y >= 0.8: idle_dy *= -1

            ctx.screen.use()
            ctx.clear(0.0, 0.0, 0.0, 1.0)

            mvp = np.eye(4, dtype='f4')
            mvp[0, 0] = 0.4 * asp_logo / (1920/1080)
            mvp[1, 1] = 0.4
            mvp[3, 0] = idle_x
            mvp[3, 1] = idle_y

            prog['mvp'].write(mvp.tobytes())
            prog['filter_color'].write(np.array([1.0, 1.0, 1.0], dtype='f4'))
            
            # Ensure the idle logo is never subjected to a user's monochrome job setting
            prog['mono_mode'].value = False 

            tex_logo.use(0)
            vao.render(moderngl.TRIANGLE_STRIP)

            pygame.display.flip()
            time.sleep(1 / 60) # Hardware throttle to prevent locking up the Pi 4

if __name__ == "__main__":
    # The script no longer requires the --job flag, as it boots blindly and waits for IPC data.
    try:
        run_persistent_engine()
    except Exception as e:
        log_audit(f"FATAL DAEMON CRASH: {e}")
        traceback.print_exc()
    finally:
        # Failsafe KMSDRM release
        pygame.quit()
        sys.exit(1)