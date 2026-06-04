"""
VOP Module:     vop.py
Location:       vop.py
Description:    Main Entry Point. Flask Web Server.               
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
import subprocess
import logging
import cv2
import glob
import math
import socket
import time
import numpy as np  # for 16-bit → 8-bit reduction in /cam_probe
from flask import Flask, jsonify, request, render_template, send_from_directory, send_file, Response

# Append the modules directory to the system path for local imports
sys.path.append(os.path.join(os.path.dirname(__file__), "modules"))

# Calibration store for reading the persisted hardware-calibration
# values. Used by the /calibration_state GET route to expose the
# current state to the frontend.
import calibration_store as cstore
import interpolator  # for resolving per-gate JK playheads in /status and /cam_probe

# Live MJPEG framing/focus feed for the Calibration page (issue #198).
# Owns its own rpicam-vid process; see the single-owner camera note in
# dispatch_engine where we stop it before any capture.
import camera_feed

# Suppress default Flask HTTP request logging to keep the terminal output clean for audit logs
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
app = Flask(__name__)

# Absolute path resolutions for standard system directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ_MAG_DIR = os.path.join(BASE_DIR, "ProjMag")
# Renamed from PROJ_BIPACK_DIR. We now have two numbered bipack layers.
PROJ_BIPACK1_DIR = os.path.join(BASE_DIR, "ProjBiPack1")
PROJ_BIPACK2_DIR = os.path.join(BASE_DIR, "ProjBiPack2")
CAM_MAG_DIR = os.path.join(BASE_DIR, "CamMag")
CURRENT_JOB_FILE = os.path.join(BASE_DIR, "current_job.json")

# Inter-Process Communication (IPC) file for the persistent engine daemon
# The Flask server writes JSON payloads here; engine.py polls this file to execute commands
COMMAND_FILE = "/tmp/vop_cmd.json" 

# Sentinel the engine's idle loop polls to show the framing/focus targets
# (issue #198). The two routes below create/remove it. MUST match the path
# CAL_TARGETS_FILE in modules/engine.py.
CAL_TARGETS_FILE = "/tmp/vop_cal_targets"

VOP_VERSION ="0.10.0"

# Initialize required directory structure on boot if missing
PRORES_DIR = os.path.join(BASE_DIR, "ProRes")
for d in [PROJ_MAG_DIR, PROJ_BIPACK1_DIR, PROJ_BIPACK2_DIR, CAM_MAG_DIR, os.path.join(BASE_DIR, "WorkPrints"), PRORES_DIR]:
    os.makedirs(d, exist_ok=True)

# Single global reference for the persistent GPU engine subprocess

engine_process = None
prores_process = None

def ensure_engine_running():
    """
    Checks the execution state of the persistent engine daemon. 
    If terminated, it clears any stale IPC commands and initializes a new subprocess.
    """
    global engine_process
    # Check if process is uninitialized or if poll() returns an exit code (meaning it died)
    if engine_process is None or engine_process.poll() is not None:
        print("[VOP SERVER] Launching persistent GPU Engine...")
        
        # Clear residual command files to prevent unintended execution on initialization
        if os.path.exists(COMMAND_FILE):
            os.remove(COMMAND_FILE)
            
        engine_script = os.path.join(BASE_DIR, "modules", "engine.py")
        engine_process = subprocess.Popen([sys.executable, engine_script])

def probe_video_frame_count(filepath):
    """
    Returns the frame count of a video file as an int, or None if the
    count cannot be determined.
    
    Used as a pre-flight check before invoking process_video_ingestion
    on long videos. Catching an oversized reel here avoids minutes of
    wasted ffmpeg work plus disk I/O - the user gets an immediate error
    instead of a silent failure deep in a sequence.
    
    Strategy:
      1. Cheap path: read the container's nb_frames metadata. This is
         instant (header-only) and accurate for MOV/MP4/ProRes which
         write the count at encode time.
      2. Fallback: use ffprobe -count_frames, which actually decodes
         the entire stream. Slow (~seconds for a multi-minute reel)
         but unavoidable for streaming-friendly containers like MKV
         that often report nb_frames=N/A.
    
    Returns int frame count on success, or None on any failure (no
    ffprobe binary, no video stream, malformed file, etc.). Callers
    should treat None as "couldn't verify" and decide whether to
    proceed cautiously or reject.
    """
    # Step 1: cheap header read. -v error suppresses ffprobe's noisy
    # banner so we can parse the single line of output cleanly.
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error",
             "-select_streams", "v:0",
             "-count_packets", "-show_entries", "stream=nb_read_packets",
             "-of", "csv=p=0", filepath],
            check=True, capture_output=True, text=True, timeout=10
        )
        raw = result.stdout.strip()
        if raw and raw != "N/A":
            return int(raw)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, ValueError) as e:
        # Fall through to the slow path. Log so the user knows why
        # ingestion takes a few seconds before the real work starts.
        print(f"[VOP SERVER] Frame-count header read failed ({e}); "
              f"falling back to full stream count.")
    
    # Step 2: slow but reliable. -count_frames forces a full decode
    # to populate nb_read_frames. Used when the container's nb_frames
    # is N/A or when step 1 raised. Capped with a generous timeout so
    # a pathological input can't hang the upload route forever.
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error",
             "-select_streams", "v:0",
             "-count_frames", "-show_entries", "stream=nb_read_frames",
             "-of", "csv=p=0", filepath],
            check=True, capture_output=True, text=True, timeout=120
        )
        raw = result.stdout.strip()
        if raw and raw != "N/A":
            return int(raw)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, ValueError) as e:
        print(f"[VOP SERVER] Frame-count full scan failed ({e}). "
              f"Cannot verify reel length.")
    
    return None

def probe_video_dimensions(filepath):
    """
    Returns (width, height) of the first video stream in `filepath`,
    or None if dimensions cannot be determined.
    
    Used by upload_cam_mag to compute the recommended PAR. Cheap
    operation - reads the container header only, doesn't decode any
    frames. Returns None on any failure (no ffprobe, no video stream,
    malformed file) and callers should treat None as "no PAR
    recommendation available" rather than aborting the upload.
    """
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error",
             "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x", filepath],
            check=True, capture_output=True, text=True, timeout=10
        )
        # Output is "WxH" on one line, e.g. "1280x720"
        raw = result.stdout.strip()
        if 'x' in raw:
            w_str, h_str = raw.split('x')
            return (int(w_str), int(h_str))
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired,
            FileNotFoundError, ValueError) as e:
        print(f"[VOP SERVER] Video dimension probe failed ({e}); "
              f"PAR recommendation will be unavailable.")
    return None

def process_video_ingestion(filepath, target_dir, filename_prefix="", start_number=0, pix_fmt_override=None, fit_to_monitor_in_camera=None):
    """
    [signature note]
    filename_prefix : str, default "". Prepended to the numeric pattern,
                      e.g. "latent_" produces latent_0001.tif. Empty
                      string keeps the legacy 0000.tif behavior used by
                      Proj Mag and BiPack uploads.
    start_number    : int, default 0. ffmpeg's -start_number value.
                      Cam Mag uses 1 because engine.py's playhead is
                      1-indexed (latent_0001.tif is the first frame),
                      while Proj Mag stays at 0 for backward compat.
    pix_fmt_override: str or None, default None. When set, bypasses the
                      job-mode-aware logic and uses this pix_fmt directly.
                      Cam Mag passes 'rgb48le' unconditionally because
                      its target is the LIME pipeline which is 16-bit
                      throughout, and unlike Proj Mag textures there's
                      no moderngl 8-bit constraint to worry about.
    fit_to_monitor_in_camera : dict or None, default None.
                      Cam Mag passes a dict of:
                          {
                              "cam_w":     int, camera frame width,
                              "cam_h":     int, camera frame height,
                              "monitor_w": int, projection monitor width,
                              "monitor_h": int, projection monitor height,
                          }
                      and the ingest then:
                        1. non-uniformly stretches every input frame to
                           a sub-rectangle whose ASPECT matches the
                           projection monitor (monitor_w / monitor_h),
                           sized to the largest such rectangle that fits
                           inside the camera frame (cam_w x cam_h),
                        2. letterboxes that monitor-aspect rectangle
                           with pure black to fill the full camera frame.
                      The non-uniform stretch is intentional - it bakes
                      the input video's aspect onto the monitor surface
                      as if the user had played the video on the monitor
                      and pointed the camera at it. The user then sets
                      par_x = input_aspect / monitor_aspect in Hardware
                      Constants to unsqueeze at composite time. The
                      letterbox fill is black because that simulates
                      what a real camera would see around a physical
                      monitor in a dark room - geometrically equivalent
                      to a true optical-printer capture.
                      PM / BP / BiPack pass None and behave as before
                      (no scaling, no letterbox).
    """

    ext = os.path.splitext(filepath)[1].lower()
    video_exts = ['.mp4', '.mov', '.avi', '.mkv', '.webm']

    if ext not in video_exts:
        return  # Stills pass through untouched, same as before

    # --- Determine target bit depth from current job mode -------------
    # We read CURRENT_JOB_FILE rather than receiving the mode as an arg
    # because every caller of this function (PM, BP1, BP2 upload routes)
    # would otherwise need plumbping. Reading the file once per upload is 
    # cheap and keeps the call sites unchanged.
    # Cam Mag explicitly passes 'rgb48le' to skip the mode-aware logic
    # below. The mode-awareness exists because moderngl's Proj Mag /
    # BiPack texture pipeline used to choke on 16-bit input in SSS/MDS
    # mode. Cam Mag's frames never become textures - they're consumed by
    # cv2.imread inside LIME, which handles 16-bit natively - so the
    # constraint doesn't apply and we want the full bit depth.
    if pix_fmt_override is not None:
        pix_fmt = pix_fmt_override
    else:
        pix_fmt = "rgb24" # safe 8-bit default - won't crash smear pipelines
        try:
            if os.path.exists(CURRENT_JOB_FILE):
                with open(CURRENT_JOB_FILE, 'r') as jf:
                    job_mode = json.load(jf).get('smear_mode', 'SSS').upper()
                if job_mode == 'DRE':
                    # rgb48le = 16-bit RGB little-endian. Preserves the full
                    # tonal range of 10/12 bit source codecs (ProRes, DNxHR)
                    # into 16 bit TIFFs that the TextureManager will 
                    # consume natively.
                    pix_fmt = "rgb48le"
        except (json.JSONDecodeError, OSError) as e:
            # Don't fail the upload just because the job file is weird;
            # log it and fall back to the safe 8-bit path
            print(f"[VOP SERVER] WARN: Could not read job mode for ingestion "
                  f"({e}). Falling back to 8-bit rgb24.")
    
    print(f"[VOP SERVER] Video detected! Extracting {filepath} "
          f"to TIFF sequence (pix_fmt={pix_fmt})...")
    
    # Build the output pattern with the optional caller-supplied prefix.
    # PM / BP1 / BP2 pass "" so the result is plain "%04d.tif" - same as
    # before. Cam Mag passes "latent_" + start_number=1 so frames are
    # written as latent_0001.tif onward, matching exactly what
    # engine.py's execute path writes during a normal exposure run.
    # That uniformity is what lets the LIME / Cam Probe / ProRes render
    # code consume an ingested reel without any branching.
    output_pattern = os.path.join(target_dir, f"{filename_prefix}%04d.tif")
    
    # Base command - same as before for the no-scale path that PM / BP /
    # BiPack still use. We build the list and then conditionally insert
    # the scale filter, rather than building two parallel commands,
    # because the scale filter is the ONLY thing that varies between
    # the two call patterns. Keeping a single source of truth for the
    # rest of the args means future flags only need to be added once.
    cmd = [
        "ffmpeg", "-y", "-i", filepath,
        "-pix_fmt", pix_fmt,
        "-start_number", str(start_number),
        output_pattern
    ]
    
    # Conditional fit-and-letterbox for Cam Mag. The geometry:
    #
    #   Camera frame (cam_w x cam_h) is the FINAL latent dimensions.
    #     For 2028x1520 (Pi HQ half-res), aspect = 4:3 = 1.333.
    #
    #   Inside the camera frame, we carve out a CONTENT rectangle
    #   whose aspect matches the projection monitor.
    #     For a 2160x1440 monitor, aspect = 3:2 = 1.500.
    #
    #   That content rectangle is the LARGEST rectangle of the
    #   monitor's aspect that fits inside the camera frame:
    #     - width-bind if monitor is wider than camera: content_w =
    #       cam_w, content_h = cam_w / monitor_aspect
    #     - height-bind if monitor is taller: content_h = cam_h,
    #       content_w = cam_h * monitor_aspect
    #
    #   Input video gets stretched non-uniformly to content_w x
    #   content_h (whatever its source aspect was - the user fixes
    #   the resulting squeeze with PAR at composite time).
    #
    #   The space between the content rect and the camera frame
    #   gets padded with pure black, simulating the dark room around
    #   a physical monitor that an actual camera would capture.
    #
    # ffmpeg filtergraph implementing this:
    #   scale=CW:CH,pad=FW:FH:(FW-CW)/2:(FH-CH)/2:black
    # which scales to the content rect then centers it on a black
    # canvas of the camera frame's size.
    if fit_to_monitor_in_camera is not None:
        cam_w = int(fit_to_monitor_in_camera["cam_w"])
        cam_h = int(fit_to_monitor_in_camera["cam_h"])
        mon_w = int(fit_to_monitor_in_camera["monitor_w"])
        mon_h = int(fit_to_monitor_in_camera["monitor_h"])
        
        cam_aspect = cam_w / cam_h
        mon_aspect = mon_w / mon_h
        
        # Pick width-bind vs height-bind. If the monitor is WIDER
        # (larger aspect) than the camera, we width-bind: the
        # content's width = camera's width, but its height shrinks
        # to monitor-aspect. If the monitor is TALLER (smaller
        # aspect), we height-bind: content's height = camera's
        # height but width pillarboxes inward.
        if mon_aspect >= cam_aspect:
            # Width-bind: letterbox top/bottom
            content_w = cam_w
            content_h = int(round(cam_w / mon_aspect))
        else:
            # Height-bind: pillarbox left/right
            content_h = cam_h
            content_w = int(round(cam_h * mon_aspect))
        
        # Build the filter as a single comma-separated chain. ffmpeg
        # applies them left to right, so scale runs before pad.
        # Important: scale forces target dims with no aspect-preserve,
        # so input gets non-uniformly stretched to content rect. pad
        # then centers that on the cam-frame-sized black canvas.
        filter_chain = (
            f"scale={content_w}:{content_h},"
            f"pad={cam_w}:{cam_h}:"
            f"{(cam_w - content_w) // 2}:{(cam_h - content_h) // 2}:"
            f"black"
        )
        
        # Insert at position -1 (just before output_pattern). list.insert
        # shifts the output_pattern out by one slot, so the final order
        # remains [..., -vf, "scale=...,pad=...", output_pattern].
        cmd.insert(-1, "-vf")
        cmd.insert(-1, filter_chain)
        print(f"[VOP SERVER] Cam Mag ingest: input stretched to "
              f"{content_w}x{content_h} (monitor-aspect content rect), "
              f"letterboxed black into {cam_w}x{cam_h} camera frame.")
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("[VOP SERVER] Frame extraction complete.")
        os.remove(filepath)
    except subprocess.CalledProcessError as e:
        print(f"[VOP SERVER] CRITICAL: FFMPEG ingestion feiled: {e}")

def count_source_frames(directory):
    """
    Counts image frames in a media directory (PROJ_MAG_DIR, PROJ_BIPACK1_DIR, 
    or PROJ_BIPACK2_DIR).

    Used by /status to tell the web UI whether a layer holds a still image
    (1 frame or a video sequence (>1 frame)). The UI uses this to show or hide
    the JK Optical Printer (GATE/CAM/STP) inputs in the exposure sheets,
    since those columns are only meaningful when there's a sequence to traverse.
    """
    if not os.path.exists(directory):
        return 0
    valid_exts = ('.png', '.jpg', '.jpeg', '.tif', '.tiff')
    return len([f for f in os.listdir(directory) if f.lower().endswith(valid_exts)])


def resolve_gate_playheads(params, cam_frame):
    """
    Resolve the current frame sitting in every gate at a given CamMag frame,
    plus each gate's total frame count. Feeds the per-mag "####/####" readouts
    in the web UI (Cam Mag, Projection Mag, BiPack 1, BiPack 2).

    Two callers, same function:
      - /status (during a render): cam_frame is the frame being exposed, read
        from the engine heartbeat. Gives the live 1Hz readout.
      - /cam_probe (while scrubbing): cam_frame is the probed frame. Gives the
        at-rest "which frame is in each gate" readout.

    The source gates (pm / bp1 / bp2) don't move 1:1 with the CamMag frame -
    the JK Optical Printer CAM:STP timing means a gate can hold or step. So we
    ask interpolator.Timeline (a pure, side-effect-free parse of the job's
    keyframe tracks) where each layer's playhead lands. Cam Mag is the
    destination, not a source, so its current frame IS cam_frame - no walk.

    Returns: { 'cam': {'cur', 'total'}, 'pm': {...}, 'bp1': {...}, 'bp2': {...} }
    'cur' is a 1-based human frame number, clamped into [1, total] when a
    sequence is present and 0 when the gate is empty. The display formatting
    (leading zeros, the 0000 still-sentinel, ----/---- for empty) lives in the
    frontend so the look can evolve without touching this contract.
    """
    counts = {
        'cam': count_source_frames(CAM_MAG_DIR),
        'pm':  count_source_frames(PROJ_MAG_DIR),
        'bp1': count_source_frames(PROJ_BIPACK1_DIR),
        'bp2': count_source_frames(PROJ_BIPACK2_DIR),
    }

    def pack(cur, total):
        # Clamp the 1-based current into the real range when there's footage;
        # 0 for an empty gate (the frontend renders that as ----/----).
        cur = max(1, min(total, int(cur))) if total >= 1 else 0
        return {'cur': cur, 'total': total}

    gates = {'cam': pack(int(cam_frame), counts['cam'])}

    try:
        tl = interpolator.Timeline(params or {})
        for layer in ('pm', 'bp1', 'bp2'):
            # calculate_playhead_at returns a 0-based gate index; +1 to present
            # the first frame of a sequence as 0001 rather than 0000.
            gate0 = int(tl.calculate_playhead_at(int(cam_frame), layer=layer))
            gates[layer] = pack(gate0 + 1, counts[layer])
    except Exception as e:
        # A malformed job shouldn't take down /status or /cam_probe - fall back
        # to the head of each gate and let the totals still surface.
        print(f"[VOP SERVER] gate playhead resolve failed: {e}")
        for layer in ('pm', 'bp1', 'bp2'):
            gates[layer] = pack(1, counts[layer])

    return gates

# ---------------------------------------------------------
# DISPLAY RESOLUTION ACCESSOR
# ---------------------------------------------------------
# The engine detects the panel resolution at boot (via EDID through
# pygame.display.get_desktop_sizes()) and writes it to this file.
# We read once and cache - the value can't change at runtime since
# the panel is hot-plug-but-not-really on the Pi 4 HDMI port; you
# need a reboot to renegotiate anyway.
#
# Module-level cache rather than a class because vop.py is already
# heavily module-scoped (Flask routes, globals, etc.) and a single
# resolution doesn't justify a new abstraction.
DISPLAY_INFO_FILE = "/tmp/vop_display.json"
_display_size_cache = None

def get_display_size():
    """
    Returns (width, height) of the projection monitor. Reads the 
    engine's published JSON on first call, caches thereafter.
    
    Falls back to (1920, 1080) if the file is missing - happens 
    transiently during the brief window after vop.py boots but 
    before the engine has written its first display info. Any 
    affected request will get correct math on the next call once 
    the engine has come up.
    """
    global _display_size_cache
    if _display_size_cache is not None:
        return _display_size_cache
    try:
        with open(DISPLAY_INFO_FILE, 'r') as f:
            info = json.load(f)
            _display_size_cache = (int(info['width']), int(info['height']))
            return _display_size_cache
    except (OSError, ValueError, KeyError):
        # Don't cache the fallback - we want to retry on the next 
        # call in case the engine has just come up. The transient 
        # window is small but worth handling cleanly.
        return (1920, 1080)

def calculate_static_fit_scale(fov, ref_z, img_aspect, mode="fit",
                               screen_width=1920, screen_height=1080,
                               par_x=1.0, par_y=1.0):
    """
    Calculates the required scaling factor to size an image of arbitrary aspect
    ratio against the frustum bounds at a specific Z-depth.

    mode="fit"  - returns the smaller scale, fitting the entire image inside the
                  frustum (letterbox/pillarbox behavior, no cropping).
    mode="fill" - returns the larger scale, filling the frustum entirely with the
                  image (image overflow on the shorter axis is intentional).

    PAR awareness:
        vop_math.get_frustum_fit_matrix post-multiplies an anamorphic squeeze
        onto the projection matrix:
            sx_anam = min(1.0, 1.0/par)   # shrinks X when PAR > 1
            sy_anam = min(1.0, par)       # shrinks Y when PAR < 1
        That squeeze cuts the rendered quad's NDC footprint on whichever axis
        is squeezed. If we ignore it here, FIT/FILL FOV sizes the quad for
        the *unsqueezed* frustum and the renderer then trims it inwards,
        producing windowboxing on the squeezed axis.

        To compensate, we divide each axis's scale budget by its squeeze
        factor. The result: the geometry is intentionally OVER-sized in
        world space, but the squeeze brings it back so it lands exactly on
        the desired frustum edge in NDC. PAR=1:1 (sx_anam=sy_anam=1.0)
        collapses cleanly to the original behavior, so old jobs are
        unaffected.
    """
    # Prevent division by zero on the depth axis - a 0 ref_z would otherwise
    # nuke the frustum to a single point.
    z_dist = abs(float(ref_z))
    if z_dist == 0:
        z_dist = 0.1

    fov_rad = math.radians(float(fov))
    screen_aspect = screen_width / screen_height

    # Physical frustum bounds at ref_z. frustum_h is the FULL height of the
    # visible plane at that Z; frustum_w follows from the panel's aspect.
    frustum_h = 2.0 * z_dist * math.tan(fov_rad / 2.0)
    frustum_w = frustum_h * screen_aspect

    # Mirror the squeeze factors used by vop_math.get_frustum_fit_matrix.
    # Guard against zero/negative PAR inputs the same way the renderer does
    # so the two stay in lockstep regardless of malformed UI input.
    px = float(par_x) if float(par_x) > 0 else 1.0
    py = float(par_y) if float(par_y) > 0 else 1.0
    par = px / py
    sx_anam = min(1.0, 1.0 / par)   # <=1.0 always; ==1.0 when PAR<=1
    sy_anam = min(1.0, par)         # <=1.0 always; ==1.0 when PAR>=1

    # Dimensional scaling requirements, with the per-axis squeeze divided
    # OUT of the budget. The "/ sx_anam" looks like it's making the quad
    # bigger - and it is, in world space - but the squeeze in the projection
    # matrix shrinks the NDC footprint back down by the same factor, so the
    # quad lands exactly on the frustum edge the user expects.
    scale_for_width  = (frustum_w / (2.0 * img_aspect)) / sx_anam
    scale_for_height = (frustum_h / 2.0) / sy_anam

    # Pick min for fit (image inside frustum) or max for fill (frustum inside image)
    if mode == "fill":
        return max(scale_for_width, scale_for_height)
    return min(scale_for_width, scale_for_height)

def dispatch_engine(task, payload):
    """
    Writes the task command to the IPC JSON file.
    Emulates synchronous blocking for preview tasks to ensure frontend UI sync.
    """
    global engine_process
    print(f"\n[VOP SERVER] ACTION: {task.upper()}")

    # Guarantee background daemon is active before dispatching
    ensure_engine_running()

    # SINGLE-OWNER CAMERA GUARD (issue #198).
    # The Calibration framing feed holds the sensor via rpicam-vid. Every
    # engine task that touches the camera does so via rpicam-still, which
    # would fail with "device busy" if the feed were still up. Stopping it
    # here - the one path all tasks funnel through - guarantees the sensor
    # is free before the engine reaches for it. No-op (and cheap) if the
    # feed isn't running.
    camera_feed.stop_feed()

    payload['task'] = task
    payload['vop_version'] = VOP_VERSION 
    
    # Serialize UI state payload to disk for persistence
    with open(CURRENT_JOB_FILE, 'w') as f:
        json.dump(payload, f, indent=4)
        
    # Write the command payload to the IPC file. engine.py will intercept this file.
    with open(COMMAND_FILE, 'w') as f:
        json.dump(payload, f)

    # HTTP Blocking logic for specific synchronous tasks.
    # Forces the Flask thread to wait until engine.py processes and deletes COMMAND_FILE.
    # 
    # comp_preview is included here for the same reason cam_preview is:
    # the front end reloads probe_live.jpg right after the POST returns,
    # so we must not return until the engine has actually written the JPG.
    if task in ['preview', 'cam_preview', 'comp_preview']:
        timeout = 45.0
        start_t = time.time()
        while os.path.exists(COMMAND_FILE):
            # Terminate wait if the engine subprocess crashes
            if engine_process.poll() is not None:
                print("[VOP SERVER] Engine crashed during preview task.")
                break
            # Terminate wait on absolute timeout
            if (time.time() - start_t) > timeout:
                print(f"[VOP SERVER] Task {task_type} timed out.")
                break
            time.sleep(0.1)

# --- FLASK ROUTES ---

@app.route('/')
def index(): 
    # Serves the main SPA application
    return render_template('index.html')

@app.route('/status', methods=['GET'])
def status():
    """
    Aggregates system state, job configuration, and engine heartbeat data.
    Polled continuously by the web UI.
    """
    wp_dir = os.path.join(BASE_DIR, "WorkPrints")
    latest_wp = ""
    try:
        # Locate the most recently generated mp4 workprint
        wps = glob.glob(os.path.join(wp_dir, "*.mp4"))
        if wps: latest_wp = os.path.basename(max(wps, key=os.path.getctime))
    except: pass
    
    params = {}
    
    # State Hydration Layer 1: Default configuration
    default_job_file = os.path.join(BASE_DIR, "configs", "default_job.json")
    if os.path.exists(default_job_file):
        try:
            with open(default_job_file, 'r') as f: 
                params = json.load(f)
        except: pass

    # State Hydration Layer 2: Active session overrides
    if os.path.exists(CURRENT_JOB_FILE):
        try:
            with open(CURRENT_JOB_FILE, 'r') as f: 
                active_job = json.load(f)
                if active_job:
                    params.update(active_job)
        except: pass

    ensure_engine_running()

    # Determine executing status based on the presence of the IPC command file
    status_state = "idle"
    if os.path.exists(COMMAND_FILE):
        status_state = "rendering"
        try:
            # Read telemetry written by engine.py for UI progress bars
            with open("/tmp/vop_heartbeat", "r") as f:
                hb = json.load(f)
                return jsonify({
                    "status": "rendering", 
                    "heartbeat": hb, 
                    "params": params, 
                    "latest_wp": latest_wp,
                    # JK printer column visibility hints for the web UI
                    "pm_frames": count_source_frames(PROJ_MAG_DIR),
                    "bp1_frames": count_source_frames(PROJ_BIPACK1_DIR),
                    "bp2_frames": count_source_frames(PROJ_BIPACK2_DIR),
                    # Per-gate current/total frame readouts. Resolved against the
                    # frame the engine is exposing right now (hb["current"]).
                    "gates": resolve_gate_playheads(params, hb.get("current", 1)),
                })
        except:
            pass

    return jsonify({
        "status": status_state, 
        "params": params, 
        "latest_wp": latest_wp, 
        "workprint": f"/workprints/{latest_wp}" if latest_wp else None,
        # JK printer column visibility hints for the web UI
        "pm_frames": count_source_frames(PROJ_MAG_DIR),
        "bp1_frames": count_source_frames(PROJ_BIPACK1_DIR),
        "bp2_frames": count_source_frames(PROJ_BIPACK2_DIR),
        # Per-gate totals (always fresh) plus head-of-gate currents. At idle the
        # frontend takes only the totals from here and keeps the currents from
        # the last probe, so an idle poll never snaps a probed number back.
        "gates": resolve_gate_playheads(params, 1),
    })

@app.route('/render_prores', methods=['POST'])
def render_prores():
    """
    Kicks off a background ffmpeg ProRes 4444 render from the current CamMag TIFFs.
    Tagged as Linear/Rec.709 for direct Resolve/Fusion import without baked gamma.
    Returns immediately - poll /prores_status for completion.
    """
    global prores_process
    
    # Refuse if already running
    if prores_process and prores_process.poll() is None:
        return jsonify({"status": "already_running"}), 409
    
    tiffs = sorted(glob.glob(os.path.join(CAM_MAG_DIR, "*.tif")))
    if not tiffs:
        return jsonify({"error": "No frames found in CamMag"}), 404
    
    try:
        fps = request.json.get('fps', 24) if request.json else 24

        # ANAMORPHIC PAR METADATA
        # The captured TIFFs are squeezed. Tagging the ProRes stream's sample
        # aspect ratio as PAR_X:PAR_Y causes ffmpeg to write a 'pasp' atom into
        # the MOV container. Resolve/Premiere/FCP read this and unsqueeze the
        # picture on import without the editor having to remember to set PAR
        # manually. PAR 1:1 produces 1:1 metadata which is a no-op visually.
        par_x = float(request.json.get('par_x', 1.0) or 1.0) if request.json else 1.0
        par_y = float(request.json.get('par_y', 1.0) or 1.0) if request.json else 1.0
        # ffmpeg's setsar wants num/den - just pass the raw floats; ffmpeg parses
        # them. We use floats verbatim instead of trying to integerize because
        # arbitrary inputs like 1:1.24 don't reduce cleanly to small integers
        # and ffmpeg handles the decimal form fine.
        sar_filter = f"setsar={par_x}/{par_y}"

        ts = int(time.time())
        out_mov = os.path.join(PRORES_DIR, f"vop_prores_{ts}.mov")

        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-pattern_type", "glob",
            "-i", os.path.join(CAM_MAG_DIR, "*.tif"),
            "-c:v", "prores_ks",
            "-profile:v", "4444",
            "-pix_fmt", "yuv444p10le",
            # Bake PAR into the stream as the QuickTime 'pasp' atom so editors
            # auto-unsqueeze the footage on import.
            "-vf", sar_filter,
            # Tag as linear light, Rec.709 primaries - no gamma baked in.
            # Resolve/Fusion reads these flags and handles the transform in the projects
            # color management pipeline. Set Input Color Space to "Linear" in Resolve.
            "-color_trc", "linear",
            "-colorspace", "bt709",
            "-color_primaries", "bt709",
            out_mov
        ]

        print(f"[VOP SERVER] ACTION: RENDER PRORES -> {os.path.basename(out_mov)} | PAR={par_x}:{par_y}")
        prores_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr= subprocess.DEVNULL)

        return jsonify({"status": "started", "filename": os.path.basename(out_mov)})
    except Exception as e:
        print(f"[VOP SERVER] ProRes render error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/prores_status', methods=['GET'])
def prores_status():
    """ Polls the background ProRes ffmpeg process for completion. """
    global prores_process
    if prores_process is None:
        return jsonify({"status": "idle"})
    code = prores_process.poll()
    if code is None:
        return jsonify({"status": "rendering"})
    elif code == 0:
        # Find the most recently created.mov to return the filename
        movs = glob.glob(os.path.join(PRORES_DIR, "*.mov"))
        filename = os.path.basename(max(movs, key=os.path.getctime)) if movs else ""
        return jsonify({"status": "done", "filename":filename})
    else:
        return jsonify({"status": "error", "code": code})

@app.route('/check_validation_warning', methods=['GET'])
def check_validation_warning():
    """Returns any pending validation warning written by the engine, then deletes it."""
    warn_file = os.path.join(BASE_DIR, "static", "validation_warning.json")
    if not os.path.exists(warn_file):
        return jsonify({"warning": None})
    try:
        with open(warn_file) as f:
            data = json.load(f)
        os.remove(warn_file)  # Consume on read so it's only shown once
        return jsonify({"warning": data})
    except Exception as e:
        return jsonify({"warning": None, "error": str(e)})

@app.route('/prores/<filename>')
def serve_prores(filename):
    """ Serves the rendered ProRes file for browser download. """
    return send_from_directory(PRORES_DIR, filename, as_attachment=True)

@app.route('/upload_target', methods=['POST'])
def upload_target():
    # Handles file reception for the primary projection target
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    print(f"[VOP SERVER] ACTION: UPLOAD PROJ MAG -> {file.filename}")

    # Purge existing frames
    for f in os.listdir(PROJ_MAG_DIR):
        os.remove(os.path.join(PROJ_MAG_DIR, f))
    
    filepath = os.path.join(PROJ_MAG_DIR, file.filename)
    file.save(filepath)
    
    # Pass to the ingestion handler to process video files if necessary
    process_video_ingestion(filepath, PROJ_MAG_DIR)

    return jsonify({"status": "ok", "filename": file.filename})

@app.route('/upload_proj_bipack1', methods=['POST'])
def upload_proj_bipack1():
    # Handles file reception for BiPack layer 1 (the holdout-matte / first secondary mask)
    print("[VOP SERVER] UPLOADING: ProjBiPack1 Mask")
    file = request.files['file']
    for f in os.listdir(PROJ_BIPACK1_DIR): os.remove(os.path.join(PROJ_BIPACK1_DIR, f))
    filepath = os.path.join(PROJ_BIPACK1_DIR, file.filename)
    file.save(filepath)  
    process_video_ingestion(filepath, PROJ_BIPACK1_DIR)
    return jsonify({"status": "ok", "filename": file.filename})

@app.route('/upload_proj_bipack2', methods=['POST'])
def upload_proj_bipack2():
    # Handles file reception for BiPack layer 2 (the second optional mask reel)
    print("[VOP SERVER] UPLOADING: ProjBiPack2 Mask")
    file = request.files['file']
    for f in os.listdir(PROJ_BIPACK2_DIR): os.remove(os.path.join(PROJ_BIPACK2_DIR, f))
    filepath = os.path.join(PROJ_BIPACK2_DIR, file.filename)
    file.save(filepath)  
    process_video_ingestion(filepath, PROJ_BIPACK2_DIR)
    return jsonify({"status": "ok", "filename": file.filename})

# Maximum frame index that fits in the 4-digit %04d pattern used by
# the engine's playhead. Frame 9999 is the last valid one; frame
# 10000 would produce a 5-digit filename (latent_10000.tif) which
# breaks the engine's glob-based readers and the LAB/INVERT sorter.
# A future migration to %05d or a pure integer key could lift this -
# tracked separately. For now: enforce here so users get a clear
# error instead of a corrupted job.
CAM_MAG_FRAME_LIMIT = 9999

@app.route('/upload_cam_mag', methods=['POST'])
def upload_cam_mag():
    """
    Cam Mag video ingest. Unlike Proj Mag / BiPack uploads, this route
    only accepts video containers (no stills) - a single still loaded
    as a cam-mag has no meaningful frame correspondence with the timeline.
    
    Pre-flight: probe the video's frame count and reject if it exceeds
    the engine's 4-digit playhead range. Without this check, a 30-min
    reel would happily spend 10+ minutes filling the SSD with files
    that the engine then can't address. The 9999 limit corresponds to
    ~6.9 min @24fps; longer reels need to be split externally for now.
    
    On accept, the route nukes any existing cam-mag contents (matching
    the destructive semantics of the other UPLOAD buttons in this
    project), then runs ffmpeg with latent_NNNN.tif naming starting at
    frame 1. That naming is identical to what engine.py's execute path
    produces, so the LIME / Cam Probe / Comp View / ProRes render code
    all consume ingested reels with zero special-casing.
    
    Pix-fmt is rgb48le unconditionally: cam mag frames feed the LIME
    pipeline which is 16-bit throughout, so the mode-aware downgrade
    that protects Proj Mag textures doesn't apply here.
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    # Reject non-video uploads up front. The frontend's <input accept>
    # filters by extension but it's only an advisory hint in the
    # browser - we have to enforce server-side too.
    ext = os.path.splitext(file.filename)[1].lower()
    video_exts = ['.mp4', '.mov', '.avi', '.mkv', '.webm']
    if ext not in video_exts:
        return jsonify({
            "error": f"Cam Mag accepts video files only "
                     f"({', '.join(video_exts)}). Got: {ext or '(no extension)'}"
        }), 400
    
    print(f"[VOP SERVER] ACTION: UPLOAD CAM MAG -> {file.filename}")
    
    # Save to a temp path BEFORE the cam-mag is nuked. That way, if
    # the pre-flight check rejects the file, we haven't trashed the
    # user's existing reel for nothing. Temp lives in CamMag dir
    # itself so the rename-into-place after the check is atomic on
    # the same filesystem.
    tmp_path = os.path.join(CAM_MAG_DIR, f".incoming_{file.filename}")
    file.save(tmp_path)
    
    # Pre-flight: probe the frame count. If we can't determine it,
    # err on the side of letting the ingest proceed - the worst case
    # is wasted disk space, which the user can recover with NUKE.
    # If we DO get a count and it's over the limit, reject cleanly.
    frame_count = probe_video_frame_count(tmp_path)
    if frame_count is not None and frame_count > CAM_MAG_FRAME_LIMIT:
        os.remove(tmp_path)
        return jsonify({
            "error": f"Reel too long: {frame_count} frames exceeds the "
                     f"current {CAM_MAG_FRAME_LIMIT}-frame limit "
                     f"(~{CAM_MAG_FRAME_LIMIT // 24} sec @24fps). "
                     f"Split the reel externally and ingest a shorter "
                     f"segment, or trim it in your NLE first."
        }), 413  # 413 Payload Too Large is the closest HTTP semantic
    
    # Past the check - now we can safely wipe the existing cam-mag.
    # Same predicate as nuke_mag() (only .tif files) so we don't
    # accidentally delete our own .incoming_* tempfile mid-flight.
    for f in os.listdir(CAM_MAG_DIR):
        if f.endswith(".tif"):
            os.remove(os.path.join(CAM_MAG_DIR, f))
    
    # Move temp into place under its real name, then ingest. The
    # rename keeps the file off-limits to the .endswith('.tif')
    # sweeper during the brief window between nuke and ffmpeg start.
    filepath = os.path.join(CAM_MAG_DIR, file.filename)
    os.rename(tmp_path, filepath)
    
    # === Geometry inputs for the Cam Mag fit ====================
    # The ingested latent must match the camera frame's dimensions
    # so cv2.add can composite without array-shape errors, AND its
    # CONTENT must occupy a sub-rectangle of the monitor's aspect
    # so geometry survives the engine's panel-shaped render at
    # composite time. We need three resolutions:
    #
    #   1. Camera resolution - from current_job.json's cam_res.
    #      That defines the final latent dimensions.
    #   2. Monitor resolution - from EDID via get_display_size().
    #      That defines the content sub-rectangle's aspect.
    #   3. Input video resolution - from ffprobe on the upload.
    #      That's used purely to compute the recommended PAR for
    #      the UI - it does NOT affect the ingest itself, since
    #      the input gets stretched non-uniformly anyway.
    # ============================================================
    
    # 1. Camera resolution from job file. Same parse pattern as
    #    engine.py's cam_res handling (~lines 1623-1630).
    cam_res_str = '2028x1520'
    try:
        if os.path.exists(CURRENT_JOB_FILE):
            with open(CURRENT_JOB_FILE, 'r') as jf:
                cam_res_str = (json.load(jf) or {}).get('cam_res', '2028x1520')
    except (json.JSONDecodeError, OSError) as e:
        # Non-fatal - fall through to the hardcoded default.
        print(f"[VOP SERVER] WARN: Could not read cam_res for ingestion "
              f"({e}). Falling back to {cam_res_str}.")
    
    try:
        cw_str, ch_str = cam_res_str.lower().split('x')
        cam_w, cam_h = int(cw_str), int(ch_str)
    except (ValueError, AttributeError):
        print(f"[VOP SERVER] WARN: Malformed cam_res '{cam_res_str}'. "
              f"Falling back to (2028, 1520).")
        cam_w, cam_h = 2028, 1520
    
    # 2. Monitor resolution from EDID. get_display_size() handles
    #    its own fallback (1920x1080) if /tmp/vop_display.json
    #    isn't there yet, so we don't double-handle.
    mon_w, mon_h = get_display_size()
    
    # 3. Input video dimensions for the PAR recommendation. This
    #    can return None if the file is exotic - in that case we
    #    just skip the recommendation, the ingest still works fine.
    src_dims = probe_video_dimensions(filepath)
    
    # === Run the ingest =========================================
    process_video_ingestion(
        filepath, CAM_MAG_DIR,
        filename_prefix="latent_",
        start_number=1,
        pix_fmt_override="rgb48le",
        fit_to_monitor_in_camera={
            "cam_w": cam_w,
            "cam_h": cam_h,
            "monitor_w": mon_w,
            "monitor_h": mon_h,
        },
    )
    
    # === Compute recommended PAR for the response ===============
    # Goal: keep circles round end-to-end. The input video has its
    # own aspect (src_aspect); we just stretched it to fill the
    # monitor-aspect content rect (mon_aspect). To undo the
    # stretch at composite time, the engine's anamorphic squeeze
    # must apply a factor of src_aspect / mon_aspect on the X
    # axis (or its inverse on Y if < 1; the engine handles both
    # directions via min(1.0, 1.0/par) and min(1.0, par)).
    #
    # Convention: we surface par_x and par_y separately so the
    # display reads naturally - "1.185 : 1.000" for a 16:9 source
    # on a 3:2 monitor - even though it's mathematically just a
    # single ratio.
    recommended_par = None
    if src_dims is not None and mon_w > 0 and mon_h > 0:
        src_w, src_h = src_dims
        if src_w > 0 and src_h > 0:
            src_aspect = src_w / src_h
            mon_aspect = mon_w / mon_h
            ratio = src_aspect / mon_aspect
            
            # Surface a "natural" two-component reading. If the
            # ratio is >= 1 we put it in par_x (X squeeze); if
            # < 1 we put its inverse in par_y (Y squeeze) so
            # neither field ever goes below 1.0 in normal usage.
            # That matches how a cinematographer would think
            # about anamorphic squeezes.
            if ratio >= 1.0:
                recommended_par = {"par_x": round(ratio, 4), "par_y": 1.0}
            else:
                recommended_par = {"par_x": 1.0, "par_y": round(1.0 / ratio, 4)}
    
    # === Stash filename in current_job.json (unchanged) =========
    try:
        job = {}
        if os.path.exists(CURRENT_JOB_FILE):
            with open(CURRENT_JOB_FILE, 'r') as jf:
                job = json.load(jf) or {}
        job['cam_mag_filename'] = file.filename
        with open(CURRENT_JOB_FILE, 'w') as jf:
            json.dump(job, jf, indent=2)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[VOP SERVER] WARN: Could not record cam_mag_filename: {e}")
    
    # Stash the loaded reel's filename in current_job.json so a page
    # refresh can show the user what's currently in the cam mag. The
    # actual TIFF files on disk are anonymous (latent_0001.tif etc.),
    # so without this we'd lose the human-readable source name.
    try:
        job = {}
        if os.path.exists(CURRENT_JOB_FILE):
            with open(CURRENT_JOB_FILE, 'r') as jf:
                job = json.load(jf) or {}
        job['cam_mag_filename'] = file.filename
        with open(CURRENT_JOB_FILE, 'w') as jf:
            json.dump(job, jf, indent=2)
    except (json.JSONDecodeError, OSError) as e:
        # Non-fatal: the upload succeeded, just the label won't
        # survive a page refresh. Log and continue.
        print(f"[VOP SERVER] WARN: Could not record cam_mag_filename: {e}")
    
    # Response surfaces the PAR recommendation alongside the
    # filename. Frontend renders this as a clickable readout that
    # copies into the par_x / par_y fields when tapped. Same
    # pattern as the Noise Crusher's measured-value link.
    return jsonify({
        "status": "ok",
        "filename": file.filename,
        "recommended_par": recommended_par,  # may be None - frontend handles
    })

