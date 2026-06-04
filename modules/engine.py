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
# Calibration store for hardware-calibration values (T_peak, black
# floor at T_peak, future LUT data, etc.). See modules/calibration_store.py
# for the IPC / engine-busy convention notes that apply to all
# calibration tasks dispatched through this engine.
import calibration_store as cstore

# Force Pygame to bypass X11 and use the hardware framebuffer directly
os.environ["SDL_VIDEODRIVER"] = "kmsdrm"

# The IPC command file written by vop.py
COMMAND_FILE = "/tmp/vop_cmd.json"

# Sentinel polled by the idle loop (issue #198). While this file exists,
# the projection monitor shows the framing/focus targets instead of the
# bouncing logo. Same /tmp on-disk-IPC paradigm as COMMAND_FILE. vop.py
# defines the identical path on its side - keep the two in sync.
CAL_TARGETS_FILE = "/tmp/vop_cal_targets"

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

def build_ip_texture(ctx, base_font=None):
    """
    Builds a GPU texture containing the 'IP:port' string for the idle
    screen, read from the JSON vop.py publishes at /tmp/vop_ip.json.

    Returns (texture, aspect_ratio). On any failure - file missing,
    font error, malformed JSON - returns (None, 1.0) so the caller can
    simply skip rendering the IP quad this round and retry later. This
    matters at boot: the engine may come up before vop.py has written
    the file, so a missing file is an expected transient, not an error.

    The surface is vertically flipped before upload for the same reason
    the logo is (see branding.png load) - pygame's surface origin is
    top-left, OpenGL's texture origin is bottom-left.
    """
    try:
        with open("/tmp/vop_ip.json", 'r') as f:
            info = json.load(f)
        # Compose the address the user types into their browser.
        text = f"http://{info['ip']}:{info['port']}"
    except (OSError, ValueError, KeyError):
        # File not there yet (engine booted first) or malformed.
        # Caller will retry on the next refresh tick.
        return (None, 1.0)

    try:
        # font.init() is cheap and idempotent. We call it here rather
        # than assuming pygame.init() brought the font submodule up,
        # because that isn't guaranteed on every pygame build.
        if not pygame.font.get_init():
            pygame.font.init()

        # SysFont(None, ...) picks pygame's built-in default font, so we
        # don't depend on any specific TTF being installed on the Pi.
        # Size is in points; 48 renders crisply when scaled down to the
        # small idle-screen quad. White text on a transparent ground so
        # only the glyphs show against the black idle screen.
        font = base_font or pygame.font.SysFont(None, 48)
        surf = font.render(text, True, (255, 255, 255), None)
        surf = pygame.transform.flip(surf, False, True)

        w, h = surf.get_size()
        data = pygame.image.tostring(surf, "RGBA", False)
        tex = ctx.texture((w, h), 4, data)
        return (tex, w / h)
    except Exception:
        # Any rendering/upload failure - skip the IP quad, don't crash
        # the idle screen over a cosmetic element.
        return (None, 1.0)

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
    
    # ---------------------------------------------------------
    # DISPLAY RESOLUTION DISCOVERY (EDID handshake)
    # ---------------------------------------------------------
    # pygame.display.get_desktop_sizes() returns one (w, h) tuple per 
    # connected display, sourced from the kernel's KMS view of each 
    # panel's EDID. Works before set_mode() and without a window.
    #
    # We pick index [0] because the VOP only ever has one HDMI panel 
    # attached (HDMI-0). If someone runs it on a Pi with two panels 
    # connected, [0] is still the right one as long as HDMI-0 is 
    # populated - the kernel enumerates in port order.
    #
    # Fallback to 1920x1080 covers two edge cases:
    #   1. EDID read failure (rare - flaky HDMI cable, panel powered
    #      off at boot). KMS reports an empty list, we keep going on 
    #      the legacy default rather than crashing the daemon.
    #   2. Older pygame/SDL where get_desktop_sizes() isn't present.
    #      Shouldn't happen on current Pi OS but the try/except 
    #      costs us nothing.
    try:
        desktop_sizes = pygame.display.get_desktop_sizes()
        if desktop_sizes:
            WIDTH, HEIGHT = desktop_sizes[0]
            log_audit(f"Display detected via EDID: {WIDTH}x{HEIGHT}")
        else:
            WIDTH, HEIGHT = 1920, 1080
            log_audit("EDID returned no displays - falling back to 1920x1080")
    except (AttributeError, pygame.error) as e:
        WIDTH, HEIGHT = 1920, 1080
        log_audit(f"EDID query failed ({e}) - falling back to 1920x1080")
    
    # ---------------------------------------------------------
    # PUBLISH RESOLUTION FOR vop.py
    # ---------------------------------------------------------
    # Engine is the only process that can detect the panel resolution 
    # (it holds the KMSDRM lock). vop.py needs to know it for:
    #   - calculate_static_fit_scale() / Fit FOV / Fill FOV math
    #   - the NO LATENT placeholder dimensions
    # 
    # We write a small JSON file at boot. vop.py reads it lazily 
    # (cached after first read - the value never changes mid-session,
    # since changing the panel requires a full reboot anyway).
    #
    # Same on-disk-IPC pattern the COMMAND_FILE already uses - keeps 
    # the daemon architecture single-paradigm.
    DISPLAY_INFO_FILE = "/tmp/vop_display.json"
    try:
        with open(DISPLAY_INFO_FILE, 'w') as f:
            json.dump({'width': WIDTH, 'height': HEIGHT}, f)
    except OSError as e:
        # Non-fatal: vop.py will fall back to 1920x1080 if it can't 
        # read this file. Worst case is slightly-off Fit/Fill math 
        # on non-1080p panels, which the user can correct manually.
        log_audit(f"Could not publish display info: {e}")

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

    # Calibration framing/focus targets (issue #198): its own program +
    # fullscreen quad, drawn in the idle branch while CAL_TARGETS_FILE
    # exists. Separate from prog/vao so it can't disturb the main pipeline.
    cal_prog, cal_vao = gfx.init_calibration_targets(ctx)

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

    # Idle-screen IP display (see build_ip_texture). Built once here;
    # refreshed every IP_REFRESH_FRAMES in the idle loop so a DHCP
    # address change is picked up without re-rendering text every frame.
    # tex_ip may be None if vop.py hasn't published the IP yet - the
    # render path handles that by simply not drawing the IP quad.
    tex_ip, asp_ip = build_ip_texture(ctx)
    ip_refresh_counter = 0
    IP_REFRESH_FRAMES = 300   # ~5s at 60fps; cheap, catches DHCP changes

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

            task = job_data.get('task')

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

            def render_world(frame_num, t_norm, is_preview=False, bracket=None):
                """
                Renders one composite frame to the HDMI screen.

                Handles all four modes (SSS, MDS, DRE, BRK) through
                state-dispatch. The PM+BP1+BP2 multiplicative
                compositing pipeline is identical across modes -
                only the per-frame state lookup differs.

                Args:
                    frame_num : float / int. Timeline frame to render.
                    t_norm    : float in [0.0, 1.0]. Time normaliser
                                within the open-shutter window. For
                                SSS/MDS this is the smear progress.
                                For BRK and DRE the panel is held
                                steady, so t_norm has no effect on
                                the state evaluation - we still
                                accept it for signature consistency
                                with the existing callsites.
                    is_preview: bool. When True, render with a dark-
                                grey frustum-bounds background so the
                                user can see the viewport edges
                                clearly. False = true black (exposure
                                blackout).
                    bracket   : brk_sequencer.BracketSpec or None.
                                When supplied, the fragment shader's
                                source-slice remap is activated for
                                this render: source values in
                                [slice_low_norm, slice_high_norm]
                                are stretched to fill screen [0..1].
                                When None (default for SSS/MDS/DRE
                                and for BRK preview-off), the remap
                                is forced to passthrough.

                Slice-uniform hygiene: this function ALWAYS leaves
                the shader's slice uniforms in a defined state
                after returning. Either passthrough (bracket=None
                or no shader support) or the supplied bracket's
                slice. Callers don't need to clean up after; the
                next render_world call will set the uniforms again
                from its own bracket argument.
                """

                # SHADER SLICE-UNIFORM SETUP
                #
                # Set the slice-remap uniforms at the top of the
                # function based on the bracket argument. This used
                # to be done via freestanding set_slice_remap /
                # clear_slice_remap helpers, but those required
                # callers to know about the hygiene rule (always
                # clear after BRK). Folding the set/clear inline
                # makes the rule unforgettable: every render_world
                # invocation defines the slice state explicitly,
                # so leaks across calls are impossible.
                #
                # The 'in prog' guards protect against drivers
                # that may strip unreferenced uniforms during
                # shader compilation. Unlikely but cheap.
                if bracket is not None:
                    if 'slice_active' in prog:
                        prog['slice_active'].value = True
                    if 'slice_low' in prog:
                        prog['slice_low'].value = float(bracket.slice_low_norm)
                    if 'slice_high' in prog:
                        prog['slice_high'].value = float(bracket.slice_high_norm)
                else:
                    if 'slice_active' in prog:
                        prog['slice_active'].value = False
                    if 'slice_low' in prog:
                        prog['slice_low'].value = 0.0
                    if 'slice_high' in prog:
                        prog['slice_high'].value = 1.0

                # PER-FRAME STATE DISPATCH
                #
                # Each mode has its own state-lookup function. They
                # all return the same dict shape (PM/BP1/BP2 pos+rot,
                # local offsets, PG/CG gels) so the composite pass
                # below is mode-agnostic.
                #
                # SSS evaluates two state lookups (start and end of
                # the smear window) and interpolates by t_norm.
                # MDS uses a dedicated function that mixes base state
                # with per-keyframe start/stop offsets via t_norm.
                # DRE and BRK are frame-locked - t_norm is ignored.
                if timeline.mode == 'mds':
                    st = timeline.get_mds_state(float(frame_num), t_norm)
                elif timeline.mode == 'brk':
                    # BRK is frame-locked. The bracket-specific
                    # slice-remap is handled above via the shader
                    # uniforms; the spatial composite uses the
                    # held keyframe state and ignores t_norm.
                    st = timeline.get_brk_state(frame_num)
                else:
                    # SSS and DRE both use get_state.
                    #
                    # SSS: smear window centered on frame_num.
                    # t_start/t_end straddle the shutter open
                    # window; t_norm picks an instant within it.
                    #
                    # DRE: keyframes populate the SSS-shaped tracks
                    # via the shared parser, so get_state returns
                    # the correct held values. (There IS a separate
                    # get_dre_state for the DRE-specific schema
                    # fields - exp, dre_steps - but render_world
                    # doesn't read those; they're consumed by
                    # execute_dre_exposure directly. So DRE goes
                    # through this branch unchanged.)
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
                #
                # Mode dispatch for issue #169. DRE jobs run through a 
                # completely separate exposure path because the inner 
                # loop is fundamentally different (pre-generated DRE 
                # step sequence vs. time-normalized motion smear). 
                # Dispatching BEFORE get_state(frame_num) below avoids 
                # the SSS-flavored state object being computed for an 
                # DRE job - it would access pos/rot/sd/ph tracks that 
                # DRE keyframes never populate.
                if timeline.mode == 'dre':
                    return execute_dre_exposure(frame_num, is_preview=is_preview,
                                                is_comp_preview=is_comp_preview)

                # BRK mode dispatch. Like DRE, BRK has a fundamentally
                # different exposure shape than SSS/MDS: N separate
                # camera captures per frame, each at a different
                # source slice, merged in CPU. The dispatch goes
                # before the get_state() call below so the SSS-
                # flavoured state object isn't computed for a job
                # that doesn't use those tracks.
                if timeline.mode == 'brk':
                    return execute_brk_exposure(frame_num, is_preview=is_preview,
                                                is_comp_preview=is_comp_preview)

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
                
                # Delegate to the shared post-capture helper. Centralizes 
                # the three preview / commit branches so the DRE path 
                # (execute_dre_exposure) can reuse the same logic.
                _finalize_capture(buf_f, frame_num, is_preview, is_comp_preview,
                                  st['cg'], black_clip)

            def _finalize_capture(buf_f, frame_num, is_preview, is_comp_preview, 
                                  cg_color, black_clip):
                """
                Shared post-capture pipeline for both execute_exposure (SSS/MDS) 
                and execute_dre_exposure (DRE) paths.
                
                After cam_proc.wait() returns, the DNG is on disk and the camera 
                doesn't care what kind of HDMI animation produced it. The three 
                downstream paths (comp_preview / cam_preview / real exposure) 
                are mode-agnostic, so we share one implementation.
                
                The cg_color argument is the resolved camera gel for this 
                frame (RGB float array). In SSS/MDS this comes from 
                timeline.get_state(...)['cg']; in DRE from get_dre_state. 
                Centralizing the call signature here means the exposure 
                functions don't need to know about each other's state shapes.
                """
                # Branch on which post-capture pipeline to run. Order matters:
                # comp_preview is checked first so a caller that accidentally 
                # sets both flags still gets the safer (non-committing) 
                # comp behavior.
                if is_comp_preview:
                    # Comp Preview: in-memory composite onto any existing latent
                    # TIFF for this frame, write JPG, do NOT commit anything to
                    # the CamMag. PAR and unsqueeze flag forwarded for the same
                    # reasons cam_preview forwards them.
                    cutil.generate_comp_preview(buf_f, static_dir, cam_mag_dir,
                                                frame_num, cg_color, mono_active,
                                                black_clip, par_x=par_x, par_y=par_y,
                                                preview_unsqueeze=preview_unsqueeze)
                elif is_preview:
                    # cam_preview path: forward the PAR + unsqueeze flag so the
                    # captured JPG can be optionally resampled for the preview
                    # window. The original DNG and the disk-bound latent TIFFs
                    # are NOT touched - those must remain squeezed so downstream
                    # NLE work has clean PAR-driven unsqueeze in post.
                    cutil.generate_sensor_preview(buf_f, static_dir, cg_color, mono_active, black_clip,
                                                  par_x=par_x, par_y=par_y, preview_unsqueeze=preview_unsqueeze)
                else:
                    tiff_flag = 8 if job_data.get('tiff_compression') == 'zip' else 1
                    out_f = os.path.join(cam_mag_dir, f"latent_{str(frame_num).zfill(4)}.tif")
                    cutil.process_and_stack_latent_image(buf_f, static_dir, out_f, tiff_flag, cg_color, mono_active, black_clip)

            def execute_dre_exposure(frame_num, is_preview=False, is_comp_preview=False):
                """
                DRE / Dynamic Range Extender exposure path (issue #169, phase 3).
                
                Sibling to execute_exposure(). Same camera trigger semantics 
                (single libcamera exposure with pre-roll), but the HDMI animation 
                pushes the DRE sequencer's output frames in dark-first order, 
                holding each step for exp_ms / dre_steps milliseconds.
                
                The PM layer is the only layer rendered in DRE mode - bipack 
                layers and spatial transforms are not part of the DRE schema. 
                The PM source is rendered as a full-frame quad with no MVP 
                transform applied (identity matrix), so what you see on screen 
                is the raw sequenced frame at native resolution.
                
                Argument semantics mirror execute_exposure() so the dispatch 
                site (snippet 3.6) can call either one with the same signature.
                """
                st = timeline.get_dre_state(frame_num)
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
                # need to re-read the source file. This is fine for DRE mode - 
                # one read per exposure - and avoids burdening tex_mgr with a 
                # second cache for CPU-side uint16 arrays.
                import dre_sequencer as dre
                
                # ---------- Resolve PM playhead and source file -----
                # Clamp the playhead the same way TextureManager.load() does,
                # so probe-frame numbers that overshoot the available PM frames 
                # (e.g. asking for frame 99 when only frame 1 exists on disk) 
                # hold on the last available frame instead of raising IndexError.
                # 
                # The TextureManager already does this clamp internally for the 
                # texture cache, but our DRE path bypasses that cache (we need 
                # the raw uint16 array, not a GPU texture), so the clamp must 
                # be repeated here.
                pm_files = tex_mgr.layer_files.get('pm', [])
                if not pm_files:
                    log_audit(f"DRE ERROR frame {frame_num}: no PM source files. Aborting exposure.")
                    return
                ph_pm = timeline.calculate_playhead_at(frame_num, layer='pm')
                pm_idx = max(0, min(len(pm_files) - 1, int(ph_pm)))
                pm_path = pm_files[pm_idx]
                
                # Warm tex_mgr's cache too. The post-capture pipeline doesn't 
                # need this for DRE specifically, but it keeps the cache 
                # consistent across mode switches.
                tex_mgr.load(ph_pm, layer='pm')
                
                # ---------- Re-read source as raw uint16 numpy -----
                source_arr = cv2.imread(pm_path, cv2.IMREAD_UNCHANGED)
                if source_arr is None or source_arr.dtype != np.uint16:
                    log_audit(
                        f"DRE ERROR frame {frame_num}: PM source is not 16-bit "
                        f"(got dtype={None if source_arr is None else source_arr.dtype}). "
                        f"DRE mode requires 16-bit TIFF sources. Aborting exposure."
                    )
                    return
                
                # Same colorspace + flip handling as TextureManager.load() so 
                # the sequencer sees pixels in the same orientation/order the 
                # eventual 8bit moderngl textures will be uploaded with.
                if source_arr.ndim == 3 and source_arr.shape[2] == 4:
                    source_arr = source_arr[:, :, :3]  # strip alpha
                source_arr = cv2.cvtColor(source_arr, cv2.COLOR_BGR2RGB)
                source_arr = cv2.flip(source_arr, 0)  # OpenCV->OpenGL Y flip
                
                h, w = source_arr.shape[:2]
                
                # ---------- PG/CG combined filter for this keyframe ----
                # get_dre_state() already returns 'pg' and 'cg' as float RGB 
                # numpy arrays (see interpolator.hex_to_rgb at line 37 - the 
                # conversion happens at parse time, not engine time). 
                # 
                # Earlier transcription called cutil.hex_to_rgb_float() here, 
                # but no such function exists in color_utils and st['pg']/'cg' 
                # don't need it anyway. We just multiply the two RGB arrays 
                # together component-wise to get the combined filter, the 
                # same way the SSS path does at engine.py line 383.
                combined_filter = (st['pg'] * st['cg']).astype('f4')
                
                # ---------- DRE sequencer setup (streaming) ----------
                # Construct the generator. No CPU work yet - sequence_frame is 
                # a Python generator, so this just builds a closure over the 
                # source array + step count. Each `next()` during the display 
                # loop triggers one numpy operation to produce one 8bit frame.
                # 
                # Streaming over eager list() construction matters for two 
                # reasons on the Pi 4:
                #   1. RAM: 256 frames * 1080p * uint8 RGB = ~1.5 GB resident. 
                #      With 4 GB total and OS+GL+libcamera competing for it, 
                #      eager allocation was OOM-prone.
                #   2. Latency: eager generation serialized 256 numpy ops 
                #      BEFORE the camera shutter opened, blowing past the 
                #      IPC timeout (~2-4 min observed for a 256-step job).
                # By yielding one frame at a time, the CPU work overlaps the 
                # GPU's per-step screen-hold wait, so the camera sees frames 
                # starting from the very beginning of the exposure window.
                import dre_sequencer as dre
                sequence_iter = dre.sequence_frame(source_arr, steps=dre_steps)
                log_audit(f"DRE frame {frame_num}: streaming {dre_steps} steps, {ms_per_step:.1f}ms each")
                

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
                
                # Iterate the generator directly. step_frame is computed 
                # just-in-time on each iteration - while the previous step 
                # is being held on the panel, the CPU is computing the next.
                for step_idx, step_frame in enumerate(sequence_iter):
                    # Pre-roll wait. For step 0 only - subsequent steps inherit 
                    # the timing implicitly because flip() blocks for one vsync 
                    # interval. The earlier wall-time polling version of this 
                    # block was redundant: each pygame.display.flip() already 
                    # waits for the panel refresh, so we just need to count 
                    # them.
                    if step_idx == 0:
                        pre_roll_flips = max(1, int(round(pre_roll_ms / PANEL_REFRESH_MS)))
                        for _ in range(pre_roll_flips):
                            pygame.event.pump()
                            ctx.screen.use()
                            ctx.clear(0.0, 0.0, 0.0, 1.0)
                            ctx.finish()
                            pygame.display.flip()
                    
                    # ---------- Step display ----------
                    # The previous version of this block tried to hold each 
                    # step on screen by combining a single flip() with a 
                    # busy wait-loop that called time.sleep(0.001). That 
                    # was ~10x too slow per step on the Pi 4:
                    #   - flip() already blocks for one ~16.7ms vsync interval
                    #   - time.sleep(0.001) returns after ~10ms (kernel quantum)
                    #   - the wait-loop's pygame.event.pump() added more latency
                    # Net effect: a 19.5ms-per-step target was actually running 
                    # at 200+ms per step, blowing past the IPC timeout on any 
                    # job with more than ~30 steps.
                    # 
                    # Replacement is just N vsync-aligned flips per step. Each 
                    # flip() blocks for exactly one refresh interval, so N 
                    # flips = N * PANEL_REFRESH_MS of held display time.
                    # 
                    # Trade-off: effective ms-per-step becomes quantized to 
                    # the refresh interval. For a 5s/256-step job, target 
                    # 19.5ms rounds to 1 flip = 16.7ms, so the actual 
                    # exposure runs slightly short of requested EXP. This 
                    # is the price of vsync alignment - the calibration LUT 
                    # phase (issue #184) will sharpen the relationship 
                    # between user-requested EXP and integrated photons.
                    flips_per_step = max(1, int(round(ms_per_step / PANEL_REFRESH_MS)))
                    
                    # Upload this step as a fresh 8-bit RGB texture. We use the 
                    # default 'f1' dtype because the sequencer's output is 
                    # explicitly uint8 - this is what the projection monitor 
                    # ultimately consumes.
                    step_tex = ctx.texture((w, h), 3, step_frame.tobytes())
                    
                    # Render the step as a full-screen quad with identity 
                    # transform and the keyframe's PG*CG filter color applied. 
                    # No spatial geometry - DRE holds the frame stationary.
                    ctx.screen.use()
                    ctx.clear(0.0, 0.0, 0.0, 1.0)
                    prog['mvp'].write(np.eye(4, dtype='f4').tobytes())
                    prog['filter_color'].write(combined_filter.tobytes())
                    step_tex.use(0)
                    vao.render(moderngl.TRIANGLE_STRIP)
                    ctx.finish()
                    
                    # Hold the step on screen for flips_per_step vsync intervals. 
                    # Each flip() blocks until the next refresh, so this is exactly 
                    # flips_per_step * PANEL_REFRESH_MS of display time. The first 
                    # flip in this batch is also what pushes the just-rendered 
                    # contents to the screen, so the texture is visible for all 
                    # N refresh intervals, not N-1.
                    for _ in range(flips_per_step):
                        pygame.event.pump()
                        pygame.display.flip()
                    
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
                
                log_audit(f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] DRE-EXPOSURE {frame_num} | DRE sequence complete. Waiting for camera file IO.")
                cam_proc.wait()
                
                # Delegate to the shared post-capture helper (same one 
                # execute_exposure uses for SSS/MDS). The camera doesn't 
                # know or care what kind of HDMI animation produced 
                # the DNG, so the downstream pipeline is mode-agnostic.
                _finalize_capture(buf_f, frame_num, is_preview, is_comp_preview,
                                  st['cg'], black_clip)

            def _finalize_brk_capture(merged_rgb, frame_num, cg_color,
                                      black_clip, destination='latent'):
                """
                BRK post-merger finalizer.

                Takes the merger's pre-decoded uint16 RGB array and
                routes it to one of three downstream destinations based
                on the `destination` argument. Each destination has its
                own helper in color_utils that handles the post-decode
                pipeline (pedestal, BGR convert, mono, gel, write).
                This function is the thin engine-side router.

                Destinations:
                  'latent'         : write the merged array as a
                                     CamMag/latent_NNNN.tif TIFF.
                                     Used by real Execute Sequence.
                                     Unconditionally overwrites any
                                     existing latent at this frame
                                     (BRK does not stack like SSS/MDS).
                  'sensor_preview' : write the merged array as
                                     static/probe_live.jpg.
                                     Used by BRK Cam View.
                  'comp_preview'   : same as sensor_preview, but
                                     additively composites against any
                                     existing latent at this frame
                                     before writing the JPG. The
                                     latent on disk is NOT modified.
                                     Used by BRK Comp View.

                Args:
                    merged_rgb  : numpy.ndarray, uint16, (H, W, 3) RGB.
                                  brk_merger.merge output.
                    frame_num   : int. For filename construction.
                    cg_color    : (3,) float [0..1] RGB. Camera gel
                                  from timeline.get_brk_state.
                    black_clip  : float. Job's pedestal value.
                    destination : str, one of 'latent',
                                  'sensor_preview', 'comp_preview'.
                                  Defaults to 'latent' to match the
                                  function's original signature.
                """
                try:
                    # Pull job-level settings once, shared across
                    # destinations. tiff_flag is only used by 'latent'
                    # but reading job_data here keeps the dispatch
                    # below clean.
                    mono_forced = bool(job_data.get('mono_mode', False))
                    par_x = float(job_data.get('par_x', 1.0) or 1.0)
                    par_y = float(job_data.get('par_y', 1.0) or 1.0)
                    preview_unsqueeze = bool(
                        job_data.get('preview_unsqueeze', False)
                    )

                    if destination == 'latent':
                        tiff_flag = (
                            8 if job_data.get('tiff_compression') == 'zip'
                            else 1
                        )
                        out_f = os.path.join(
                            cam_mag_dir,
                            f"latent_{str(frame_num).zfill(4)}.tif"
                        )
                        cutil.write_merged_latent(
                            merged_rgb=merged_rgb,
                            output_file=out_f,
                            tiff_flag=tiff_flag,
                            cam_gel_rgb=cg_color,
                            mono_forced=mono_forced,
                            black_clip=black_clip,
                        )
                    elif destination == 'sensor_preview':
                        cutil.merged_to_sensor_preview(
                            merged_rgb=merged_rgb,
                            static_dir=static_dir,
                            cam_gel_rgb=cg_color,
                            mono_forced=mono_forced,
                            black_clip=black_clip,
                            par_x=par_x,
                            par_y=par_y,
                            preview_unsqueeze=preview_unsqueeze,
                        )
                    elif destination == 'comp_preview':
                        cutil.merged_to_comp_preview(
                            merged_rgb=merged_rgb,
                            static_dir=static_dir,
                            cam_mag_dir=cam_mag_dir,
                            frame_num=frame_num,
                            cam_gel_rgb=cg_color,
                            mono_forced=mono_forced,
                            black_clip=black_clip,
                            par_x=par_x,
                            par_y=par_y,
                            preview_unsqueeze=preview_unsqueeze,
                        )
                    else:
                        # Unknown destination is a programming error
                        # (engine-internal call with a typo or bad
                        # branch). Log it loudly and fall back to
                        # writing the latent so we don't silently
                        # produce no output.
                        log_audit(
                            f"BRK ERROR frame {frame_num}: "
                            f"_finalize_brk_capture called with "
                            f"unknown destination '{destination}'. "
                            f"Falling back to 'latent'."
                        )
                        tiff_flag = (
                            8 if job_data.get('tiff_compression') == 'zip'
                            else 1
                        )
                        out_f = os.path.join(
                            cam_mag_dir,
                            f"latent_{str(frame_num).zfill(4)}.tif"
                        )
                        cutil.write_merged_latent(
                            merged_rgb=merged_rgb,
                            output_file=out_f,
                            tiff_flag=tiff_flag,
                            cam_gel_rgb=cg_color,
                            mono_forced=mono_forced,
                            black_clip=black_clip,
                        )

                except Exception as e:
                    print(f"[VOP WARNING] _finalize_brk_capture error for frame {frame_num}: {e}")
                    log_audit(
                        f"BRK ERROR frame {frame_num}: finalize failed: {e}. "
                        f"destination={destination}"
                    )

            def execute_brk_exposure(frame_num, is_preview=False, is_comp_preview=False):
                """
                BRK / Bracketed-exposure path (issue: BRK mode).

                Sibling of execute_exposure and execute_dre_exposure.
                Unlike SSS/MDS (one camera capture per frame, motion
                rendered during the open shutter) and DRE (one camera
                capture per frame, multiple displayed steps within
                the shutter), BRK runs N SEPARATE camera captures
                per frame - one per bracket - and merges them on the
                CPU after all captures complete.

                Per-bracket flow:
                  1. Set shader's slice-remap uniforms to this
                     bracket's source range.
                  2. Trigger camera for t_peak + pre/post roll.
                  3. During the open-shutter window, render the
                     usual PM+BP1+BP2 composite via render_world.
                     The shader applies the slice remap, so the
                     panel shows the source's [slice_low, slice_high]
                     range stretched to full 0..1.
                  4. Camera writes its DNG to a per-bracket path.

                After all N brackets:
                  5. Decode each DNG to uint16 RGB via
                     cutil.dng_to_uint16_rgb.
                  6. brk_merger.merge() fuses them into one uint16.
                  7. _finalize_brk_capture writes the latent TIFF.

                Preview semantics: when is_preview or is_comp_preview
                is True, the FULL bracket sequence still runs (BRK has
                no cheaper preview - the only representative preview of
                a bracketed frame is the actual N-bracket merge). The
                difference is purely in the finalize destination:
                  - is_comp_preview -> merged result composited against
                    any existing latent, written to probe_live.jpg.
                    The latent on disk is NOT modified.
                  - is_preview (Cam View) -> merged result written
                    straight to probe_live.jpg. No composite, no
                    commit.
                  - neither (real Execute) -> merged result written
                    to CamMag/latent_NNNN.tif.
                is_comp_preview takes precedence over is_preview when
                both are set, matching execute_exposure's convention.

                This means a BRK Cam View / Comp View is as slow as a
                real one-frame Execute (it captures all brackets). That
                is intentional and was a deliberate design decision:
                the user wants to see exactly what Execute will produce,
                and for BRK there is no faster faithful preview.
                """

                # ---------- Read job config + calibration ----------
                # bracket_count and bracket_stops live in job_data
                # (per-job UI controls). t_peak lives in
                # calibration.json (set by Peak White ACB
                # calibration). All three are required - if any
                # are missing, abort the frame and log clearly.
                try:
                    bracket_count = int(job_data.get('bracket_count', 3))
                    bracket_stops = float(job_data.get('bracket_stops', 1.0))
                except (ValueError, TypeError) as e:
                    log_audit(
                        f"BRK ERROR frame {frame_num}: malformed bracket_count "
                        f"or bracket_stops in job_data: {e}. Aborting frame."
                    )
                    return

                t_peak = cstore.get(static_dir, 't_peak', default=None)
                if t_peak is None:
                    log_audit(
                        f"BRK ERROR frame {frame_num}: no t_peak in calibration.json. "
                        f"Run Peak White ACB calibration first. Aborting frame."
                    )
                    return
                t_peak = float(t_peak)

                # ---------- Build the bracket schedule ----------
                # The sequencer is pure-math; it can't fail unless
                # we passed it out-of-range parameters, which the
                # GUI clamps and the type-check above caught.
                import brk_sequencer as brk_seq
                try:
                    brackets = brk_seq.compute_brackets(
                        bracket_count, bracket_stops, t_peak
                    )
                except ValueError as e:
                    log_audit(f"BRK ERROR frame {frame_num}: {e}. Aborting frame.")
                    return

                # Audit the bracket plan once at frame start - lets
                # the user see exactly what's about to happen.
                log_audit(
                    f"BRK frame {frame_num}: {len(brackets)} brackets at "
                    f"{bracket_stops} stops, t_peak={t_peak:.3f}s each. "
                    f"Estimated total per frame: {len(brackets) * (t_peak + 1.0):.1f}s"
                )
                # Warn (don't abort) on extreme configurations - the
                # user may have chosen these deliberately.
                brk_seq.warn_if_extreme(brackets, log_fn=log_audit)

                # ---------- Per-frame BRK state ----------
                # get_brk_state currently returns just gels. POS/ROT
                # and JK printer per-keyframe overrides land in
                # slice 13; for slice 12b we use straight playheads
                # (frame_num as PM playhead) and identity transforms.
                brk_state = timeline.get_brk_state(frame_num)
                pg_color = brk_state['pg']
                cg_color = brk_state['cg']

                black_clip = validate_black_clip(job_data.get('black_clip', 0.0))

                # ---------- Per-bracket capture loop ----------
                # Each bracket gets its own buffer path so the
                # finalize step can read them all back independently.
                # /tmp is fine - small files, cleared after merge.
                captured_files = []
                try:
                    for bracket in brackets:
                        bracket_buf = (
                            f"/tmp/vop_brk_buf_{frame_num}_b{bracket.index}.dng"
                        )

                        # Pre-cache the layer textures. Same as
                        # execute_exposure (SSS) - no-op if the
                        # textures are already warm in cache from
                        # a prior bracket. After the first bracket
                        # in this frame all subsequent ones hit
                        # the cache, which is the big perf win.
                        ph_pm  = timeline.calculate_playhead_at(frame_num, layer='pm')
                        ph_bp1 = timeline.calculate_playhead_at(frame_num, layer='bp1')
                        ph_bp2 = timeline.calculate_playhead_at(frame_num, layer='bp2')
                        tex_mgr.load(ph_pm,  layer='pm')
                        tex_mgr.load(ph_bp1, layer='bp1')
                        tex_mgr.load(ph_bp2, layer='bp2')

                        # Pre-exposure blackout. Forces the screen to
                        # true black before the camera shutter opens.
                        ctx.screen.use()
                        ctx.clear(0.0, 0.0, 0.0, 1.0)
                        ctx.finish()
                        pygame.display.flip()

                        # Camera trigger + pre-roll. Same shape as
                        # SSS execute_exposure, with the same
                        # 500ms pre-roll / 500ms post-roll envelope.
                        # The "smr" window length here is t_peak
                        # itself - BRK is frame-locked so the panel
                        # is held steady for the full open-shutter
                        # window.
                        smr_ms = t_peak * 1000.0
                        total_ms = smr_ms + 1000.0

                        t_trigger = time.time()
                        log_audit(
                            f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] "
                            f"BRK-EXPOSURE {frame_num}.b{bracket.index} | "
                            f"Triggering libcamera, slice=[{bracket.slice_low_norm:.4f}, "
                            f"{bracket.slice_high_norm:.4f}]"
                        )
                        cam_proc = hw.trigger_capture(
                            bracket_buf, total_ms,
                            job_data.get('gain', 1.0),
                            job_data.get('awb_r', 1.0),
                            job_data.get('awb_b', 1.0),
                            job_data.get('cam_res', '2028x1520')
                        )
                        hw.wait_for_sensor_prime()
                        anchor = time.time()

                        # Render-during-shutter loop, identical to
                        # SSS execute_exposure. Walks the open-
                        # shutter window in real time, rendering
                        # the composite during the in_window phase
                        # and forcing black outside it.
                        frame_rendered = False
                        while (time.time() - anchor) * 1000 < total_ms:
                            pygame.event.pump()
                            elapsed = (time.time() - anchor) * 1000

                            in_window = 500.0 <= elapsed <= (500.0 + smr_ms)
                            missed_window = (elapsed > 500.0) and not frame_rendered

                            if in_window or missed_window:
                                # Render the PM+BP1+BP2 composite with
                                # this bracket's source-slice remap
                                # applied via the shader. render_world
                                # handles slice-uniform setup and BRK
                                # state lookup internally based on
                                # the bracket argument and
                                # timeline.mode respectively.
                                #
                                # BRK is frame-locked, so t_norm
                                # doesn't matter across the open-
                                # shutter window - we pass 0.5
                                # (middle) as a stable point.
                                render_world(frame_num, 0.5,
                                             is_preview=False,
                                             bracket=bracket)
                                frame_rendered = True
                            else:
                                # Forced blackout outside the open-
                                # shutter window (same as SSS).
                                ctx.screen.use()
                                ctx.clear(0.0, 0.0, 0.0, 1.0)
                                prog['mvp'].write(np.eye(4, dtype='f4').tobytes())
                                prog['filter_color'].write(np.array([0.0, 0.0, 0.0], dtype='f4'))
                                tex_mgr.white_tex.use(0)
                                vao.render(moderngl.TRIANGLE_STRIP)

                            ctx.finish()
                            pygame.display.flip()

                        # Post-exposure blackout for this bracket.
                        ctx.screen.use()
                        ctx.clear(0.0, 0.0, 0.0, 1.0)
                        prog['mvp'].write(np.eye(4, dtype='f4').tobytes())
                        prog['filter_color'].write(np.array([0.0, 0.0, 0.0], dtype='f4'))
                        tex_mgr.white_tex.use(0)
                        vao.render(moderngl.TRIANGLE_STRIP)
                        ctx.finish()
                        pygame.display.flip()

                        cam_proc.wait()
                        captured_files.append(bracket_buf)
                        log_audit(
                            f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] "
                            f"BRK-EXPOSURE {frame_num}.b{bracket.index} | DNG saved."
                        )

                finally:
                    # Slice-remap hygiene used to require an explicit
                    # clear here, because the per-bracket loop set
                    # slice uniforms via a freestanding helper that
                    # left them dirty after the loop ended. With
                    # render_world now owning slice-uniform setup,
                    # the next non-BRK render_world call (or any
                    # render_world call with bracket=None) will
                    # automatically clear the uniforms. No explicit
                    # cleanup needed here.
                    #
                    # The try/finally is kept so the structure stays
                    # the same in case future BRK additions (e.g.
                    # per-bracket buffer cleanup on exception) need
                    # to be added to this block. Empty pass for now.
                    pass

                # ---------- Decode all DNGs to uint16 arrays ----------
                # cutil.dng_to_uint16_rgb returns the RGB uint16
                # array with hot-pixel patch and pedestal applied.
                # For BRK we leave pedestal at 0 (job's black_clip
                # is for the *merged* result, not per-bracket - the
                # merger's overlap-weight blend handles the noise
                # floor implicitly).
                log_audit(f"BRK frame {frame_num}: decoding {len(captured_files)} DNGs...")
                arrays = []
                for buf in captured_files:
                    arr = cutil.dng_to_uint16_rgb(buf, static_dir, black_clip=0.0)
                    if arr is None:
                        log_audit(
                            f"BRK ERROR frame {frame_num}: failed to decode {buf}. "
                            f"Aborting frame."
                        )
                        # Clean up before bailing
                        for b in captured_files:
                            if os.path.exists(b):
                                os.remove(b)
                            jpg = b.replace('.dng', '.jpg')
                            if os.path.exists(jpg):
                                os.remove(jpg)
                        return
                    arrays.append(arr)

                # ---------- Merge the brackets ----------
                # brk_merger.merge is pure-numpy and validates its
                # inputs (raises ValueError on shape/dtype mismatch).
                # The output is a uint16 RGB (H,W,3) array - the
                # merged latent in source-space.
                import brk_merger
                try:
                    merged = brk_merger.merge(arrays, brackets)
                except ValueError as e:
                    log_audit(f"BRK ERROR frame {frame_num}: merger failed: {e}. Aborting.")
                    for b in captured_files:
                        if os.path.exists(b):
                            os.remove(b)
                    return

                log_audit(
                    f"BRK frame {frame_num}: merged. shape={merged.shape}, "
                    f"dtype={merged.dtype}, min={merged.min()}, max={merged.max()}."
                )

                # ---------- Finalize: route by destination ----------
                # _finalize_brk_capture dispatches to one of three
                # color_utils helpers based on the destination arg.
                # We pick the destination from the preview flags:
                #   is_comp_preview -> 'comp_preview' (composite + JPG)
                #   is_preview      -> 'sensor_preview' (JPG only)
                #   neither         -> 'latent' (CamMag TIFF write)
                # is_comp_preview takes precedence when both are set,
                # matching execute_exposure's flag-precedence rule.
                if is_comp_preview:
                    brk_destination = 'comp_preview'
                elif is_preview:
                    brk_destination = 'sensor_preview'
                else:
                    brk_destination = 'latent'

                _finalize_brk_capture(
                    merged, frame_num, cg_color, black_clip,
                    destination=brk_destination
                )

                # ---------- Cleanup ----------
                # Remove per-bracket DNGs and their JPG siblings.
                # Each capture leaves both files; the JPG is a
                # libcamera-side preview that we don't use. Both are
                # transient - the merged latent (or preview JPG) is
                # the only output we keep.
                for buf in captured_files:
                    if os.path.exists(buf):
                        os.remove(buf)
                    jpg = buf.replace('.dng', '.jpg')
                    if os.path.exists(jpg):
                        os.remove(jpg)

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
                    # ---- Render-to-screen branch: SSS/MDS path vs DRE DRE-step path ----
                    # 
                    # The SSS/MDS path uses render_world() to composite all three 
                    # optical layers onto the screen with the smear's spatial 
                    # transforms applied. 
                    # 
                    # The DRE path has two sub-cases:
                    #   - DRE preview OFF: same as today, render_world() draws the 
                    #     raw PM source through identity transforms. Since DRE 
                    #     keyframes don't populate the SSS-style pos/rot tracks, 
                    #     get_state() returns identity defaults and the result is 
                    #     a clean preview of the source frame.
                    #   - DRE preview ON: pick one specific step from the DRE 
                    #     sequencer (selected by Sub * dre_steps), upload it as a 
                    #     full-screen quad, render to screen. This lets the user 
                    #     visualize what the projection monitor will display at 
                    #     that point during a real exposure - extremely useful for 
                    #     calibration intuition and exposure planning.
                    # 
                    # Whichever branch runs, by the time we exit this block the 
                    # HDMI screen holds a valid 1920x1080 render that the rest of 
                    # the preview pipeline (screen-grab -> unsqueeze -> letterbox 
                    # -> JPG) can consume unchanged.
                    probe_frame = float(job_data.get('probe_frame', 1))
                    probe_sub = float(job_data.get('probe_sub', 0.5))
                    dre_preview_on = (timeline.mode == 'dre' 
                                       and str(job_data.get('probe_dre', 'false')).lower() in ('true', 'on', '1'))

                    # BRK probe toggle: when in BRK mode AND the BRK probe
                    # toggle is on, Proj Probe shows ONE bracket's slice
                    # remap (so the user can scrub through brackets and
                    # see how each one paints the panel). When off, BRK
                    # Proj Probe shows the raw composite (bracket=None),
                    # identical in spirit to the SSS/MDS path.
                    #
                    # The toggle field is 'probe_brk' (parallel to DRE's
                    # 'probe_dre'). The sub-slider 'probe_sub' [0..1]
                    # picks which bracket: 0.0 = peak (bracket 0),
                    # 1.0 = deepest (bracket N-1).
                    brk_preview_on = (timeline.mode == 'brk'
                                       and str(job_data.get('probe_brk', 'false')).lower() in ('true', 'on', '1'))

                    if brk_preview_on:
                        # ---- BRK bracket-slice preview path ----
                        # Build the bracket specs the same way the
                        # execute path does, then pick one by probe_sub.
                        import brk_sequencer
                        try:
                            bc = int(job_data.get('bracket_count', 3))
                            bs = float(job_data.get('bracket_stops', 1.0))
                            tp = cstore.get(static_dir, 't_peak', default=0.75)
                            brk_specs = brk_sequencer.compute_brackets(bc, bs, tp)
                        except Exception as e:
                            log_audit(f"BRK PROBE: failed to build bracket specs: {e}. "
                                      f"Falling back to raw composite.")
                            brk_specs = []

                        if brk_specs:
                            # Map probe_sub [0..1] to bracket index
                            # [0, N-1]. min() so sub=1.0 hits the last
                            # bracket (deepest), matching the DRE
                            # convention where sub=1.0 is the END.
                            b_idx = min(int(probe_sub * len(brk_specs)), len(brk_specs) - 1)
                            b_idx = max(0, b_idx)
                            chosen = brk_specs[b_idx]
                            log_audit(
                                f"BRK PROBE: frame {probe_frame}, bracket "
                                f"{b_idx}/{len(brk_specs)-1}, "
                                f"slice=[{chosen.slice_low_norm:.4f}, "
                                f"{chosen.slice_high_norm:.4f}]"
                            )
                            # render_world with a bracket applies the
                            # slice-remap shader uniforms (Phase 2).
                            render_world(probe_frame, probe_sub,
                                         is_preview=True, bracket=chosen)
                        else:
                            # No specs - fall back to raw composite.
                            render_world(probe_frame, probe_sub, is_preview=True)
                    elif dre_preview_on:
                        # ---- DRE step preview path ----
                        # Resolve DRE keyframe state (gives us dre_steps and gel colors).
                        st = timeline.get_dre_state(probe_frame)
                        dre_steps = int(st['dre_steps'])
                        
                        # Map Sub [0.0, 1.0] to step index [0, dre_steps-1]. 
                        # We use min() rather than clip so sub=1.0 exactly hits 
                        # the last meaningful step (where only the brightest 
                        # pixels still contribute), matching the SSS convention 
                        # that sub=1.0 shows the END of a smear.
                        step_idx = min(int(probe_sub * dre_steps), dre_steps - 1)
                        step_idx = max(0, step_idx)  # also clamp the low end for safety
                        
                        # Resolve and load PM source as raw uint16 numpy (same 
                        # pattern as execute_dre_exposure). The TextureManager 
                        # cache holds GPU textures, not arrays, so we re-read 
                        # the file. For a single-step preview the cost is fine.
                        pm_files = tex_mgr.layer_files.get('pm', [])
                        if not pm_files:
                            log_audit(f"DRE PREVIEW: no PM source files. Falling back to render_world().")
                            render_world(probe_frame, probe_sub, is_preview=True)
                        else:
                            ph_pm = timeline.calculate_playhead_at(probe_frame, layer='pm')
                            pm_idx = max(0, min(len(pm_files) - 1, int(ph_pm)))
                            pm_path = pm_files[pm_idx]
                            
                            source_arr = cv2.imread(pm_path, cv2.IMREAD_UNCHANGED)
                            if source_arr is None or source_arr.dtype != np.uint16:
                                log_audit(f"DRE PREVIEW: PM source not 16-bit. Falling back to render_world().")
                                render_world(probe_frame, probe_sub, is_preview=True)
                            else:
                                # Same colorspace + flip handling as execute_dre_exposure.
                                if source_arr.ndim == 3 and source_arr.shape[2] == 4:
                                    source_arr = source_arr[:, :, :3]
                                source_arr = cv2.cvtColor(source_arr, cv2.COLOR_BGR2RGB)
                                source_arr = cv2.flip(source_arr, 0)
                                h_src, w_src = source_arr.shape[:2]
                                
                                # Walk the sequencer to the requested step. Cheap: 
                                # each step is one numpy clip, and we throw away 
                                # all but the last. For dre_steps <= 256 this 
                                # takes well under 100ms on the Pi.
                                import dre_sequencer as dre
                                seq_iter = dre.sequence_frame(source_arr, steps=dre_steps)
                                step_frame = None
                                for i, f in enumerate(seq_iter):
                                    if i == step_idx:
                                        step_frame = f
                                        break
                                
                                # Render the step to the screen, identical to one 
                                # iteration of the execute_dre_exposure inner loop.
                                combined_filter = (st['pg'] * st['cg']).astype('f4')
                                step_tex = ctx.texture((w_src, h_src), 3, step_frame.tobytes())
                                ctx.screen.use()
                                ctx.clear(0.1, 0.1, 0.1, 1.0)  # gray bg = frustum-bounds visual cue, matches is_preview=True
                                prog['mvp'].write(np.eye(4, dtype='f4').tobytes())
                                prog['filter_color'].write(combined_filter.tobytes())
                                step_tex.use(0)
                                vao.render(moderngl.TRIANGLE_STRIP)
                                step_tex.release()
                                log_audit(f"DRE PREVIEW: rendered step {step_idx}/{dre_steps-1} of frame {probe_frame}")
                    else:
                        # Default path: SSS/MDS smear preview, or DRE with DRE 
                        # toggle off (which render_world handles correctly via 
                        # identity-transform defaults).
                        render_world(probe_frame, probe_sub, is_preview=True)
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

                    # Step 5: bake an explicit "inside camera, outside panel"
                    # indicator band into the JPG itself. The default fill
                    # (26,26,26) matches --bg-panel in style.css, which used
                    # to be desirable - the JPG letterbox visually merged
                    # into the preview-area background so the seam was
                    # invisible. For Proj Probe specifically that's exactly
                    # the wrong behavior: we WANT the user to see where the
                    # projection panel ends and the camera frame still
                    # continues, because that gap is the whole point of the
                    # PAR + screen-shape preview.
                    #
                    # Picking (64,64,64) = #404040 here gives a clearly
                    # lighter mid-grey that:
                    #   - reads as distinct from --bg-panel (#1a1a1a) outside,
                    #   - reads as distinct from chart blacks (0) inside,
                    #   - stays neutral enough not to compete with image
                    #     content for attention.
                    # Only this Proj Probe call site overrides the default;
                    # letterbox_into itself keeps its old default so any
                    # future caller that DOES want the seam-blending
                    # behavior gets it for free without re-specifying.
                    img_data = cutil.letterbox_into(
                        img_data, target_w, target_h, fill_bgr=(64, 64, 64)
                    )

                    out_file = os.path.join(static_dir, "probe_live.jpg")
                    cv2.imwrite(out_file, img_data)
                    pygame.display.flip()
                    
                elif task == 'cam_preview':
                    # Cam View. For all modes including BRK, this routes
                    # through execute_exposure, which dispatches to the
                    # mode-specific capture path. For BRK that means
                    # execute_brk_exposure runs the full N-bracket
                    # sequence and (because is_preview=True) routes the
                    # merged result to probe_live.jpg instead of a
                    # latent TIFF. Slow but representative - it's exactly
                    # what Execute will produce for this frame.
                    execute_exposure(float(job_data.get('probe_frame', 1)), is_preview=True)

                elif task == 'comp_preview':
                    # Comp View. For all modes including BRK, routes
                    # through execute_exposure. The captured result is
                    # additively composited on top of any existing
                    # latent for this frame and written to the preview
                    # JPG; nothing on disk in CamMag is altered. For
                    # BRK, execute_brk_exposure runs the full N-bracket
                    # sequence and (because is_comp_preview=True) routes
                    # the merged result through the comp_preview
                    # destination.
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
                    # Capture the dark frame.
                    #
                    # The shutter argument must be plain total_ms - do NOT
                    # add PRIME_WAIT_MS here. trigger_capture already bakes
                    # the prime delay into rpicam-still's `-t` flag, and the
                    # wait_for_sensor_prime() call below mirrors that same
                    # delay on the Python side. The shutter we actually want
                    # is total_ms (frame exposure + the 1000ms header/tail
                    # pad) - the IDENTICAL integration time a real exposure
                    # of this frame uses (the normal exposure path also
                    # passes plain total_ms).
                    #
                    # The old code added PRIME_WAIT_MS, stretching the
                    # shutter by 1.5s. Since sensor dark current grows
                    # roughly linearly with integration time, that made the
                    # reported noise floor correspond to a longer-than-
                    # claimed exposure - i.e. overstated. (issue #187)
                    cam_proc = hw.trigger_capture(buf_f, total_ms, job_data.get('gain', 1.0),
                                                  job_data.get('awb_r', 1.0), job_data.get('awb_b', 1.0),
                                                  job_data.get('cam_res', '2028x1520'))
                    hw.wait_for_sensor_prime()
                    time.sleep(total_ms / 1000.0) 
                    cam_proc.wait()

                    noise_val = cutil.measure_noise_floor(buf_f, static_dir)
                    log_audit(f">>> RECOMMENDED BLACK CLIP: {noise_val:.6f} <<<")
                
                elif task == 'single_peak_measurement':
                    # Calibration page: "Single Measurement" button.
                    # Show a synthetic white patch on the projection
                    # monitor, capture once at the user-supplied
                    # exposure time, measure centre brightness, and
                    # write the result to calibration.json under a
                    # transient key the frontend reads to colour-code
                    # the readout.
                    #
                    # Unlike measure_noise this task does not consult
                    # the timeline - exposure time comes straight from
                    # the request payload, because the Calibration page
                    # is decoupled from any job's keyframes. The user
                    # is asking "what does the sensor see at X seconds
                    # right now?", not "what would the sensor see for
                    # frame N of my current job?".
                    exposure_s = float(job_data.get('exposure_s', 1.0))
                    total_ms = exposure_s * 1000.0

                    log_audit(f"Calibration | Single Peak Measurement | {exposure_s:.3f}s")

                    # Draw the synthetic white patch on the projection
                    # monitor. We use ctx.clear with full-white because
                    # it's the simplest correct way to drive the panel
                    # to its true maximum output. A full-screen flat
                    # field is also intentional: it removes any
                    # uncertainty about which screen region we're
                    # actually measuring. The centre-patch limiting
                    # happens on the sensor side (see
                    # measure_centre_brightness), not the screen side.
                    ctx.screen.use()
                    ctx.clear(1.0, 1.0, 1.0, 1.0)
                    pygame.display.flip()

                    # Capture using the same trigger pattern as every
                    # other calibration task: plain total_ms as the
                    # shutter argument, with the sensor prime handled
                    # separately by trigger_capture's `-t` flag and the
                    # wait_for_sensor_prime() call below. Do NOT add
                    # PRIME_WAIT_MS to the shutter (see issue #187).
                    buf_f = "/tmp/vop_peak_buf.dng"
                    cam_proc = hw.trigger_capture(
                        buf_f,
                        total_ms,
                        job_data.get('gain', 1.0),
                        job_data.get('awb_r', 1.0),
                        job_data.get('awb_b', 1.0),
                        job_data.get('cam_res', '2028x1520'),
                    )
                    hw.wait_for_sensor_prime()
                    time.sleep(total_ms / 1000.0)
                    cam_proc.wait()

                    # Centre-weighted brightness in [0.0, 1.0]. This
                    # writes probe_live.jpg as a side effect, so the
                    # frontend's preview window will refresh with the
                    # capture once polling sees status return to idle.
                    brightness = cutil.measure_centre_brightness(buf_f, static_dir)

                    # Persist the result. We write it under a transient
                    # key (last_single_measurement) rather than t_peak
                    # because a single-shot measurement is *not* a
                    # commitment that this exposure should become the
                    # stored T_peak - only ACB writes t_peak. The
                    # frontend reads last_single_measurement to colour-
                    # code its readout, but does not auto-populate the
                    # exposure-time field from it.
                    cstore.save(static_dir, {
                        'last_single_measurement': {
                            'exposure_s': exposure_s,
                            'brightness': brightness,
                        }
                    })

                    log_audit(f">>> SINGLE MEASUREMENT: {brightness:.6f} at {exposure_s:.3f}s <<<")

                elif task == 'measure_peak_white':
                    # Calibration page: "ACB" (Auto Calibrate for
                    # Brackets) button. Bisection-with-doubling-
                    # bootstrap search for the exposure time that lands
                    # the projection monitor's max-white capture at
                    # near-but-not-over per-channel sensor saturation.
                    #
                    # Algorithm shape:
                    #   1. Capture at initial exposure guess.
                    #   2. If per-channel max < target_low: too dark,
                    #      double exposure. If > target_high: too
                    #      bright, halve. Repeat until we bracket
                    #      (one undershoot AND one overshoot seen).
                    #      This is the "doubling-bootstrap" phase -
                    #      it converges fast even when the initial
                    #      guess is wildly off.
                    #   3. Once bracketed, switch to bisection: try
                    #      the midpoint of the bracket, replace
                    #      whichever bound it passed.
                    #   4. Stop on convergence (in target range), OR
                    #      on max_iterations (safety net), whichever
                    #      comes first.
                    #
                    # We use per-channel max rather than mean because
                    # any single channel clipping is real data loss
                    # in BRK captures. See measure_centre_brightness
                    # docs for the cyan-capture cautionary tale.
                    initial_exposure = float(job_data.get('initial_exposure_s', 1.0))
                    target_low = float(job_data.get('target_low', 0.85))
                    target_high = float(job_data.get('target_high', 0.97))
                    max_iterations = int(job_data.get('max_iterations', 10))

                    # Clip threshold is now applied to MEAN, not
                    # per-channel max. Default 1.5 means "effectively
                    # never fires" - the safety net is preserved as
                    # a config knob for users with calibrated screens
                    # who want hard per-mean-saturation protection,
                    # but for the normal case we trust the
                    # target_high to be the soft upper bound.
                    clip_threshold = float(job_data.get('clip_threshold', 1.5))

                    # Defensive: target_low must be < target_high or
                    # convergence is impossible. We don't crash here -
                    # log and clamp - because the targets come from
                    # the user via the UI and we don't want a typo to
                    # take down the engine. Clamping to a known-safe
                    # range lets the user see "ACB still ran somehow"
                    # in the preview and figure out what they did.
                    if target_low >= target_high:
                        log_audit(f"ACB | Invalid targets ({target_low}, {target_high}), clamping to defaults")
                        target_low, target_high = 0.85, 0.97

                    # Capture the WB values used for this calibration.
                    # We stamp these into calibration.json so future
                    # readers (and future-me) can see what conditions
                    # t_peak was measured under. If the user changes
                    # WB without recalibrating, the stale stamp is
                    # the only clue that t_peak no longer matches
                    # current sensor behaviour.
                    awb_r = float(job_data.get('awb_r', 1.0))
                    awb_b = float(job_data.get('awb_b', 1.0))
                    gain = float(job_data.get('gain', 1.0))
                    cam_res = job_data.get('cam_res', '2028x1520')

                    log_audit(
                        f"ACB | Start | initial={initial_exposure:.3f}s "
                        f"target=[{target_low:.2f}, {target_high:.2f}] "
                        f"clip={clip_threshold:.2f} "
                        f"max_iter={max_iterations} "
                        f"WB=(R={awb_r:.2f}, B={awb_b:.2f})"
                    )

                    # Convergence state. The bracket bounds start as
                    # None - we don't know either one until we've
                    # actually overshot/undershot. Once both are
                    # populated, we're in bisection phase.
                    low_bound = None    # exposure we know is too low (per_channel_max < target_low)
                    high_bound = None   # exposure we know is too high (per_channel_max > target_high)
                    current_exposure = initial_exposure
                    last_measurement = None
                    converged = False

                    # The single capture-and-measure routine, lifted
                    # into a closure so the iteration loop stays
                    # readable. Returns the dict form of
                    # measure_centre_brightness so we have access to
                    # per_channel_max as well as the per-channel
                    # diagnostic values.
                    def _capture_and_measure(exp_s):
                        ctx.screen.use()
                        ctx.clear(1.0, 1.0, 1.0, 1.0)
                        pygame.display.flip()

                        total_ms = exp_s * 1000.0
                        buf_f = "/tmp/vop_acb_buf.dng"
                        cam_proc = hw.trigger_capture(
                            buf_f,
                            total_ms,
                            gain, awb_r, awb_b, cam_res,
                        )
                        hw.wait_for_sensor_prime()
                        time.sleep(total_ms / 1000.0)
                        cam_proc.wait()

                        return cutil.measure_centre_brightness(
                            buf_f, static_dir, return_dict=True
                        )

                    for iteration in range(1, max_iterations + 1):
                        m = _capture_and_measure(current_exposure)
                        last_measurement = m
                        pcm = m['per_channel_max']
                        mean_b = m['mean']
                        r, g, b = m['channel_maxes']

                        log_audit(
                            f"ACB | Iter {iteration}/{max_iterations} | "
                            f"exp={current_exposure:.4f}s | "
                            f"mean={mean_b:.4f} | "
                            f"per_ch_max={pcm:.4f} | "
                            f"channels=(R={r:.3f}, G={g:.3f}, B={b:.3f})"
                        )

                        # Decision tree (in priority order):
                        #
                        #   1. mean above clip_threshold? Hard back
                        #      off - the entire patch is saturated,
                        #      not just one channel. This is genuine
                        #      "too bright". Clip threshold default
                        #      is high (1.5) so this rarely fires; it
                        #      exists for the pathological case where
                        #      something has gone very wrong upstream.
                        #   2. mean < target_low? Too dark - push
                        #      exposure up.
                        #   3. mean > target_high? Too bright - back
                        #      off (but no clipping, just over-target).
                        #   4. Otherwise: converged. Mean is in the
                        #      target range.
                        #
                        # Per-channel clipping is intentionally NOT a
                        # stop condition. The reasoning: on a screen
                        # with a WB-tilted white point (i.e. all
                        # consumer LCDs, including yours), the
                        # brightest channel saturates first when the
                        # screen is displaying max white. That's a
                        # property of the screen, not data loss in
                        # any meaningful sense - the user can't make
                        # the screen brighter, and BRK brackets are
                        # going to display source slices that map to
                        # the screen's available range regardless. We
                        # log per-channel clipping for diagnostic
                        # purposes so the user can see WB tilt at a
                        # glance, but it does not affect convergence.
                        #
                        # If a user genuinely wants ACB to back off
                        # at the first per-channel clip (e.g. for a
                        # custom calibration scenario where the screen
                        # white point has somehow been pre-balanced),
                        # they can set clip_threshold to something
                        # like 0.99 manually. Default is 1.5 = "never
                        # fires for normal hardware."
                        if mean_b >= clip_threshold:
                            is_too_bright = True
                            log_audit(f"ACB | Iter {iteration}: MEAN CLIPPING "
                                      f"(mean={mean_b:.4f} >= {clip_threshold})")
                        elif mean_b < target_low:
                            is_too_bright = False
                        elif mean_b > target_high:
                            is_too_bright = True
                        else:
                            converged = True
                            clipped_channels = [
                                ch for ch, v in zip('RGB', (r, g, b))
                                if v >= 0.99
                            ]
                            clip_note = (
                                f" (info: {','.join(clipped_channels)} "
                                f"at-or-above 0.99)"
                                if clipped_channels else ""
                            )
                            log_audit(
                                f"ACB | Converged at {current_exposure:.4f}s "
                                f"(mean={mean_b:.4f}, per_ch_max={pcm:.4f}) "
                                f"after {iteration} iters{clip_note}"
                            )
                            break

                        # Bracket update. Same math as before, just
                        # driven by the is_too_bright flag from the
                        # decision tree above.
                        if is_too_bright:
                            high_bound = current_exposure
                            if low_bound is None:
                                current_exposure = current_exposure / 2.0
                            else:
                                current_exposure = (low_bound + high_bound) / 2.0
                        else:
                            low_bound = current_exposure
                            if high_bound is None:
                                current_exposure = current_exposure * 2.0
                            else:
                                current_exposure = (low_bound + high_bound) / 2.0
                    # Loop ended either by convergence (break) or by
                    # exhausting max_iterations. Both write a result
                    # to calibration.json - the converged flag tells
                    # the user (and any future automation) which
                    # happened.
                    if not converged:
                        log_audit(
                            f"ACB | DID NOT CONVERGE after {max_iterations} iters. "
                            f"Last exposure: {current_exposure:.4f}s, "
                            f"per_ch_max: {last_measurement['per_channel_max']:.4f}. "
                            f"Result written but flagged as non-converged."
                        )

                    cstore.save(static_dir, {
                        't_peak': current_exposure,
                        't_peak_meta': {
                            'converged': converged,
                            'mean': last_measurement['mean'],
                            'per_channel_max': last_measurement['per_channel_max'],
                            'channel_maxes': list(last_measurement['channel_maxes']),
                            'iterations_used': iteration,
                            'target_low': target_low,
                            'target_high': target_high,
                            'clip_threshold': clip_threshold,
                            'awb_r': awb_r,
                            'awb_b': awb_b,
                            'gain': gain,
                        }
                    })

                    log_audit(f">>> T_PEAK: {current_exposure:.6f}s "
                              f"(converged={converged}) <<<")
                              
                elif task == 'measure_peak_black':
                    # Calibration page: "Include black level
                    # measurement" checkbox companion to ACB. Captures
                    # at a supplied exposure time (intended to be the
                    # T_peak that ACB just converged on) but with the
                    # projection monitor showing pure black instead of
                    # full white. The captured centre-patch mean tells
                    # us the noise floor BRK shadow brackets will sit
                    # on top of at T_peak exposures.
                    #
                    # We pass exposure_s as a parameter rather than
                    # reading t_peak from calibration.json directly.
                    # Two reasons:
                    #   1. Looser coupling - this task does not need
                    #      to know what "T_peak" means as a concept,
                    #      it just measures black at whatever exposure
                    #      it is given.
                    #   2. Future flexibility - lets us re-use the
                    #      same task for any future calibration that
                    #      wants to know the noise floor at a specific
                    #      exposure time (e.g. a "what does black
                    #      look like at MY normal SSS exposures?"
                    #      diagnostic).
                    # The frontend sequencer is responsible for
                    # pulling the just-measured t_peak from
                    # calibration.json after ACB completes and
                    # passing it here.
                    exposure_s = float(job_data.get('exposure_s', 1.0))
                    total_ms = exposure_s * 1000.0

                    awb_r = float(job_data.get('awb_r', 1.0))
                    awb_b = float(job_data.get('awb_b', 1.0))
                    gain = float(job_data.get('gain', 1.0))
                    cam_res = job_data.get('cam_res', '2028x1520')

                    log_audit(
                        f"Calibration | Peak Black Measurement | "
                        f"exp={exposure_s:.4f}s | "
                        f"WB=(R={awb_r:.2f}, B={awb_b:.2f})"
                    )

                    # Draw black across the entire projection monitor.
                    # Same approach as measure_noise - we clear the
                    # framebuffer to (0, 0, 0) and let the panel
                    # produce whatever its physical "black" actually
                    # is. That's the measurement we want: what does
                    # the camera see when the screen is doing its
                    # darkest? Any stray room light, panel backlight
                    # bleed, sensor dark current at this exposure
                    # time - it all rolls into this one number.
                    ctx.screen.use()
                    ctx.clear(0.0, 0.0, 0.0, 1.0)
                    pygame.display.flip()

                    buf_f = "/tmp/vop_acb_black_buf.dng"
                    cam_proc = hw.trigger_capture(
                        buf_f,
                        total_ms,
                        gain, awb_r, awb_b, cam_res,
                    )
                    hw.wait_for_sensor_prime()
                    time.sleep(total_ms / 1000.0)
                    cam_proc.wait()

                    # We want the dict form so we have per-channel
                    # info in the audit log - lets the user see if
                    # one channel has a noticeably hotter dark current
                    # than the others, which is a useful diagnostic
                    # for sensor warmup or stray-light issues.
                    m = cutil.measure_centre_brightness(
                        buf_f, static_dir, return_dict=True
                    )
                    floor = m['mean']
                    r, g, b = m['channel_maxes']

                    log_audit(
                        f"ACB | Black floor at {exposure_s:.4f}s: "
                        f"mean={floor:.6f} | "
                        f"channels=(R={r:.4f}, G={g:.4f}, B={b:.4f})"
                    )

                    # Persist. We merge into the existing
                    # calibration.json - the t_peak block already
                    # written by ACB stays untouched, and we add
                    # the black floor info alongside.
                    cstore.save(static_dir, {
                        'black_floor_at_t_peak': floor,
                        'black_floor_meta': {
                            'exposure_s': exposure_s,
                            'mean': floor,
                            'channel_maxes': list(m['channel_maxes']),
                            'awb_r': awb_r,
                            'awb_b': awb_b,
                            'gain': gain,
                        }
                    })

                    log_audit(f">>> BLACK FLOOR: {floor:.6f} at {exposure_s:.4f}s <<<")
                
                elif task == 'measure_white_balance':
                    # Calibration page: "Auto White Balance".
                    # 
                    # Semi-auto WB gain finder, CLOSED LOOP on --awbgains.
                    # For DNGs, libraw's default WB comes from the
                    # AsShotNeutral that rpicam writes from --awbgains, so
                    # driving the camera gains directly changes the decoded
                    # TIFF. Verified on real captures: unity gain floors red
                    # to black; 3.3/1.42 lands the grey ramp neutral.
                    # 
                    # "Semi": runs once here, stores awb_r/awb_b, jobs reuse
                    # them every frame -> WB can't drift mid-render.
                    #
                    # GELS: grey is drawn with ctx.clear(), bypassing
                    # render_world / the timeline, so no PG/CG applies.
                    # 
                    # WB math (green is the reference, gain 1.0):
                    #   measured R = awb_r * raw_red_response
                    #   measured G =   1.0 * raw_green_response
                    #   measured B = awb_b * raw_blue_response
                    # To neutralise grey we want measured R == G == B, so:
                    #   awb_r_new = awb_r_cur * (G / R)
                    #   awb_b_new = awb_b_cur * (G / B)
                    # Linear, so this converges in 1-2 iterations.

                    grey_level          = float(job_data.get('grey_level', 0.5))
                    initial_exposure    = float(job_data.get('initial_exposure_s', 1.0))
                    # Safe per-channel-max window for the grey capture: above
                    # the noise floor, clear of clipping.
                    expo_low            = float(job_data.get('expo_target_low', 0.45))
                    expo_high           = float(job_data.get('expo_target_high', 0.70))
                    max_expo_iter       = int(job_data.get('max_iterations',12))
                    # WB convergence: stop when both channels are within tol
                    # of green, 0.01 = 1% ("accountant's truth").
                    tol                 = float(job_data.get('wb_tolerance', 0.01))
                    max_wb_iter         = int(job_data.get('max_wb_iterations', 6))
                    # A channel reading below this (normalized) is floored /
                    # noise-dominated: its G/ratio is meaningless. We bootstrap
                    # its gain up instead of dividing by ~zero.
                    noise_min           = float(job_data.get('wb_noise_min', 0.04)) 
                    bootstrap_factor    = float(job_data.get('wb_bootstrap', 4.0))

                    gain    = float(job_data.get('gain', 1.0))
                    cam_res = job_data.get('cam_res', '2028x1520')

                    # START FROM CURRENT GAINS, NOT UNITY. At 1.0/1.0 red
                    # floors to black on this screen(measured), so G/R would
                    # explode. The Main page hands us the user's working gains
                    # if absent, fall back to a sane non-unity guess rather
                    # than 1.0 so the very first capture has signal in red.
                    awb_r = float(job_data.get('awb_r', 3.0)) or 3.0
                    awb_b = float(job_data.get('awb_b', 1.4)) or 1.4

                    if expo_low >= expo_high:
                        log_audit(f"AWB | Invalid expo window, clamping")
                        expo_low, expo_high = .45, 0.70
                    
                    log_audit(
                        f"AWB | Start | grey={grey_level:.2f} "
                        f"init_awb=(R={awb_r:.3f},B={awb_b:.3f}) "
                        f"expo_window=[{expo_low:.2f},{expo_high:.2f}] "
                        f"tol={tol*100:.1f}% max_wb_iter={max_wb_iter}"
                    )

                    # SINGLE-CAPTURE PRIMITIVE.
                    # One grey capture at the CURRENT gains. Note awb_r/awb_b
                    # are read from the enclosing scope each call, so as the
                    # loop updates them, captures track. Returns the dict form
                    # for per-channel values. Writes probe_live.jpg too.
                    def _measure_grey(exp_s):
                        ctx.screen.use()
                        ctx.clear(grey_level, grey_level, grey_level, 1.0)
                        pygame.display.flip()
                        total_ms = exp_s * 1000.0
                        buf_f = "/tmp/vop_wb_buf.dng"
                        cam_proc = hw.trigger_capture(
                            buf_f, total_ms, gain, awb_r, awb_b, cam_res,
                        )
                        hw.wait_for_sensor_prime()
                        time.sleep(total_ms / 1000.0)
                        cam_proc.wait()
                        return cutil.measure_centre_brightness(
                            buf_f, static_dir, return_dict=True
                        )

                    # AVERAGING WRAPPER.
                    # Average N captures of the SAME grey to pull the per-frame
                    # measurement noise down. Noise falls ~as 1/sqrt(N), so 4
                    # frames roughly halves it. We only need this for the
                    # verdict: at convergence the true WB error (~0.3-0.5%) is
                    # smaller than single-frame noise (~0.65%), so a one-shot
                    # CONFIRM is a coin flip against a 1% tolerance. Averaging
                    # makes PASS mean "actually balanced" instead of "lucky
                    # frame". Calls the primitive above N times and means the
                    # per-channel values; per_channel_max is kept as the worst
                    # (max) seen, since that's a clipping guard not an average.
                    def _measure_grey_avg(exp_s, n):
                        rs = gs = bs = 0.0
                        pcm = 0.0
                        n = max(1, n)
                        for _ in range(n):
                            m = _measure_grey(exp_s)
                            r, g, b = m['channel_maxes']
                            rs += r; gs += g; bs += b
                            pcm = max(pcm, m['per_channel_max'])
                        return {'channel_maxes': (rs / n, gs / n, bs / n),
                                'per_channel_max': pcm}
                    
                    # --- PHASE 1: exposure search (ACB-shaped bisection. run
                    # at the starting gains so all channels have signal).---
                    low_bound = high_bound = None
                    current_exposure = initial_exposure
                    last = None
                    expo_found = False
                    for it in range(1, max_expo_iter + 1):
                        m = _measure_grey(current_exposure)
                        last = m
                        pcm = m['per_channel_max']
                        r, g, b = m['channel_maxes']
                        log_audit(f"AWB | Expo {it}/{max_expo_iter} | "
                                  f"exp={current_exposure:.4f}s pcm={pcm:.4f} "
                                  f"(R={r:.3f},G={g:.3f},B={b:.3f})")
                        if pcm < expo_low:
                            low_bound = current_exposure
                            current_exposure = (current_exposure * 2.0
                                if high_bound is None
                                else(low_bound + high_bound) / 2.0)
                        elif pcm > expo_high:
                            high_bound = current_exposure
                            current_exposure = (current_exposure / 2.0
                                if low_bound is None
                                else (low_bound + high_bound) / 2.0)
                        else:
                            expo_found = True
                            break
                    log_audit(f"AWB | Exposure {'found' if expo_found else 'NOT found'}: "
                              f"{current_exposure:.4f}s")
                    
                    # --- PHASE 2: WB closed loop at the converged exposure. ---
                    eps = 1e-6
                    wb_converged = False
                    for it in range(1, max_wb_iter +1):
                        m = _measure_grey(current_exposure)
                        r, g, b = m['channel_maxes']

                        # Bootstrap any floored channel: if it's in the noise,
                        # G/ratio is garbage, so just multiply it's gain up by a
                        # fixed factor and try again rather than computing a 
                        # ratio. (This is what rescues a near-unity start.)
                        floored = False
                        if r < noise_min:
                            awb_r *= bootstrap_factor; floored = True
                        if b < noise_min:
                            awb_b *= bootstrap_factor; floored = True
                        if floored:
                            log_audit(f"AWB | WB {it}: channel floored "
                                      f"(R={r:.4f},B={b:.4f} -> bootstrap "
                                      f"awb=(R={awb_r:.3f},B={awb_b:.3f})")
                            continue

                        res_r = abs(r - g) / max(g, eps)
                        res_b = abs(b - g) / max(g, eps)
                        log_audit(f"AWB | WB {it}/{max_wb_iter} | "
                                  f"awb=(R={awb_r:.3f},B={awb_b:.3f}) | "
                                  f"residual R={res_r*100:+.2f}% B={res_b*100:+.2f}%")
                        if res_r <= tol and res_b <= tol:
                            wb_converged = True
                            break
                        
                        # DAMPED green-referenced correction.
                        #
                        # WHY: the decoded channel ratios respond to an awbgain
                        # change with a LOOP GAIN of ~2.5 - a 10% change in
                        # awb_r moves the measured R/G by ~30% - because
                        # rawpy.postprocess runs the camera colour matrix, so
                        # green is NOT a fixed reference and the ratio over-
                        # shoots. An undamped step (the old code) therefore
                        # oscillates and runs away to magenta. We under-relax
                        # by raising the ratio to a power < 1: with damping ~0.4
                        # the effective loop gain is ~1 (near-Newton), so it
                        # settles in 1-2 iterations.
                        #
                        # Tuning: if you still see the residual bounce/grow,
                        # LOWER wb_damping (e.g. 0.3 -> smaller, safer steps).
                        # If it converges but too slowly, raise it toward 0.5.
                        damping = float(job_data.get('wb_damping', 0.4))
                        fr = (g / max(r, eps)) ** damping
                        fb = (g / max(b, eps)) ** damping

                        # Tighter per-step clamp than the old [0.5, 2.0]. With
                        # damping the steps are small near convergence, so this
                        # is only a guard against one wild measurement. The old
                        # wide clamp let the oscillation build amplitude (you
                        # can see it hit exactly 0.5 in run 2); keep it near 1.
                        fr = min(max(fr, 0.7), 1.4)
                        fb = min(max(fb, 0.7), 1.4)

                        awb_r = min(max(awb_r * fr, 0.25), 16.0)
                        awb_b = min(max(awb_b * fb, 0.25), 16.0)

                    # --- Phase 3: confirm. Capture grey at the FINAL gains and
                    # report how neutral it actually came out. This is the real
                    # accountant's truth: not a predicted residual, but what the
                    # camera genuinely produces at the gains we're about to 
                    # store. (no digital multiply needed - the gains are baked
                    # into this capture via --awbgains.) ---
                    # Averaged confirm: the verdict is the one place precision
                    # matters more than speed. Frames count from wb_confirm_avg
                    # (default 4); set to 1 to restore single-frame behaviour.
                    wb_confirm_avg = int(job_data.get('wb_confirm_avg', 4))
                    mc = _measure_grey_avg(current_exposure, wb_confirm_avg)
                    rc, gc, bc = mc['channel_maxes']
                    res_r = abs(rc - gc) / max(gc, eps)
                    res_b = abs(bc - gc) / max(gc, eps)
                    passed = (res_r <= tol) and (res_b <= tol)
                    log_audit(f"AWB | CONFIRM | awb=(R={awb_r:.3f},B={awb_b:.3f}) "
                              f"residual R={res_r*100:+.2f}% B={res_b*100:+.2f}% "
                              f"-> {'PASS' if passed else 'FAIL'}")
                    
                    # Persist as awb_r/awb_b - the same keys jobs already use
                    cstore.save(static_dir, {
                        'awb_r': awb_r,
                        'awb_b': awb_b,
                        'wb_meta': {
                            'exposure_s': current_exposure,
                            'grey_level': grey_level,
                            'confirm_channels': [rc, gc, bc],
                            'confirm_residual_r': res_r,
                            'confirm_residual_b': res_b,
                            'tolerance': tol,
                            'passed': passed,
                            'wb_converged': wb_converged,
                            'exposure_found': expo_found,
                            'gain': gain,
                        }
                    })
                    log_audit(f">>> WB: awb_r={awb_r:.4f} awb_b={awb_b:.4f} "
                              f"(passed={passed}) <<<")
                              
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
                    # Capture the dark frame for hot-pixel detection.
                    #
                    # Shutter argument is plain total_ms - do NOT add
                    # PRIME_WAIT_MS. trigger_capture already bakes the prime
                    # delay into rpicam-still's `-t` flag, and the
                    # wait_for_sensor_prime() call below mirrors it on the
                    # Python side. The integration time we want is total_ms
                    # (frame exposure + the 1000ms header/tail pad) - the
                    # same time a real exposure of this frame uses.
                    #
                    # The old code added PRIME_WAIT_MS, stretching the
                    # shutter by 1.5s. For hot-pixel mapping that's not
                    # merely a logged-vs-actual mismatch (as in #187's
                    # noise floor): a longer dark frame lets MORE pixels
                    # drift past the hot threshold, so we were mapping
                    # pixels that only misbehave at exposures we never
                    # actually shoot. Matching the real integration time
                    # maps the pixels that are genuinely hot at the
                    # exposures our jobs use. (sibling of issue #187)
                    cam_proc = hw.trigger_capture(buf_f, total_ms, job_data.get('gain', 1.0),
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
            
            if idle_x <= -0.7 or idle_x >= 0.7: idle_dx *= -1
            if idle_y <= -0.5 or idle_y >= 0.5: idle_dy *= -1

            # --- CLEAR BEFORE DRAW (idle frame) ---
            # The idle branch never cleared, so with DOUBLEBUF every flip()
            # swapped to a back buffer still holding an OLDER idle frame and
            # we drew the logo on top of it. Because the logo uses an "over"
            # blend (SRC_ALPHA / ONE_MINUS_SRC_ALPHA below), only its opaque
            # pixels overwrite - transparent areas keep whatever was already
            # there - so the logo's swept path accumulated into the white
            # smear-blocks now visible through the live feed.
            #
            # Bind the default framebuffer first (a prior task may have left
            # a BiPack FBO bound) and clear to opaque black so each idle
            # frame starts clean. Slice 2's alignment targets render in this
            # same branch and rely on this clear too.
            ctx.screen.use()
            ctx.clear(0.0, 0.0, 0.0, 1.0)

            # --- CALIBRATION TARGETS MODE (issue #198) ---
            # While the framing tool is active, vop.py drops CAL_TARGETS_FILE.
            # As long as it exists we draw the alignment/focus targets instead
            # of the bouncing logo, so the operator - watching the live feed -
            # can square the camera to the panel and dial in focus.
            #
            # This is a DISPLAY mode only; it never touches the camera, so the
            # rpicam-vid feed keeps running right alongside it (the whole point
            # is that you see these targets THROUGH the feed).
            #
            # We render, flip, throttle, then `continue` so the logo/IP block
            # below is skipped entirely while targets are showing.
            if os.path.exists(CAL_TARGETS_FILE):
                # Opaque procedural geometry on a freshly-cleared black frame,
                # so no alpha compositing is wanted. The exposure path can
                # leave BLEND enabled on a multiplicative func; disabling it
                # here guarantees the crosshairs/moire draw at full strength.
                ctx.disable(moderngl.BLEND)
                # Panel aspect -> circular centre target on 3:2 / 16:9 panels.
                # float() guards against any chance of integer division.
                cal_prog['u_aspect'].value = WIDTH / float(HEIGHT)
                cal_vao.render(moderngl.TRIANGLE_STRIP)
                pygame.display.flip()
                time.sleep(1 / 60)   # same 60fps throttle as the logo path
                continue

            # --- IDLE-SCREEN ALPHA BLENDING ---
            # The logo and IP textures are straight-alpha RGBA surfaces
            # (pygame's tostring("RGBA") gives non-premultiplied alpha).
            # Without blending, the GPU writes RGB and discards alpha, so a
            # texture whose transparent pixels carry white RGB (which is
            # exactly what font.render produces) paints as a solid white box.
            # Enabling SRC_ALPHA / ONE_MINUS_SRC_ALPHA makes alpha=0 pixels
            # contribute nothing, so only the glyphs (and logo marks) show.
            ctx.enable(moderngl.BLEND)
            # blend_func MUST be set explicitly here: the exposure path leaves
            # it at (DST_COLOR, ZERO) for its multiplicative pass and never
            # resets it, so we'd otherwise inherit that multiply and the text
            # would vanish against the black screen after the first job runs.
            ctx.blend_func = (moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA)

            mvp = np.eye(4, dtype='f4')
            # The trailing divisor is the SCREEN aspect, used to counter the
            # NDC stretch that happens on non-square screens. Reading from 
            # WIDTH/HEIGHT (set during EDID discovery) keeps the logo 
            # correctly-proportioned on any panel - 16:9, 3:2, UHD, etc.
            mvp[0, 0] = 0.4 * asp_logo / (WIDTH / HEIGHT)
            mvp[1, 1] = 0.4
            mvp[3, 0] = idle_x
            mvp[3, 1] = idle_y

            prog['mvp'].write(mvp.tobytes())
            prog['filter_color'].write(np.array([1.0, 1.0, 1.0], dtype='f4'))
            
            # Ensure the idle logo is never subjected to a user's monochrome job setting
            prog['mono_mode'].value = False 

            tex_logo.use(0)
            vao.render(moderngl.TRIANGLE_STRIP)

            # --- IDLE SCREEN IP DISPLAY ---
            # Periodically rebuild the IP texture so a DHCP address
            # change is eventually reflected. Cheap: only every
            # IP_REFRESH_FRAMES, and build_ip_texture returns fast.
            ip_refresh_counter += 1
            if ip_refresh_counter >= IP_REFRESH_FRAMES:
                ip_refresh_counter = 0
                new_tex, new_asp = build_ip_texture(ctx)
                # Only swap in a successful build. If the rebuild failed
                # (e.g. file briefly unreadable) we keep showing the last
                # good texture rather than blanking the address.
                if new_tex is not None:
                    if tex_ip is not None:
                        tex_ip.release()   # free the old GPU texture
                    tex_ip, asp_ip = new_tex, new_asp

            # Render the IP quad below the logo, only if we have one.
            if tex_ip is not None:
                ip_mvp = np.eye(4, dtype='f4')

                # ---- SIZE: width-driven, not height-driven ----
                # The old code fixed the text HEIGHT and let WIDTH follow the
                # text aspect ratio. Because the address string is long, its
                # aspect ratio is large, so a fixed height produced a quad
                # wider than the entire screen.
                #
                # Instead we fix the WIDTH to a small fraction of the screen
                # and derive the height from the aspect ratio. Now any address,
                # long or short, occupies the same modest width and just gets a
                # proportionally small height.
                #
                # ip_half_w is the quad's NDC half-width (base quad spans
                # -1..1), so 0.30 => 0.60 NDC wide => ~30% of screen width.
                # This is the main knob for "how big is the address"; shrink it
                # to make the text smaller.
                ip_half_w = 0.30
                ip_mvp[0, 0] = ip_half_w
                # Height = width * screen_aspect / text_aspect. This is the old
                # width formula solved for height instead, so glyphs stay
                # undistorted on any panel (16:9, 3:2, UHD...).
                ip_mvp[1, 1] = ip_half_w * (WIDTH / HEIGHT) / asp_ip

                # ---- POSITION: fully below the logo, never overlapping ----
                # X tracks the logo so the address bounces along with it.
                ip_mvp[3, 0] = idle_x
                # Y: drop from the logo CENTER (idle_y) by the logo's real NDC
                # half-height, then a small gap, then a further half of THIS
                # quad's height so the text's TOP edge clears the logo's BOTTOM.
                # The old 0.30 assumed the logo was half as tall as it is, which
                # is why the address sat over the logo's lower edge.
                logo_half_h = 0.4          # MUST match the logo's mvp[1,1] above
                gap = 0.06                 # blank space between logo and address
                ip_mvp[3, 1] = idle_y - logo_half_h - gap - ip_mvp[1, 1]

                prog['mvp'].write(ip_mvp.tobytes())
                # White, never monochrome-filtered - same treatment as
                # the logo so a job's mono setting can't tint the address.
                prog['filter_color'].write(np.array([1.0, 1.0, 1.0], dtype='f4'))
                prog['mono_mode'].value = False

                tex_ip.use(0)
                vao.render(moderngl.TRIANGLE_STRIP)
            # --- END IP DISPLAY ---

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