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
from flask import Flask, jsonify, request, render_template, send_from_directory, send_file

# Append the modules directory to the system path for local imports
sys.path.append(os.path.join(os.path.dirname(__file__), "modules"))

# Suppress default Flask HTTP request logging to keep the terminal output clean for audit logs
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
app = Flask(__name__)

# Absolute path resolutions for standard system directories
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ_MAG_DIR = os.path.join(BASE_DIR, "ProjMag")
PROJ_BIPACK_DIR = os.path.join(BASE_DIR, "ProjBiPack")
CAM_MAG_DIR = os.path.join(BASE_DIR, "CamMag")
CURRENT_JOB_FILE = os.path.join(BASE_DIR, "current_job.json")

# Inter-Process Communication (IPC) file for the persistent engine daemon
# The Flask server writes JSON payloads here; engine.py polls this file to execute commands
COMMAND_FILE = "/tmp/vop_cmd.json" 

VOP_VERSION ="0.6.5"

# Initialize required directory structure on boot if missing
PRORES_DIR = os.path.join(BASE_DIR, "ProRes")
for d in [PROJ_MAG_DIR, PROJ_BIPACK_DIR, CAM_MAG_DIR, os.path.join(BASE_DIR, "WorkPrints"), PRORES_DIR]:
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

def process_video_ingestion(filepath, target_dir):
    """
    Checks if an uploaded file is a video container.
    If so, extracts all frames to zero-padded TIFFs matching the engine's
    playhead expectations (0000.tif, 0001.tif) and deletes the original video.
    
    Extra thought. If future me needs, that could maybe be increased to 5 digits.
    that would increase the incoming video's max length from 6 min 56 sec 16 frames to 
    69 min 26 sec 16 frames (if my math is correct). But let's keep it at 4 digits for 
    a max length "reel" of just under 7 minutes. It seems oddly realistic to real life systems
    """
    ext = os.path.splitext(filepath)[1].lower()
    video_exts = ['.mp4', '.mov', '.avi', '.mkv', '.webm']

    if ext in video_exts:
        print(f"[VOP SERVER] Video detected! Extracting {filepath} to TIFF sequence...")

        output_pattern = os.path.join(target_dir, "%04d.tif")

        # ffmpeg flags: -y (overwrite), -i (input), -start_number 0 (force index 0)
        cmd = [
            "ffmpeg", "-y", "-i", filepath,
            "-start_number", "0",
            output_pattern
        ]

        try:
            # Execute ffmpeg blocking call. Redirect stdout/stderr to DEVNULL to prevent terminal spam
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[VOP SERVER] Frame extraction complete.")
            os.remove(filepath) # Delete the source video to conserve storage
        
        except subprocess.CalledProcessError as e:
            print(f"[VOP SERVER] CRITICAL: FFMPEG ingestion failed: {e}")

def count_source_frames(directory):
    """
    Counts image frames in a media directory (PROJ_MAG_DIR or PROJ_BIPACK_DIR).

    Used by /status to tell the web UI whether a layer holds a still image
    (1 frame or a video sequence (>1 frame)). The UI uses this to show or hide
    the JK Optical Printer (GATE/CAM/STP) inputs in the exposure sheets,
    since those columns are only meaningful when there's a sequence to traverse.
    """
    if not os.path.exists(directory):
        return 0
    valid_exts = ('.png', '.jpg', '.jpeg', '.tif', '.tiff')
    return len([f for f in os.listdir(directory) if f.lower().endswith(valid_exts)])


def calculate_static_fit_scale(fov, ref_z, img_aspect, screen_width=1920, screen_height=1080):
    """
    Calculates the required scaling factor to fit an image of arbitrary aspect ratio
    within the frustum bounds at a specific Z-depth.
    """
    # Prevent division by zero
    z_dist = abs(float(ref_z))
    if z_dist == 0: z_dist = 0.1 
        
    fov_rad = math.radians(float(fov))
    screen_aspect = screen_width / screen_height
    
    # Calculate physical frustum bounds
    frustum_h = 2.0 * z_dist * math.tan(fov_rad / 2.0)
    frustum_w = frustum_h * screen_aspect
    
    # Calculate dimensional scaling requirements
    scale_for_width = frustum_w / (2.0 * img_aspect)
    scale_for_height = frustum_h / 2.0
    
    # Return the minimum constraint to ensure the image fits entirely (letterbox/pillarbox behavior)
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
    if task_type in ['preview', 'cam_preview']:
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
                    "bp_frames": count_source_frames(PROJ_BIPACK_DIR),
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
        "bp_frames": count_source_frames(PROJ_BIPACK_DIR),
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
            # Tag as linear light, Rec.709 primaries - no gamma baked in.
            # Resolve/Fusion reads these flags and handles the transform in the projects
            # color management pipeline. Set Input Color Space to "Linear" in Resolve.
            "-color_trc", "linear",
            "-colorspace", "bt709",
            "-color_primaries", "bt709",
            out_mov
        ]

        print(f"[VOP SERVER] ACTION: RENDER PRORES -> {os.path.basename(out_mov)}")
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

@app.route('/upload_proj_bipack', methods=['POST'])
def upload_proj_bipack():
    # Handles file reception for the secondary mask/bipack layer
    print("[VOP SERVER] UPLOADING: ProjBiPack Mask")
    file = request.files['file']
    for f in os.listdir(PROJ_BIPACK_DIR): os.remove(os.path.join(PROJ_BIPACK_DIR, f))
    filepath = os.path.join(PROJ_BIPACK_DIR, file.filename)
    file.save(filepath)  
    process_video_ingestion(filepath, PROJ_BIPACK_DIR)
    return jsonify({"status": "ok", "filename": file.filename})

@app.route('/nuke_proj_mag', methods=['POST'])
def nuke_proj_mag():
    # Deletes all primary projection assets
    print("[VOP SERVER] ACTION: NUKE PROJ MAG")
    for f in os.listdir(PROJ_MAG_DIR): os.remove(os.path.join(PROJ_MAG_DIR, f))
    return jsonify({"status": "ok"})

@app.route('/nuke_proj_bipack', methods=['POST'])
def nuke_proj_bipack():
    # Deletes all secondary bipack assets
    print("[VOP SERVER] ACTION: NUKE PROJ BIPACK")
    for f in os.listdir(PROJ_BIPACK_DIR): os.remove(os.path.join(PROJ_BIPACK_DIR, f))
    return jsonify({"status": "ok"})

@app.route('/get_img_aspect', methods=['GET'])
def get_img_aspect():
    # Analyzes the first valid image frame in the target directory to return the aspect ratio
    target = request.args.get('mag', 'proj')
    check_dir = PROJ_BIPACK_DIR if target == 'bipack' else PROJ_MAG_DIR
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
    # Route for the UI 'Fit Image' button logic
    print("[VOP SERVER] ACTION: CALCULATE FIT FOV")
    data = request.json
    try:
        fov = float(data.get('fov', 45.0))
        ref_z = float(data.get('ref_z', 1.0))
        aspect = float(data.get('aspect_ratio', 1.777))
        
        req_scale = calculate_static_fit_scale(fov, ref_z, aspect)
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

@app.route('/execute', methods=['POST'])
def execute_seq():
    # Dispatches the full frame sequence exposure task
    dispatch_engine('execute', request.json)
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