@app.route('/nuke_proj_mag', methods=['POST'])
def nuke_proj_mag():
    # Deletes all primary projection assets
    print("[VOP SERVER] ACTION: NUKE PROJ MAG")
    for f in os.listdir(PROJ_MAG_DIR): os.remove(os.path.join(PROJ_MAG_DIR, f))
    return jsonify({"status": "ok"})

@app.route('/nuke_proj_bipack1', methods=['POST'])
def nuke_proj_bipack1():
    # Deletes all BiPack layer 1 assets
    print("[VOP SERVER] ACTION: NUKE PROJ BIPACK1")
    for f in os.listdir(PROJ_BIPACK1_DIR): os.remove(os.path.join(PROJ_BIPACK1_DIR, f))
    return jsonify({"status": "ok"})

@app.route('/nuke_proj_bipack2', methods=['POST'])
def nuke_proj_bipack2():
    # Deletes all BiPack layer 2 assets
    print("[VOP SERVER] ACTION: NUKE PROJ BIPACK2")
    for f in os.listdir(PROJ_BIPACK2_DIR): os.remove(os.path.join(PROJ_BIPACK2_DIR, f))
    return jsonify({"status": "ok"})
    
@app.route('/get_img_aspect', methods=['GET'])
def get_img_aspect():
    # Analyzes the first valid image frame in the target directory to return the aspect ratio
    # mag query: 'proj' (default) | 'bipack1' | 'bipack2'
    target = request.args.get('mag', 'proj')
    if target == 'bipack1':
        check_dir = PROJ_BIPACK1_DIR
    elif target == 'bipack2':
        check_dir = PROJ_BIPACK2_DIR
    else:
        check_dir = PROJ_MAG_DIR
    try:
        valid_exts = ('.png', '.jpg', '.jpeg', '.tif', '.tiff')
        files = sorted([f for f in os.listdir(check_dir) if f.lower().endswith(valid_exts)])
        
        if files:
            img = cv2.imread(os.path.join(check_dir, files[0]))
            if img is not None: 
                h, w = img.shape[:2]
                aspect = w / h
                print(f"[VOP SERVER] {target.upper()} Aspect Assessed: {w}x{h} ({aspect:.4f})")
                return jsonify({"aspect": aspect})
    except Exception as e: 
        print(f"[VOP SERVER] Aspect Calc Error: {e}")
        
    return jsonify({"aspect": 1.777})

