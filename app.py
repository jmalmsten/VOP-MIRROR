"""
VOP Module:     app.py
Version:        v0.1.4
Description:    Flask Web Server and UI Router.
                Handles incoming requests, state sync, and subprocess isolation.
                Includes Workprint serving and OpenCV aspect ratio calculation.
"""
import os
import json
import subprocess
import time
import logging
import cv2
import glob
from flask import Flask, jsonify, request, render_template, send_from_directory

# --- TERMINAL CLEANUP ---
# Flask uses the 'werkzeug' logger to print every GET/POST request.
# Setting this to ERROR suppresses the constant 200 OK heartbeat spam.
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)

# Absolute paths based on the location of this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ_MAG_DIR = os.path.join(BASE_DIR, "ProjMag")
CAM_MAG_DIR = os.path.join(BASE_DIR, "CamMag")
CURRENT_JOB_FILE = os.path.join(BASE_DIR, "current_job.json")
DEFAULT_JOB_FILE = os.path.join(BASE_DIR, "default_job.json")

# Ensure required directories exist on boot
os.makedirs(PROJ_MAG_DIR, exist_ok=True)
os.makedirs(CAM_MAG_DIR, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "WorkPrints"), exist_ok=True)

# Global reference to the engine subprocess so we can monitor or kill it
engine_process = None

def load_job_state():
    """
    State Loader with Fallback Logic.
    Attempts to load the user's active session ('current_job.json').
    If the file is missing or corrupted, it falls back to the safe defaults ('default_job.json').
    """
    if os.path.exists(CURRENT_JOB_FILE):
        try:
            with open(CURRENT_JOB_FILE, "r") as f: 
                return json.load(f)
        except json.JSONDecodeError:
            pass # File was corrupted or empty, proceed to fallback
            
    if os.path.exists(DEFAULT_JOB_FILE):
        try:
            with open(DEFAULT_JOB_FILE, "r") as f: 
                return json.load(f)
        except json.JSONDecodeError:
            pass

    return {}

@app.route('/', methods=['GET'])
def index():
    """Serves the main HTML user interface."""
    return render_template('index.html')

@app.route('/status', methods=['GET'])
def get_status():
    """
    The Silent Heartbeat. Polled every second by main.js. 
    Provides the current UI parameter state, engine progress data, and latest workprint.
    """
    global engine_process
    params = load_job_state()
    
    # Calculate available disk space on the root partition.
    try:
        statvfs = os.statvfs('/')
        disk_free = (statvfs.f_frsize * statvfs.f_bavail) / (1024**3)
        disk_str = f"FREE: {disk_free:.1f}GB"
    except:
        disk_str = "DISK UNKNOWN"

    status = "idle"
    msg = "VOP Engine Ready"
    
    # Check if the execution engine is actively running
    if engine_process is not None:
        if engine_process.poll() is None:
            status = "running"
            msg = "Engine Executing..."
        else:
            status = "idle"
            msg = "Execution Complete."
            engine_process = None

    # Retrieve progress from the heartbeat file written by the engine.
    current_frame = 0
    if os.path.exists("/tmp/vop_heartbeat"):
        try:
            with open("/tmp/vop_heartbeat", "r") as f:
                current_frame = int(f.read().strip())
        except:
            pass

    # NEW: Find the most recent workprint in the WorkPrints directory
    latest_wp = None
    wp_list = glob.glob(os.path.join(BASE_DIR, "WorkPrints", "*.mp4"))
    if wp_list:
        # Get the file with the newest creation/modification time
        latest_wp = os.path.basename(max(wp_list, key=os.path.getctime))

    return jsonify({
        "status": status, "msg": msg, "current": current_frame, 
        "total": 0, "eta": 0, "disk": disk_str, "params": params,
        "latest_wp": latest_wp # Pass the filename to the UI
    })

@app.route('/get_img_aspect', methods=['GET'])
def get_img_aspect():
    """
    Reads the physical pixel dimensions of the current image using OpenCV
    so the UI can mathematically calculate a zero-crop frustum fit.
    """
    job = load_job_state()
    img_name = job.get('image', '')
    if not img_name:
        return jsonify({'aspect': 1.0})
        
    img_path = os.path.join(PROJ_MAG_DIR, img_name)
    aspect = 1.0
    if os.path.exists(img_path):
        try:
            img = cv2.imread(img_path)
            if img is not None:
                h, w = img.shape[:2]
                aspect = w / h
        except Exception as e:
            print(f"[ERROR] Could not calculate aspect ratio: {e}")
            
    return jsonify({'aspect': aspect})

