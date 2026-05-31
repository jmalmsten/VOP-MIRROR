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
from flask import Flask, jsonify, request, render_template, send_from_directory, send_file

# Append the modules directory to the system path for local imports
sys.path.append(os.path.join(os.path.dirname(__file__), "modules"))

# Calibration store for reading the persisted hardware-calibration
# values. Used by the /calibration_state GET route to expose the
# current state to the frontend.
import calibration_store as cstore

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

def process_video_ingestion(filepath, target_dir, filename_prefix="", start_number=0, pix_fmt_override=None):
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
    cmd = [
        "ffmpeg", "-y", "-i", filepath,
        "-pix_fmt", pix_fmt,
        "-start_number", str(start_number),
        output_pattern
    ]

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

def dispatch_engine(task_type, payload):
    """
    Writes the task command to the IPC JSON file.
    Emulates synchronous blocking for preview tasks to ensure frontend UI sync.
    """
    global engine_process
    print(f"\n[VOP SERVER] ACTION: {task_type.upper()}")

    # Guarantee background daemon is active before dispatching
    ensure_engine_running()

    payload['type'] = task_type
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
    if task_type in ['preview', 'cam_preview', 'comp_preview']:
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
            return jsonify({"status": "ok", "frame": frame_num, "placeholder": True})

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

        return jsonify({"status": "ok", "frame": frame_num})

    except Exception as e:
        print(f"[VOP SERVER] CAM PROBE error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

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
    # Deletes all captured latent TIFFs
    print("[VOP SERVER] ACTION: NUKE CAM MAG")
    for f in os.listdir(CAM_MAG_DIR):
        if f.endswith(".tif"): os.remove(os.path.join(CAM_MAG_DIR, f))
    return jsonify({"status": "mag_cleared"})

@app.route('/nuke_job', methods=['POST'])
def nuke_job():
    # Deletes the active session configuration file
    print("[VOP SERVER] ACTION: NUKE CURRENT JOB")
    if os.path.exists(CURRENT_JOB_FILE):
        os.remove(CURRENT_JOB_FILE)
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

    print("\n" + "="*50)
    print(f" VOP Server is online.")
    print(f" Status: Waiting for jobs")
    print(f" WebGUI: http://{ip_addr}:{port}")
    print("="*50 + "\n" )

    # Boot the persistent engine daemon before opening the web socket
    ensure_engine_running()

    app.run(host='0.0.0.0', port=port, debug=False)