@app.route('/calculate_fit', methods=['POST'])
def calculate_fit():
    # Route for the UI Fit FOV / Fill FOV buttons. The 'mode' field on the 
    # request body decides which behavior the math uses; defaults to fit for 
    # backward compatibility with any old clients.
    print("[VOP SERVER] ACTION: CALCULATE FIT FOV")
    data = request.json
    try:
        fov     = float(data.get('fov', 45.0))
        ref_z   = float(data.get('ref_z', 1.0))
        aspect  = float(data.get('aspect_ratio', 1.777))
        mode    = data.get('mode', 'fit')      # 'fit' or 'fill'
        # New: anamorphic PAR values forwarded from the GUI's PAR inputs.
        # Defaults to 1:1 so any old/stripped client (or a manual curl
        # request that pre-dates this field) still gets the original
        # unsqueezed behavior - no silent surprises on legacy callers.
        par_x   = float(data.get('par_x', 1.0))
        par_y   = float(data.get('par_y', 1.0))

        # Pull the live panel dimensions so frustum-bounds math matches
        # what the engine is actually rendering into. Without this, Fit/Fill
        # FOV would compute against a fictional 1920x1080 frustum and the
        # button would set the user a few degrees off on a 3:2 or UHD panel.
        screen_w, screen_h = get_display_size()
        req_scale = calculate_static_fit_scale(fov, ref_z, aspect, mode=mode,
                                               screen_width=screen_w,
                                               screen_height=screen_h,
                                               par_x=par_x, par_y=par_y)
        return jsonify({"status": "ok", "scale": req_scale})
    except Exception as e:
        print(f"[VOP SERVER] Fit Calc Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400
        
@app.route('/preview', methods=['POST'])
def preview():
    # Dispatches the internal renderer preview
    dispatch_engine('preview', request.json)
    return jsonify({"status": "started"})

@app.route('/cam_preview', methods=['POST'])
def cam_preview():
    # Dispatches the hardware camera preview
    dispatch_engine('cam_preview', request.json)
    return jsonify({"status": "started"})

@app.route('/comp_preview', methods=['POST'])
def comp_preview():
    # Dispatches a Comp Preview: same as cam_preview (smear render +
    # camera capture + JPG to probe_live.jpg) but in color_utils we
    # additively composite the new exposure on top of any existing
    # CamMag latent TIFF for this frame BEFORE writing the JPG.
    # The existing TIFF on disk is NEVER modified - this is purely a
    # viewfinder for lining up multi-pass exposures.
    dispatch_engine('comp_preview', request.json)
    return jsonify({"status": "started"})

@app.route('/calibration_feed')
def calibration_feed():
    # The live MJPEG stream itself. The browser consumes this directly via
    # <img src="/calibration_feed">; each part is a full JPEG frame. We do
    # NOT auto-start here - the frontend calls /calibration_feed/start
    # first - so that a stray <img> can't grab the camera unexpectedly.
    return Response(
        camera_feed.frames(),
        mimetype='multipart/x-mixed-replace; boundary=vopframe'
    )

@app.route('/calibration_feed/start', methods=['POST'])
def calibration_feed_start():
    # Refuse to start while the engine is mid-task: COMMAND_FILE existing
    # means a capture/render is in flight and owns (or is about to own)
    # the sensor. Starting rpicam-vid then would collide.
    if os.path.exists(COMMAND_FILE):
        return jsonify({"status": "busy"}), 409
    camera_feed.start_feed()
    return jsonify({"status": "started"})

@app.route('/calibration_feed/stop', methods=['POST'])
def calibration_feed_stop():
    # Explicit stop from the frontend (Stop button, or navigating away
    # from the Calibration page). Releases the camera immediately.
    camera_feed.stop_feed()
    return jsonify({"status": "stopped"})

@app.route('/calibration_targets/on', methods=['POST'])
def calibration_targets_on():
    # Drop the sentinel the engine's idle loop polls. While it exists the
    # projection monitor shows the framing/focus targets instead of the
    # idle logo. Deliberately NOT routed through dispatch_engine: that stops
    # the camera, but targets are display-only and must run alongside the
    # live feed. open()/close() just touches the file into existence.
    open(CAL_TARGETS_FILE, 'w').close()
    return jsonify({"status": "on"})

@app.route('/calibration_targets/off', methods=['POST'])
def calibration_targets_off():
    # Remove the sentinel; the idle loop falls back to the bouncing logo on
    # its next frame. FileNotFoundError is fine - "off" is the goal state,
    # so a double-off (or off before any on) is a harmless no-op.
    try:
        os.remove(CAL_TARGETS_FILE)
    except FileNotFoundError:
        pass
    return jsonify({"status": "off"})

@app.route('/display_info', methods=['GET'])
def display_info():
    # Panel + sensor dimensions for the framing overlay (issue #198, Slice 3).
    # The frontend uses the PANEL aspect to place the corner target boxes
    # where the on-screen crosshairs land in the sensor frame, and the SENSOR
    # dims to size the SVG viewBox 1:1 with the feed. get_display_size() reads
    # the engine's EDID-published resolution (cached after first call); cam_w/
    # cam_h come from the feed module so the viewBox always tracks the actual
    # stream resolution even if we retune it later.
    w, h = get_display_size()
    return jsonify({
        "monitor_w": w,
        "monitor_h": h,
        "cam_w": camera_feed.FEED_WIDTH,
        "cam_h": camera_feed.FEED_HEIGHT,
    })

@app.route('/cam_probe', methods=['POST'])
def cam_probe():
    """
    CAM PROBE
    Reads the existing latent TIFF for the current probe frame from CamMag,
    converts it to an 8-bit JPG, and writes it to static/probe_live.jpg so
    the GUI's preview window can show it.

    This is a pure file-read/convert operation - no smear render, no camera
    capture, no engine dispatch. It runs in the Flask request thread, which
    means it's also safe to call while a long Execute job is in flight; we
    just read whatever the latent currently looks like.

    The bit-depth reduction matches the other preview paths (img / 256.0)
    so Cam Probe and Cam Preview produce visually comparable JPGs - both
    are 8-bit linear-light samples of the same 16-bit linear data.
    """
    print("[VOP SERVER] ACTION: CAM PROBE")

   # Pull the probe frame number from the posted body, same shape the other
    # preview routes receive. Default to 1 if missing/garbled.
    #
    # Also pull PAR (par_x, par_y) and the preview_unsqueeze toggle so Cam
    # Probe can mirror the anamorphic-aware behavior of Cam View / Comp View.
    # Without these, toggling between the preview buttons would cause the
    # preview window to alternate between unsqueezed (looks right) and
    # squeezed (looks ovally), which defeats the whole point of having a
    # PAR system in the first place.
    try:
        data = request.json or {}
        # The collectParams() shipping side may send numbers as strings -
        # int(float(...)) coerces both numeric and string inputs cleanly.
        frame_num = int(float(data.get('probe_frame', 1)))
    except (TypeError, ValueError):
        frame_num = 1

    # PAR + unsqueeze - parsed defensively. If anything is malformed we
    # silently fall back to 1.0 / False, which is identical to non-anamorphic
    # behavior. We never want a malformed PAR field to blow up Cam Probe.
    try:
        par_x = float(data.get('par_x', 1.0) or 1.0)
        par_y = float(data.get('par_y', 1.0) or 1.0)
    except (TypeError, ValueError):
        par_x, par_y = 1.0, 1.0
    preview_unsqueeze = bool(data.get('preview_unsqueeze', False))

    # Resolve the per-gate readouts for the frame being probed. The posted body
    # is the live job (collectParams), so Timeline sees the current exposure
    # sheet. Returned on the OK paths below; the frontend uses it to update the
    # Cam Mag / Projection Mag / BiPack readouts to match what's in each gate
    # at this probed frame.
    gate_data = resolve_gate_playheads(data, frame_num)

    # ANAMORPHIC PREVIEW UNSQUEEZE - inline helper.
    # Mirrors the unsqueeze logic in color_utils.generate_sensor_preview and
    # generate_comp_preview verbatim, so Cam Probe produces the same JPG
    # dimensions those functions would for the same PAR settings. The visual
    # consistency between the four preview buttons depends on this matching.
    #
    # NOTE: this is duplicated from color_utils. A future cleanup could
    # extract a single helper (perhaps color_utils.unsqueeze_preview_jpg)
    # and have all three callers use it. Not doing it now to keep the
    # blast radius of this Cam Probe fix small and avoid touching the two
    # working preview functions on the brink of a release.
    def _maybe_unsqueeze(img):
        if not preview_unsqueeze:
            return img
        try:
            px = par_x if par_x > 0 else 1.0
            py = par_y if par_y > 0 else 1.0
            par = px / py
            if abs(par - 1.0) <= 1e-6:
                return img  # square pixels - nothing to do
            h, w = img.shape[:2]
            if par > 1.0:
                # Wide-pixel case: stretch X horizontally.
                new_w = int(round(w * par))
                return cv2.resize(img, (new_w, h), interpolation=cv2.INTER_CUBIC)
            else:
                # Tall-pixel case: stretch Y vertically.
                new_h = int(round(h / par))
                return cv2.resize(img, (w, new_h), interpolation=cv2.INTER_CUBIC)
        except Exception as e:
            # Fall back to the squeezed image rather than failing the
            # whole probe - matches the same defensive behavior in
            # color_utils.generate_sensor_preview.
            print(f"[VOP SERVER] Cam Probe unsqueeze failed (falling back to squeezed): {e}")
            return img

    # Build the path using the SAME filename format execute_exposure writes
    # ("latent_NNNN.tif" with 4-digit zero-padding). If we drift from that
    # format here, Cam Probe will silently read the wrong frame or nothing.
    latent_file = os.path.join(CAM_MAG_DIR, f"latent_{str(frame_num).zfill(4)}.tif")
    static_dir = os.path.join(BASE_DIR, "static")
    out_jpg = os.path.join(static_dir, "probe_live.jpg")

    # No latent for this frame - write a placeholder JPG so the user gets
    # an unambiguous visual answer rather than a stale preview from a
    # previous click.
    #
    # Why we write a JPG here instead of returning 404 and letting the
    # frontend handle it: keeping ALL preview state in probe_live.jpg
    # means the frontend pipeline is uniform (post -> reload JPG) for
    # every preview button. The user also gets the frame number baked
    # into the placeholder so there's zero ambiguity about which frame
    # they're being told is empty.
    #
    # Generated on the fly rather than served as a static asset because
    # we want the frame number IN the image. A pre-rendered "NO LATENT"
    # PNG couldn't communicate that.
    if not os.path.exists(latent_file):
        print(f"[VOP SERVER] CAM PROBE: no latent at frame {frame_num} - writing placeholder")
        try:
            # Match Proj Probe's actual dimensions so the placeholder 
            # scales identically in the preview panel. The probe_img CSS 
            # uses object-fit:contain so source dimensions don't really 
            # affect display size, but matching keeps things tidy and 
            # makes the placeholder layout look right at any panel size.
            ph_w, ph_h = get_display_size()

            # Background: very dark gray (BGR), close to --bg-panel from
            # style.css. Pure black would be visually indistinguishable
            # from a real latent that's mostly underexposed; the slight
            # gray makes "this is a system message, not your data" read.
            placeholder = np.full((ph_h, ph_w, 3), 26, dtype=np.uint8)  # 26,26,26 BGR

            # Headline: "NO LATENT" in a muted red/orange. We use the
            # cv2 built-in Hershey font so we don't need to introduce a
            # PIL/Pillow dependency just for this placeholder.
            headline = "NO LATENT"
            sub = f"Frame {frame_num}"
            font = cv2.FONT_HERSHEY_SIMPLEX

            # Sizing chosen so both lines read clearly when the 1920x1080
            # placeholder is scaled down to fit the preview panel. Tuned
            # by eye - bump these if the panel is small on your display.
            head_scale, head_thick = 5.0, 12
            sub_scale,  sub_thick  = 3.0, 6

            # Measure text so we can center it horizontally. cv2.getTextSize
            # returns ((width, height), baseline).
            (hw, hh), _ = cv2.getTextSize(headline, font, head_scale, head_thick)
            (sw, sh), _ = cv2.getTextSize(sub,      font, sub_scale,  sub_thick)

            # Vertical layout: stack the two lines around the vertical
            # center with a comfortable gap. cv2.putText anchors text by
            # its baseline (bottom-left), which is why the y values look
            # like they're below center - they account for text height.
            gap = 80
            total_h = hh + gap + sh
            head_y = (ph_h - total_h) // 2 + hh
            sub_y  = head_y + gap + sh

            head_x = (ph_w - hw) // 2
            sub_x  = (ph_w - sw) // 2

            # Headline color: muted red/orange (BGR). Picks up the same
            # warning-feel as --color-warning in style.css without being
            # alarming-emergency-red. The color also can't naturally
            # appear in a latent (which would be tinted by CG gel from
            # the user's job, not a system-chosen accent).
            cv2.putText(placeholder, headline, (head_x, head_y),
                        font, head_scale, (60, 110, 230), head_thick, cv2.LINE_AA)

            # Sub-line: lighter gray, informational. Carries the frame
            # number so the user knows exactly which frame is empty -
            # critical when probe_frame may have changed since last click.
            cv2.putText(placeholder, sub, (sub_x, sub_y),
                        font, sub_scale, (170, 170, 170), sub_thick, cv2.LINE_AA)

            # Unsqueeze the placeholder too, so the preview panel
            # dimensions stay stable as the user cycles between frames
            # with and without latents. Without this, landing on a
            # no-latent frame would visually "jump" the panel back to
            # the squeezed aspect ratio - the exact unsteady cue the
            # Preview Unsqueeze toggle is supposed to eliminate.
            placeholder = _maybe_unsqueeze(placeholder)
            cv2.imwrite(out_jpg, placeholder)

            # Return 200 + a placeholder marker. The marker isn't used
            # by the current frontend (it just reloads the JPG either
            # way) but is here as a hook for future features.
            return jsonify({"status": "ok", "frame": frame_num, "placeholder": True, "gates": gate_data})

        except Exception as e:
            print(f"[VOP SERVER] CAM PROBE placeholder error: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    try:
        # Read the 16-bit linear BGR latent off disk untouched.
        # IMREAD_UNCHANGED preserves bit depth and channel count.
        img = cv2.imread(latent_file, cv2.IMREAD_UNCHANGED)
        if img is None:
            return jsonify({"status": "read_failed", "frame": frame_num}), 500

        # Downscale 16-bit -> 8-bit using the same /256.0 reduction as the
        # sibling preview functions in color_utils.py. This intentionally
        # leaves the data in linear light so the visual character matches
        # the other preview JPGs (they'll all look uniformly "dark on a
        # sRGB monitor" - that's expected and consistent across previews).
        if img.dtype == np.uint16:
            img8 = (img / 256.0).astype(np.uint8)
        else:
            # Defensive branch: if for some reason the file isn't uint16
            # (legacy job, hand-edited TIFF, etc), just pass it through.
            img8 = img

        # Apply preview unsqueeze BEFORE writing the JPG, so the final
        # file on disk is what the user sees. This matches the order of
        # operations in color_utils.generate_sensor_preview.
        img8 = _maybe_unsqueeze(img8)
        cv2.imwrite(out_jpg, img8)

        return jsonify({"status": "ok", "frame": frame_num, "gates": gate_data})

    except Exception as e:
        print(f"[VOP SERVER] CAM PROBE error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/gate_readout', methods=['POST'])
def gate_readout():
    """
    GATE READOUT - pure gate-frame resolver, no rendering.

    Exists so the async preview actions (Proj Probe, Cam View, Comp View) can
    update the per-mag "####/####" readouts. Those three dispatch the engine
    and return immediately ({"status":"started"}); their image lands later via
    probe_live.jpg and the heartbeat, so unlike Cam Probe they have no synchronous
    response to hang gate data on. Rather than thread gate data through the engine's
    async preview path (large blast radius for a readout), the frontend calls this
    tiny synchronous route alongside the preview dispatch and applies the result.

    Mirrors the gate-resolution half of /cam_probe exactly: same body shape
    (collectParams()), same probe_frame default, same resolve_gate_playheads
    helper - so Proj Probe / Cam View / Comp View land on identical numbers to
    Cam Probe for the same frame. No camera, no disk writes, no engine dispatch.
    """
    data = request.json or {}
    try:
        frame_num = int(float(data.get('probe_frame', 1)))
    except (TypeError, ValueError):
        frame_num = 1
    return jsonify({"status": "ok", "frame": frame_num,
                    "gates": resolve_gate_playheads(data, frame_num)})

@app.route('/execute', methods=['POST'])
def execute_seq():
    # Dispatches the full frame sequence exposure task
    dispatch_engine('execute', request.json)
    return jsonify({"status": "started"})

@app.route('/measure_white_balance', methods=['POST'])
def measure_white_balance():
    # Calibration page: "Auto White Balance".
    #
    # Fire-and-forget, exactly like ACB. The engine runs the full
    # exposure-search -> WB loop -> confirm sequence in one task
    # (unlike ACB+black which split because they're independently
    # useful; WB search/solve/confirm is one logical operation).
    # Frontend sees /status go "rendering" then "idle", then GETs
    # /calibration_state to read the derived gains.
    dispatch_engine('measure_white_balance', request.json)
    return jsonify({"status": "started"})

@app.route('/measure_noise', methods=['POST'])
def measure_noise():
    # Dispatches the dark frame noise floor measurement
    dispatch_engine('measure_noise', request.json)
    return jsonify({"status": "started"})

@app.route('/map_hot_pixels', methods=['POST'])
def map_hot_pixels():
    # Dispatches the hot pixel mapping calibration routine
    dispatch_engine('map_hot_pixels', request.json)
    return jsonify({"status": "started"})

@app.route('/nuke_hot_pixels', methods=['POST'])
def nuke_hot_pixels():
    # Deletes the hot pixel map JSON
    hp_file = os.path.join(BASE_DIR, "static", "hot_pixels.json")
    if os.path.exists(hp_file):
        os.remove(hp_file)
    return jsonify({"status": "clear"})

@app.route('/lab_invert', methods=['POST'])
def lab_invert():
    # Dispatches the mathematical 16-bit negative inversion process
    dispatch_engine('lab_invert', request.json)
    return jsonify({"status": "started"})

@app.route('/single_peak_measurement', methods=['POST'])
def single_peak_measurement():
    # Calibration page: "Single Measurement" button.
    #
    # Dispatches a single capture at the supplied exposure time,
    # measuring centre-patch brightness against a synthetic white
    # patch. Result lands in calibration.json under the
    # last_single_measurement key.
    #
    # Fire-and-forget. Frontend polls /status to detect completion
    # and then GETs /calibration_state to read the new measurement.
    # See the IPC-busy-state convention notes in
    # modules/calibration_store.py for how the polling works.
    dispatch_engine('single_peak_measurement', request.json)
    return jsonify({"status": "started"})


@app.route('/measure_peak_white', methods=['POST'])
def measure_peak_white():
    # Calibration page: "ACB" (Auto Calibrate for Brackets) button.
    #
    # Runs the bisection-with-doubling-bootstrap search for T_peak -
    # the exposure time at which the projection monitor's synthetic
    # white lands at the user-defined target brightness range. On
    # convergence, persists t_peak (and metadata) to calibration.json.
    #
    # This task is potentially long-running (up to max_iterations
    # camera captures, each taking 4-5 seconds including libcamera
    # overhead). Fire-and-forget like the other measurement routes;
    # the frontend will see /status flip to "rendering" for the
    # duration and back to "idle" on completion.
    dispatch_engine('measure_peak_white', request.json)
    return jsonify({"status": "started"})


@app.route('/measure_peak_black', methods=['POST'])
def measure_peak_black():
    # Calibration page: "Include black level measurement" checkbox
    # companion to ACB.
    #
    # Single capture at the supplied exposure time (intended to be
    # the just-measured T_peak) with the projection monitor showing
    # synthetic black. Persists black_floor_at_t_peak to
    # calibration.json.
    #
    # The frontend sequencer is responsible for calling this AFTER
    # /measure_peak_white completes, with the exposure_s parameter
    # set to whatever t_peak the ACB run produced. We don't chain
    # them automatically server-side because the user might want
    # to run them independently (e.g. re-measuring black floor
    # without re-running ACB, to check sensor drift between job
    # runs).
    dispatch_engine('measure_peak_black', request.json)
    return jsonify({"status": "started"})


@app.route('/calibration_state', methods=['GET'])
def calibration_state():
    # Returns the current contents of calibration.json as a normalised
    # JSON dict. Frontend uses this to populate the Calibration page's
    # readouts after each measurement task completes.
    #
    # Wrapping this in a route (rather than serving calibration.json
    # as a static file) gives us a stable contract: always a dict,
    # never a 404 on missing-file. The static_dir global is the
    # same path the engine writes to via cstore.save() - so what's
    # written by the engine is exactly what we read here.
    static_dir = os.path.join(BASE_DIR, "static")
    return jsonify(cstore.load(static_dir))

@app.route('/panic', methods=['POST'])
def panic():
    # Emergency halt execution route
    print("[VOP SERVER] ACTION: PANIC STOP")
    global engine_process

    # Bruteforce termination of the engine subprocess to force DRM lock release
    if engine_process and engine_process.poll() is None:
        engine_process.terminate()
        try:
            engine_process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            engine_process.kill()
            
    # Force kill any hung libcamera instances
    subprocess.run(["pkill", "-9", "rpicam-still"])
    
    # Immediately reboot the persistent daemon to resume idle screen
    ensure_engine_running()
    
    return jsonify({"status": "panic_executed"})

@app.route('/nuke_mag', methods=['POST'])
def nuke_mag():
    # Deletes all captured latent TIFFs. Now also clears the recorded
    # cam_mag_filename, since the reel that label refers to no longer
    # exists on disk - leaving the label stale would mislead the UI
    # into showing a phantom reel name.
    print("[VOP SERVER] ACTION: NUKE CAM MAG")
    for f in os.listdir(CAM_MAG_DIR):
        if f.endswith(".tif"): os.remove(os.path.join(CAM_MAG_DIR, f))
    
    # Best-effort clear of the filename label. Same fail-soft pattern
    # as upload_cam_mag - if the job file is unreadable we log and
    # move on rather than reporting a 500 for a cosmetic concern.
    try:
        if os.path.exists(CURRENT_JOB_FILE):
            with open(CURRENT_JOB_FILE, 'r') as jf:
                job = json.load(jf) or {}
            if 'cam_mag_filename' in job:
                job.pop('cam_mag_filename', None)
                with open(CURRENT_JOB_FILE, 'w') as jf:
                    json.dump(job, jf, indent=2)
    except (json.JSONDecodeError, OSError) as e:
        print(f"[VOP SERVER] WARN: Could not clear cam_mag_filename: {e}")
    
    return jsonify({"status": "mag_cleared"})

def write_branding_preview():
    """
    Render the branding logo centered on a black background and write it to
    static/probe_live.jpg, replacing whatever preview was last shown.

    This is the "standby" preview - used when there is nothing meaningful to
    show, e.g. right after Nuke Job, where the previous job's preview would
    otherwise linger and falsely imply state that no longer exists.

    The output is an ordinary preview JPG, so the next Proj Probe / Cam View /
    Cam Probe just overwrites it like any other preview - no special-casing
    needed anywhere else in the pipeline.

    branding.png is a 512x512 square today, but a user may swap in a logo of
    any aspect ratio. We scale-to-fit (contain) while preserving aspect, then
    center it and let the black canvas pad the rest - so any AR lands cleanly
    with black bars rather than being distorted.
    """
    # Match the projection monitor resolution so the standby card has the same
    # dimensions as a real preview. probe_img uses object-fit:contain so exact
    # size isn't critical, but matching avoids the panel visibly resizing when
    # switching between this and a live probe.
    disp_w, disp_h = get_display_size()
    out_jpg = os.path.join(BASE_DIR, "static", "probe_live.jpg")

    # Pure-black canvas (BGR, cv2's channel order). Shape is (H, W, 3). This is
    # the "blank black background" the logo sits on.
    canvas = np.zeros((disp_h, disp_w, 3), dtype=np.uint8)

    logo_path = os.path.join(BASE_DIR, "graphics", "branding.png")

    # Fraction of each axis the logo may occupy. The logo is fit INSIDE this
    # centered box, so 0.6 leaves a comfortable black margin all around instead
    # of the logo touching the edges. Tune to taste (1.0 = edge-to-edge on the
    # limiting axis).
    LOGO_FILL = 0.6

    try:
        # IMREAD_COLOR forces a 3-channel BGR image (and drops any alpha), so
        # the paste below always matches the canvas channel count even if a
        # user supplies an RGBA PNG.
        logo = cv2.imread(logo_path, cv2.IMREAD_COLOR)
        if logo is None:
            raise FileNotFoundError(logo_path)

        logo_h, logo_w = logo.shape[:2]

        # Centered target box the logo must fit within.
        box_w = disp_w * LOGO_FILL
        box_h = disp_h * LOGO_FILL

        # "Contain" scale: the SMALLER ratio, so the whole logo fits inside the
        # box on both axes with its aspect ratio preserved.
        scale = min(box_w / logo_w, box_h / logo_h)
        new_w = max(1, int(round(logo_w * scale)))
        new_h = max(1, int(round(logo_h * scale)))

        # Pick interpolation by direction: INTER_AREA is best when shrinking,
        # INTER_CUBIC when enlarging (a small logo on a big monitor upscales).
        interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_CUBIC
        resized = cv2.resize(logo, (new_w, new_h), interpolation=interp)

        # Integer top-left offset so the logo sits dead-center and the black
        # canvas pads the remainder symmetrically.
        x0 = (disp_w - new_w) // 2
        y0 = (disp_h - new_h) // 2

        # Paste by overwriting the pixel block - the logo is opaque BGR on a
        # black background, so no alpha blending is required.
        canvas[y0:y0 + new_h, x0:x0 + new_w] = resized

    except Exception as e:
        # Missing/unreadable logo: fall back to a plain black standby card.
        # Still better than a stale preview, and never blocks the nuke.
        print(f"[VOP SERVER] Branding preview: logo unavailable, writing black ({e})")

    # cv2.imwrite expects BGR, which is exactly what we built.
    cv2.imwrite(out_jpg, canvas)

@app.route('/nuke_job', methods=['POST'])
def nuke_job():
    # Deletes the active session configuration file
    print("[VOP SERVER] ACTION: NUKE CURRENT JOB")
    if os.path.exists(CURRENT_JOB_FILE):
        os.remove(CURRENT_JOB_FILE)
    # Replace the lingering preview with the branding standby card. Without
    # this, the previous job's last preview stays up after the reload and
    # falsely implies there's still something to preview. Written here during
    # the POST so the frontend's post-reload first-load fetch of
    # probe_live.jpg (already cache-busted) picks it up.
    write_branding_preview()
    return jsonify({"status": "job_nuked"})

@app.route('/workprints/<filename>')
def serve_workprint(filename):
    # Returns the compiled h.264 mp4 file
    return send_from_directory(os.path.join(BASE_DIR, "WorkPrints"), filename)

def get_ip():
    # Utility function to determine the local routing IP address.
    # Uses a dummy UDP connection to 8.8.8.8 to force the OS to resolve the local interface IP.
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


@app.route('/export_job', methods=['GET'])
def export_job():
    # Sends the current session JSON file to the client for download
    print("[VOP SERVER] ACTION: EXPORT CURRENT JOB")
    if os.path.exists(CURRENT_JOB_FILE):
        return send_file(CURRENT_JOB_FILE, as_attachment=True)
    return jsonify({"error": "No active job found to export"}), 404

@app.route('/import_job', methods=['POST'])
def import_job():
    # Receives a JSON configuration file and overwrites the active session
    print("[VOP SERVER] ACTION: IMPORT JOB")
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    try:
        job_data = json.load(file)
        file_version = job_data.get('vop_version', 'legacy/unknown')
        warning = None
        # Provide feedback if the imported file structure might be incompatible
        if file_version != VOP_VERSION:
            warning = f"System is v{VOP_VERSION}, but the file is v{file_version}."
        
        with open(CURRENT_JOB_FILE, 'w') as f:
            json.dump(job_data, f, indent=4)
        with open(CURRENT_JOB_FILE, 'w') as f:
            json.dump(job_data, f, indent=4)
        
        return jsonify({"status": "ok", "warning": warning})

    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON format."}), 400
    except Exception as e:
        print(f"[VOP SERVER] Import Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/save_job', methods=['POST'])
def save_job():
    # Silently serializes UI changes to disk without dispatching a command to the engine
    payload = request.json
    payload['vop_version'] = VOP_VERSION
    
    with open(CURRENT_JOB_FILE, 'w') as f:
        json.dump(payload, f, indent=4)
        
    return jsonify({"status": "ok"})
        
if __name__ == '__main__':
    port = 5000
    ip_addr = get_ip()

    # Publish the WebGUI address for the engine's idle screen.
    # engine.py runs as a separate process (it holds the KMSDRM lock)
    # so it cannot call get_ip() directly. We drop the IP+port to a
    # small JSON file - the same on-disk-IPC pattern the engine uses
    # to publish display info back to us (see /tmp/vop_display.json).
    # The engine reads this when rendering the idle screen so the user
    # can see where to point their browser. Non-fatal if it fails:
    # the engine falls back to a placeholder string.
    try:
        with open("/tmp/vop_ip.json", 'w') as f:
            json.dump({'ip': ip_addr, 'port': port}, f)
    except OSError as e:
        print(f"[VOP SERVER] Could not publish IP info: {e}")

    print("\n" + "="*50)
    print(f" VOP Server is online.")
    print(f" Status: Waiting for jobs")
    print(f" WebGUI: http://{ip_addr}:{port}")
    print("="*50 + "\n" )

    # Boot the persistent engine daemon before opening the web socket
    ensure_engine_running()

    app.run(host='0.0.0.0', port=port, debug=False)