@app.route('/sync_state', methods=['POST'])
def sync_state():
    """
    Receives state updates pushed by the UI and writes them to the current job file.
    """
    new_state = request.json
    with open(CURRENT_JOB_FILE, "w") as f:
        json.dump(new_state, f, indent=4)
    return jsonify({"status": "ok", "new_sync": new_state.get('last_sync', 0)})

@app.route('/preview', methods=['POST'])
def preview():
    """
    Triggers a single-frame operation ('Proj Probe' or 'Cam View').
    Dispatched as a blocking subprocess so the UI waits for it to finish.
    """
    data = request.json
    req_type = data.get('type', 'unknown')
    target_frame = data.get('probe_frame', 1)
    
    if req_type == 'cam_preview':
        print(f"\n[UI ACTION] Button Pressed: CAM VIEW (Frame: {target_frame})")
    else:
        print(f"\n[UI ACTION] Button Pressed: PROJ PROBE (Frame: {target_frame})")
        
    job_file = "/tmp/vop_job.json"
    with open(job_file, "w") as f:
        json.dump(data, f)
        
    subprocess.run(["python3", os.path.join(BASE_DIR, "engine.py"), "--job", job_file])
    return jsonify({"status": "ok"})

@app.route('/execute_sequence', methods=['POST'])
def execute_sequence():
    """
    Triggers a full timeline sequence render.
    Dispatched as a non-blocking background process.
    """
    global engine_process
    data = request.json
    print("\n[UI ACTION] Button Pressed: SEQUENCE RENDER")
    
    if engine_process is not None and engine_process.poll() is None:
         print("[ERROR] Attempted to start sequence, but engine is already running.")
         return jsonify({"status": "error", "msg": "Engine is already running."}), 400

    job_file = "/tmp/vop_job.json"
    with open(job_file, "w") as f:
        json.dump(data, f)
        
    engine_process = subprocess.Popen(["python3", os.path.join(BASE_DIR, "engine.py"), "--job", job_file])
    return jsonify({"status": "started"})

@app.route('/upload_target', methods=['POST'])
def upload_target():
    """
    Receives image files from the browser and saves them to the ProjMag.
    """
    print("\n[UI ACTION] Uploading new file to ProjMag...")
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    for f in os.listdir(PROJ_MAG_DIR):
        os.remove(os.path.join(PROJ_MAG_DIR, f))
        
    filename = file.filename
    file.save(os.path.join(PROJ_MAG_DIR, filename))
    print(f"[UI ACTION] Upload complete: {filename}")
    return jsonify({"status": "ok", "filename": filename})

@app.route('/panic', methods=['POST'])
def panic():
    """
    Emergency stop. Kills the Python engine process and any hanging camera hardware processes.
    """
    print("\n[UI ACTION] Button Pressed: PANIC STOP!")
    global engine_process
    if engine_process is not None:
        engine_process.kill()
        engine_process = None
    subprocess.run(["pkill", "-9", "rpicam-still"])
    return jsonify({"status": "panic_executed"})

@app.route('/nuke_mag', methods=['POST'])
def nuke_mag():
    """
    Wipes all accumulated TIFF exposures from the CamMag directory.
    """
    print("\n[UI ACTION] Button Pressed: NUKE MAG (Clearing TIFFs)")
    for f in os.listdir(CAM_MAG_DIR):
        if f.endswith(".tif"):
            os.remove(os.path.join(CAM_MAG_DIR, f))
    return jsonify({"status": "mag_cleared"})

# NEW: Route to allow the browser to download/play the mp4 workprints
@app.route('/workprints/<filename>')
def serve_workprint(filename):
    return send_from_directory(os.path.join(BASE_DIR, "WorkPrints"), filename)

if __name__ == '__main__':
    print("=========================================")
    print(" VOP Server is online.")
    print(" Heartbeat logging is silenced.")
    print(" UI available at: http://<PI_IP>:5000")
    print("=========================================")
    app.run(host='0.0.0.0', port=5000)