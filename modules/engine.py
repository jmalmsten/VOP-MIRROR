""" 
VOP Module:     engine.py
Description:    Multiplicative Multi-Layer Engine.
                Forces GLES 3.0 profile prior to display initialization.
                Added contextual dark gray background for UI previews to visualize frustum bounds.
                Expanded from 2-layer (PM+BP) to 3-layer (PM+BP1+BP2) compositing (v0.8.0).
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
    Values >= 1.0 would crush the entire 16-bit range to black, so we refuse
    them and warn loudly. This is a guardrail against the classic "missing
    decimal point" pasted-value mistake (e.g. typing 003704 instead of 0.003704
    yields 3704.0 which silently nukes every captured photo to pure black)
    
    Also writes a flag file the GUI polls, so the warning becomes visible 
    in the browser, not just the terminal.
    """
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    warn_file = os.path.join(base_path, "static", "validation_warning.json")
    
    def emit_warning(message):
        log_audit(message)
        try:
            with open(warn_file, "w") as f:
                json.dump({"field": "black_clip", "message": message, "forced_value": 0.0, "ts": time.time()}, f)
        except Exception as e:
            log_audit(f"WARNING: could not write validation flag file: {e}")
    
    try:
        val = float(raw_clip) if raw_clip != "" else 0.0
    except (TypeError, ValueError):
        emit_warning(f"Noise Crusher value '{raw_clip}' is not a number. Forcing to 0.0.")
        return 0.0
    
    if val >= 1.0:
        emit_warning(f"Noise Crusher value {val} is unreasonable (must be 0.0-1.0). Did you forget the leading decimal? Forcing to 0.0.")
        return 0.0
    
    if val < 0.0:
        emit_warning(f"Noise Crusher value {val} is negative. Forcing to 0.0.")
        return 0.0
    
    # Valid input: clear any stale warning file so the GUI doesn't keep showing 
    # a previous warning for a now-corrected value.
    if os.path.exists(warn_file):
        try:
            os.remove(warn_file)
        except Exception:
            pass
    
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

    # Pre-allocate off-screen Framebuffer Objects (FBOs) for the BiPack masks.
    # One FBO per bipack layer so they render independently before being
    # multiplicatively composited over the PM screen pass. Both persist in 
    # GPU memory for the entire lifecycle of the daemon - allocating them 
    # once at boot rather than per-job avoids fragmentation and GL state churn.
    # 
    # Memory cost is ~8 MB per FBO at 1920x1080 RGBA, well within the Pi 4's 
    # VRAM budget. Adding a third layer's FBO is therefore a near-free change.
    bp1_tex = ctx.texture((WIDTH, HEIGHT), 4)
    bp1_fbo = ctx.framebuffer(color_attachments=[bp1_tex])
    bp2_tex = ctx.texture((WIDTH, HEIGHT), 4)
    bp2_fbo = ctx.framebuffer(color_attachments=[bp2_tex])

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
            # Per-bipack-layer world scales. The PM key 'coord_scale' is 
            # unchanged for backward compatibility. BP1 inherits the old 
            # 'bipack_coord_scale' name now suffixed to '1'; BP2 is new.
            bp1_scale = float(job_data.get('bipack1_coord_scale', 1.0))
            bp2_scale = float(job_data.get('bipack2_coord_scale', 1.0))

            # ---------------------------------------------------------
            # ANAMORPHIC PAR (Pixel Aspect Ratio) RESOLUTION
            # Read once per task to avoid redundant dict lookups during the
            # per-frame render loop. The preview-unsqueeze toggle is consumed
            # only by the Proj Probe path below; cam_preview unsqueezing is
            # done downstream in color_utils when we resample the JPG.
            # ---------------------------------------------------------
            par_x = float(job_data.get('par_x', 1.0) or 1.0)
            par_y = float(job_data.get('par_y', 1.0) or 1.0)
            preview_unsqueeze = bool(job_data.get('preview_unsqueeze', False))
            
            # Rotation order for Euler -> matrix composition. The string
            # is "XYZ", "ZYX", etc. — see vop_math.get_frustum_fit_matrix
            # for the full mapping. Default "XYZ" reproduces the original
            # hardcoded Z*Y*X behavior exactly, so jobs saved before this
            # feature existed render identically.
            rot_order = job_data.get('rot_order', 'XYZ')

            # Announce rendering state to the UI via the heartbeat file
            with open("/tmp/vop_heartbeat", "w") as hbf:
                json.dump({"status": "rendering", "msg": f"Starting {task}...", "current": 0, "total": 1, "eta": 0, "est_mb": 0.0}, hbf)

            # ---------------------------------------------------------
            # NESTED RENDER FUNCTIONS
            # Defined inside the execution block so they securely inherit 
            # the current job_data, timeline, and tex_mgr states.
            # ---------------------------------------------------------
            def render_world(frame_num, t_norm, is_preview=False):
                """
                Renders one composite frame to the HDMI screen.
                
                Three optical layers stack multiplicatively:
                  PASS 1: BP1 rendered into bp1_fbo
                  PASS 2: BP2 rendered into bp2_fbo
                  PASS 3: PM rendered to the screen
                  PASS 4: bp1_tex multiplied over the screen
                  PASS 5: bp2_tex multiplied over the screen
                
                Multiplication is commutative so the order of the two BP 
                blends doesn't affect output. PM always renders to screen 
                directly because the projector gel (PG) filter color is 
                applied to it - that's the bulb's tint, not a mask.
                """
                if timeline.mode == 'mds':
                    st = timeline.get_mds_state(float(frame_num), t_norm)
                else:
                    st_base = timeline.get_state(frame_num)
                    t_start = frame_num - (st_base['sd'] * st_base['ph'])
                    t_end = frame_num + (st_base['sd'] * (1.0 - st_base['ph']))
                    st = timeline.get_state(t_start + (t_end - t_start) * t_norm)

                # ANAMORPHIC PAR FOR THIS RENDER
                #
                # Always use the real job PAR, even for previews. We used to
                # force PAR=1.0 here when (is_preview and preview_unsqueeze)
                # so the 1920x1080 screen-grab would already look unsqueezed.
                # The trade-off was that at non-square PARs the rendered
                # geometry would overflow the screen edges, silently cropping
                # the preview - dishonest about what the eventual exposure
                # would look like.
                #
                # The Proj Probe path now does its own JPG-level unsqueeze
                # (via color_utils.unsqueeze_preview_jpg) followed by a
                # letterbox into a camera-shaped frame, mirroring the
                # post-processing pipeline of Cam View / Comp View / Cam
                # Probe. So we no longer need - or want - the render-time
                # override here.
                #
                # is_preview is still meaningful below: it controls the gray
                # frustum-bounds background color in the live HDMI render.
                render_par_x, render_par_y = par_x, par_y

                # Resolve playhead positions independently for each optical layer.
                # The PM and both BiPack reels run on separate JK printer tracks - 
                # a job could, for example, hold the PM still while reverse-running 
                # BP1 and forward-running BP2, just like a real optical printer's 
                # multiple independently-clocked magazine heads.
                ph_pm  = timeline.calculate_playhead_at(frame_num, layer='pm')
                ph_bp1 = timeline.calculate_playhead_at(frame_num, layer='bp1')
                ph_bp2 = timeline.calculate_playhead_at(frame_num, layer='bp2')

                tex_mag, asp_mag = tex_mgr.load(ph_pm,  layer='pm')
                tex_bp1, asp_bp1 = tex_mgr.load(ph_bp1, layer='bp1')
                tex_bp2, asp_bp2 = tex_mgr.load(ph_bp2, layer='bp2')
                
                # Layer visibility toggles (the "eye" icons next to the upload fields).
                # When a layer is hidden, swap its texture for the all-white texture.
                # The white_tex check inside each pass below handles this cleanly: 
                # the layer is rendered as pure pass-through, no geometry transform, 
                # no masking contribution. With all layers hidden, the user sees the 
                # bare bulb (still tintable via PG / CG).
                # Defaults to True (visible) so missing keys don't accidentally hide
                # layers in jobs created before this feature existed.
                if not job_data.get('pm_visible', True):
                    tex_mag = tex_mgr.white_tex
                if not job_data.get('bp1_visible', True):
                    tex_bp1 = tex_mgr.white_tex
                if not job_data.get('bp2_visible', True):
                    tex_bp2 = tex_mgr.white_tex
                    
                bg_color = (0.1, 0.1, 0.1, 1.0) if is_preview else (0.0, 0.0, 0.0, 1.0)

                def render_bipack_to_fbo(fbo, tex, asp, world_scale, mst_p, mst_r, lcl_p, lcl_r):
                    """
                    Renders one bipack layer into its dedicated off-screen FBO.
                    
                    If the layer's texture is the all-white pass-through (because 
                    the eye is closed or no source file exists), clear the FBO 
                    to white and skip the geometry pass entirely - that produces 
                    a true identity contribution under multiplication. Otherwise 
                    clear to black (so the unrendered border around the artwork 
                    cleanly masks out the PM contribution) and render the textured 
                    quad with the layer's MVP matrix.
                    """
                    fbo.use()
                    if tex == tex_mgr.white_tex:
                        fbo.clear(1.0, 1.0, 1.0, 1.0)
                        return
                    fbo.clear(0.0, 0.0, 0.0, 1.0)
                    mvp = vmath.get_frustum_fit_matrix(
                        float(job_data.get('fov', 45)), asp, world_scale,
                        mst_p, mst_r, lcl_p, lcl_r, WIDTH, HEIGHT,
                        par_x=render_par_x, par_y=render_par_y,
                        rot_order=rot_order)
                    prog['mvp'].write(mvp)
                    prog['filter_color'].write(np.array([1.0, 1.0, 1.0], dtype='f4'))
                    tex.use(0)
                    vao.render(moderngl.TRIANGLE_STRIP)

                # PASS 1: RENDER BIPACK 1 INTO OFF-SCREEN FBO
                render_bipack_to_fbo(bp1_fbo, tex_bp1, asp_bp1, bp1_scale,
                                     st['bp1_p'], st['bp1_r'], st['lbp1_p'], st['lbp1_r'])

                # PASS 2: RENDER BIPACK 2 INTO OFF-SCREEN FBO
                render_bipack_to_fbo(bp2_fbo, tex_bp2, asp_bp2, bp2_scale,
                                     st['bp2_p'], st['bp2_r'], st['lbp2_p'], st['lbp2_r'])

                # PASS 3: RENDER PM TO THE ACTUAL SCREEN
                ctx.screen.use()
                ctx.clear(*bg_color)
                if tex_mag == tex_mgr.white_tex:
                    mvp_mag = np.eye(4, dtype='f4').tobytes()
                else:
                    mvp_mag = vmath.get_frustum_fit_matrix(float(job_data.get('fov', 45)), asp_mag, mag_scale,
                                                        st['p'], st['r'], st['lp'], st['lr'], WIDTH, HEIGHT,
                                                        par_x=render_par_x, par_y=render_par_y,
                                                        rot_order=rot_order)
                
                prog['mvp'].write(mvp_mag)
                prog['filter_color'].write(st['pg'].astype('f4'))
                tex_mag.use(0)
                vao.render(moderngl.TRIANGLE_STRIP)
                
                # PASS 4 & 5: MULTIPLY EACH BIPACK FBO OVER THE SCREEN.
                # DST_COLOR * srcColor + ZERO is the classic multiplicative blend: 
                # destination becomes destination*source. Applied once per layer.
                # Multiplication is commutative so the application order doesn't 
                # change the final pixel values.
                ctx.enable(moderngl.BLEND)
                ctx.blend_func = (moderngl.DST_COLOR, moderngl.ZERO)
                prog['mvp'].write(np.eye(4, dtype='f4').tobytes())
                prog['filter_color'].write(np.array([1.0, 1.0, 1.0], dtype='f4'))
                bp1_tex.use(0)
                vao.render(moderngl.TRIANGLE_STRIP)
                bp2_tex.use(0)
                vao.render(moderngl.TRIANGLE_STRIP)
                ctx.disable(moderngl.BLEND)

            def execute_exposure(frame_num, is_preview=False, is_comp_preview=False):
                # is_preview         -> Cam Preview: capture + JPG, no commit, no composite
                # is_comp_preview    -> Comp Preview: capture + composite-in-memory + JPG, no commit
                # neither            -> Real exposure: capture + composite + commit to TIFF
                # is_comp_preview takes precedence over is_preview when both are True
                # (defensive - the caller should only set one).
                st = timeline.get_state(frame_num)
                # Mode dispatch for issue #169. HDR jobs run through a separate 
                # exposure path because the inner loop is fundamentally different 
                # (pre-generated DRE step sequence vs. time-normalized motion 
                # smear). Returning early here means execute_exposure's existing 
                # SSS/MDS body is completely untouched for non-HDR jobs.
                if timeline.mode == 'hdr':
                    return execute_dre_exposure(frame_num, is_preview=is_preview, 
                                                is_comp_preview=is_comp_preview)
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

                ph_pm  = timeline.calculate_playhead_at(frame_num, layer='pm')
                ph_bp1 = timeline.calculate_playhead_at(frame_num, layer='bp1')
                ph_bp2 = timeline.calculate_playhead_at(frame_num, layer='bp2')
                tex_mgr.load(ph_pm,  layer='pm')
                tex_mgr.load(ph_bp1, layer='bp1')
                tex_mgr.load(ph_bp2, layer='bp2')

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
                        render_world(frame_num, t_norm, is_preview=False)
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
                
                # Branch on which post-capture pipeline to run. Order matters:
                # comp_preview is checked first so a caller that accidentally sets
                # both flags still gets the safer (non-committing) comp behavior.
                if is_comp_preview:
                    # Comp Preview: in-memory composite onto any existing latent
                    # TIFF for this frame, write JPG, do NOT commit anything to
                    # the CamMag. PAR and unsqueeze flag forwarded for the same
                    # reasons cam_preview forwards them.
                    cutil.generate_comp_preview(buf_f, static_dir, cam_mag_dir,
                                                frame_num, st['cg'], mono_active,
                                                black_clip, par_x=par_x, par_y=par_y,
                                                preview_unsqueeze=preview_unsqueeze)
                elif is_preview:
                    # cam_preview path: forward the PAR + unsqueeze flag so the
                    # captured JPG can be optionally resampled for the preview
                    # window. The original DNG and the disk-bound latent TIFFs
                    # are NOT touched - those must remain squeezed so downstream
                    # NLE work has clean PAR-driven unsqueeze in post.
                    cutil.generate_sensor_preview(buf_f, static_dir, st['cg'], mono_active, black_clip,
                                                  par_x=par_x, par_y=par_y, preview_unsqueeze=preview_unsqueeze)
                else:
                    tiff_flag = 8 if job_data.get('tiff_compression') == 'zip' else 1
                    out_f = os.path.join(cam_mag_dir, f"latent_{str(frame_num).zfill(4)}.tif")
                    cutil.process_and_stack_latent_image(buf_f, static_dir, out_f, tiff_flag, st['cg'], mono_active, black_clip)


            def execute_dre_exposure(frame_num, is_preview=False, is_comp_preview=False):
            """
            HDR / Dynamic Range Extender exposure path (issue #169, phase 3).
            
            Sibling to execute_exposure(). Same camera trigger semantics 
            (single libcamera exposure with pre-roll), but the HDMI animation 
            pushes the DRE sequencer's output frames in dark-first order, 
            holding each step for exp_ms / dre_steps milliseconds.
            
            The PM layer is the only layer rendered in DRE mode - bipack 
            layers and spatial transforms are not part of the HDR schema. 
            The PM source is rendered as a full-frame quad with no MVP 
            transform applied (identity matrix), so what you see on screen 
            is the raw sequenced frame at native resolution.
            
            Argument semantics mirror execute_exposure() so the dispatch 
            site (snippet 3.6) can call either one with the same signature.
            """
            st = timeline.get_hdr_state(frame_num)
            exp_ms = float(st['exp']) * 1000.0
            dre_steps = int(st['dre_steps'])
            total_ms = exp_ms + 1000.0  # same 500ms pre + 500ms post as SSS
            
            black_clip = validate_black_clip(job_data.get('black_clip', 0.0))
            
            buf_f = f"/tmp/vop_buf_{frame_num}.dng" if not is_preview else "/tmp/vop_prev_buf.dng"
            
            # ---------- Refresh-rate sanity check ----------
            # The Pi's HDMI output is 60Hz on the panels we ship; each frame 
            # latches for ~16.7ms. If the requested ms_per_step falls below 
            # that, most of the sequence would be skipped before latching, 
            # silently corrupting the temporal encoding. Clamp steps down 
            # rather than fail the job - the user gets a slightly coarser 
            # bit depth but a valid result instead of garbage.
            PANEL_REFRESH_MS = 16.7  # 60Hz floor; replace with measured value later
            min_steps_dwell = PANEL_REFRESH_MS
            max_steps_for_exp = int(exp_ms / min_steps_dwell)
            if dre_steps > max_steps_for_exp:
                log_audit(
                    f"DRE WARNING frame {frame_num}: requested {dre_steps} steps in "
                    f"{exp_ms:.0f}ms = {exp_ms/dre_steps:.2f}ms/step is below the "
                    f"{PANEL_REFRESH_MS}ms panel floor. Clamping to {max_steps_for_exp} "
                    f"steps. Increase EXP or reduce DRE STEPS to silence this warning."
                )
                dre_steps = max(2, max_steps_for_exp)
            
            ms_per_step = exp_ms / dre_steps
            
            # ---------- Pre-cache the PM source frame ----------
            # DRE uses only the PM layer. The bipack textures still get loaded 
            # for cache warmth (cheap if folders are empty), but they're never 
            # rendered. The playhead is held at frame_num's resolved PM index 
            # for the full exposure - DRE has no concept of motion within a 
            # single exposure window.
            ph_pm = timeline.calculate_playhead_at(frame_num, layer='pm')
            tex_pm_8bit, asp_pm = tex_mgr.load(ph_pm, layer='pm')
            
            # ---------- Generate the DRE sequence ----------
            # The sequencer is pure numpy and expects a uint16 (H,W,3) array. 
            # tex_mgr's cache holds GPU textures, not the raw arrays, so we 
            # need to re-read the source file. This is fine for HDR mode - 
            # one read per exposure - and avoids burdening tex_mgr with a 
            # second cache for CPU-side uint16 arrays.
            import dre_sequencer as dre
            
            # Reload the source file as uint16. We trust the ingestion 
            # pipeline (phase 1.5) and TextureManager (phase 2a) to have 
            # produced 16-bit TIFFs; if a user uploaded an 8-bit source 
            # under HDR mode the sequencer's dtype check will fail loud, 
            # which is the desired behavior.
            pm_path = tex_mgr.layer_files['pm'][int(ph_pm)] if tex_mgr.layer_files.get('pm') else None
            if pm_path is None:
                log_audit(f"DRE ERROR frame {frame_num}: no PM source file. Aborting exposure.")
                return
            
            source_arr = cv2.imread(pm_path, cv2.IMREAD_UNCHANGED)
            if source_arr is None or source_arr.dtype != np.uint16:
                log_audit(
                    f"DRE ERROR frame {frame_num}: PM source is not 16-bit "
                    f"(got dtype={None if source_arr is None else source_arr.dtype}). "
                    f"HDR mode requires 16-bit TIFF sources. Aborting exposure."
                )
                return
            
            # Same colorspace + flip handling as TextureManager.load(). We need 
            # the array in the same orientation/order as what TextureManager 
            # would have uploaded, because the sequenced frames are also 
            # uploaded as moderngl textures below.
            if source_arr.ndim == 3 and source_arr.shape[2] == 4:
                source_arr = source_arr[:, :, :3]  # strip alpha
            source_arr = cv2.cvtColor(source_arr, cv2.COLOR_BGR2RGB)
            source_arr = cv2.flip(source_arr, 0)  # OpenCV->OpenGL Y flip
            
            h, w = source_arr.shape[:2]
            
            # Pre-generate the entire sequence as a list of uint8 arrays. We 
            # do this eagerly rather than lazily (the sequencer is a generator) 
            # because we want all the CPU work done before the camera shutter 
            # opens. Holding the full sequence in RAM is fine - even at 4K with 
            # 256 steps, it's ~6GB which won't fit, so cap at 1080p resolution 
            # for now. (TODO: streaming version for larger sequences.)
            # For 1080p (1920*1080*3 = 6.2MB per uint8 frame), 256 steps = 
            # 1.6GB. The Pi has 4GB. Tight but workable for an initial 
            # implementation; will need a streaming rewrite for higher 
            # resolution sources.
            sequence = list(dre.sequence_frame(source_arr, steps=dre_steps))
            log_audit(f"DRE frame {frame_num}: generated {len(sequence)} steps, {ms_per_step:.1f}ms each")
            
            # ---------- PG/CG tints for this keyframe ----------
            # Same parsing the SSS path uses; we centralize it later.
            pg = cutil.hex_to_rgb_float(st['pg'])
            cg = cutil.hex_to_rgb_float(st['cg'])
            combined_filter = np.array([pg[0]*cg[0], pg[1]*cg[1], pg[2]*cg[2]], dtype='f4')
            
            # ---------- Camera trigger + pre-roll (same as execute_exposure) ----------
            ctx.screen.use()
            ctx.clear(0.0, 0.0, 0.0, 1.0)
            ctx.finish()
            pygame.display.flip()
            
            t_trigger = time.time()
            log_audit(f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] DRE-EXPOSURE {frame_num} | Triggering libcamera")
            cam_proc = hw.trigger_capture(buf_f, total_ms, job_data.get('gain', 1.0),
                                        job_data.get('awb_r', 1.0), job_data.get('awb_b', 1.0),
                                        job_data.get('cam_res', '2028x1520'))
            hw.wait_for_sensor_prime()
            anchor = time.time()
            boot_delay = (anchor - t_trigger) * 1000
            log_audit(f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] DRE-EXPOSURE {frame_num} | Wait complete. Boot delay: {boot_delay:.1f}ms")
            log_audit(f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] DRE-EXPOSURE {frame_num} | Starting DRE sequence ({dre_steps} steps, {ms_per_step:.1f}ms each)")
            
            # ---------- The DRE sequence loop ----------
            # Walk the sequence in dark-first order (sequencer already emits 
            # them this way). Each step gets its own moderngl texture, uploaded 
            # right before display, then released after the step's window 
            # closes. This is texture-churn-heavy but bounded: the GL driver 
            # reuses VRAM aggressively and we never have more than one DRE 
            # step texture live at once.
            pre_roll_ms = 500.0
            
            for step_idx, step_frame in enumerate(sequence):
                # When should this step's display end?
                step_end_ms = pre_roll_ms + (step_idx + 1) * ms_per_step
                
                # Pre-roll wait. For step 0 only - subsequent steps inherit 
                # the wait by virtue of the previous step's hold ending exactly 
                # at this step's start.
                if step_idx == 0:
                    while (time.time() - anchor) * 1000 < pre_roll_ms:
                        pygame.event.pump()
                        ctx.screen.use()
                        ctx.clear(0.0, 0.0, 0.0, 1.0)
                        ctx.finish()
                        pygame.display.flip()
                
                # Upload this step as a fresh 8-bit RGB texture. We use the 
                # default 'f1' dtype because the sequencer's output is 
                # explicitly uint8 - this is what the projection monitor 
                # ultimately consumes.
                step_tex = ctx.texture((w, h), 3, step_frame.tobytes())
                
                # Render the step as a full-screen quad with identity transform 
                # and the keyframe's PG*CG filter color applied. No spatial 
                # geometry - DRE holds the frame stationary.
                ctx.screen.use()
                ctx.clear(0.0, 0.0, 0.0, 1.0)
                prog['mvp'].write(np.eye(4, dtype='f4').tobytes())
                prog['filter_color'].write(combined_filter.tobytes())
                step_tex.use(0)
                vao.render(moderngl.TRIANGLE_STRIP)
                ctx.finish()
                pygame.display.flip()
                
                # Hold this step until its allotted window expires. The 
                # pygame.event.pump() inside the wait loop keeps the OS happy 
                # about responsiveness; without it the Pi's window manager 
                # may flag us as unresponsive on long exposures.
                while (time.time() - anchor) * 1000 < step_end_ms:
                    pygame.event.pump()
                    # Brief sleep to avoid 100% CPU spin on the hold. 1ms is 
                    # short enough that we'll wake well within a screen 
                    # refresh of the target step_end_ms.
                    time.sleep(0.001)
                
                # Release this step's texture before the next allocation. 
                # Without this the GL driver would accumulate textures across 
                # the whole sequence and VRAM-OOM by step ~50 on 1080p sources.
                step_tex.release()
            
            # ---------- Post-exposure blackout (same as execute_exposure) ----------
            ctx.screen.use()
            ctx.clear(0.0, 0.0, 0.0, 1.0)
            prog['mvp'].write(np.eye(4, dtype='f4').tobytes())
            prog['filter_color'].write(np.array([0.0, 0.0, 0.0], dtype='f4'))
            tex_mgr.white_tex.use(0)
            vao.render(moderngl.TRIANGLE_STRIP)
            ctx.finish()
            pygame.display.flip()
            
            log_audit(f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] DRE-EXPOSURE {frame_num} | HDR sequence complete. Waiting for camera file IO.")
            cam_proc.wait()
            
            # From here on, the post-capture pipeline (DNG demosaic, noise 
            # crush, TIFF commit) is the same as SSS/MDS - the camera doesn't 
            # know or care that the HDMI animation was a DRE sequence. We 
            # delegate to the same downstream code by NOT duplicating it here. 
            # The dispatcher in snippet 3.6 falls through to that pipeline 
            # after execute_dre_exposure returns.


            # ---------------------------------------------------------
            # TASK ROUTING & EXECUTION
            # ---------------------------------------------------------
            try:
                if task == 'preview':
                    # PROJ PROBE
                    # 1. Render the composite world to the HDMI screen at real PAR
                    #    (the override that used to force 1.0/1.0 here was
                    #    removed in render_world above).
                    # 2. Read the 1920x1080 screen-grab.
                    # 3. Apply the JPG-level unsqueeze (same helper Cam Probe
                    #    uses, same math Cam View / Comp View have inline).
                    # 4. Letterbox the result into a camera-shaped canvas so
                    #    the Proj Probe JPG has the same outer shape as the
                    #    other three preview buttons under matching settings.
                    #
                    # End result: the preview window shape is consistent
                    # across all four preview buttons, and Proj Probe shows
                    # the FULL logical frame even at non-square PARs - no
                    # silent cropping at the screen edges.
                    render_world(float(job_data.get('probe_frame', 1)), float(job_data.get('probe_sub', 0.5)), is_preview=True)
                    ctx.finish()
                    raw_bytes = ctx.screen.read(components=4)
                    img_data = np.frombuffer(raw_bytes, dtype=np.uint8).reshape((HEIGHT, WIDTH, 4))
                    img_data = cv2.flip(img_data, 0)
                    img_data = cv2.cvtColor(img_data, cv2.COLOR_RGBA2BGR)

                    # Step 3: JPG-level unsqueeze. Forwards the same PAR and
                    # toggle values that were used to render. With
                    # preview_unsqueeze off this is a no-op pass-through.
                    img_data = cutil.unsqueeze_preview_jpg(img_data, par_x, par_y, preview_unsqueeze)

                    # Step 4: letterbox into a Cam-View-shaped canvas.
                    # Compute target dims from cam_res and PAR using the
                    # same formula generate_sensor_preview applies when it
                    # builds Cam View's output. Defaults to '2028x1520' to
                    # match the rest of the engine when cam_res is unset.
                    cam_res_str = job_data.get('cam_res', '2028x1520')
                    try:
                        cw_str, ch_str = cam_res_str.lower().split('x')
                        cam_w, cam_h = int(cw_str), int(ch_str)
                    except (ValueError, AttributeError):
                        # Defensive fallback - never let a malformed cam_res
                        # crash a preview. Matches the default elsewhere.
                        cam_w, cam_h = 2028, 1520

                    # Target shape mirrors what Cam View produces under the
                    # same PAR + unsqueeze inputs:
                    #   - unsqueeze off  -> camera native
                    #   - PAR > 1, on    -> wider than camera (cam_w * PAR)
                    #   - PAR < 1, on    -> taller than camera (cam_h / PAR)
                    target_w, target_h = cam_w, cam_h
                    if preview_unsqueeze:
                        try:
                            px = float(par_x) if float(par_x) > 0 else 1.0
                            py = float(par_y) if float(par_y) > 0 else 1.0
                            par = px / py
                            if abs(par - 1.0) > 1e-6:
                                if par > 1.0:
                                    target_w = int(round(cam_w * par))
                                else:
                                    target_h = int(round(cam_h / par))
                        except Exception as e:
                            log_audit(f"Proj Probe target-shape calc failed: {e}")

                    img_data = cutil.letterbox_into(img_data, target_w, target_h)

                    out_file = os.path.join(static_dir, "probe_live.jpg")
                    cv2.imwrite(out_file, img_data)
                    pygame.display.flip()
                    
                elif task == 'cam_preview':
                    execute_exposure(float(job_data.get('probe_frame', 1)), is_preview=True)

                elif task == 'comp_preview':
                    # Identical hardware path to cam_preview - smear-render the
                    # combined world while the camera captures - but route the
                    # captured DNG through the Comp Preview pipeline so the
                    # resulting JPG shows the new exposure additively
                    # composited on top of any existing latent for this frame.
                    # Nothing on disk in CamMag is altered.
                    execute_exposure(float(job_data.get('probe_frame', 1)), is_comp_preview=True)
                
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