"""
VOP Module:     app.py
Version:        v0.1.0
Description:    Flask Web Server and UI Router.
                Handles incoming requests from the browser, reads/writes JSON job states,
                and dispatches execution commands to the engine via subprocess isolation.
"""
import os
import json
import subprocess
import time
from flask import Flask, jsonify, request, render_template

app = Flask(__name__)

# Absolute paths based on the location of this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ_MAG_DIR = os.path.join(BASE_DIR, "ProjMag")
CAM_MAG_DIR = os.path.join(BASE_DIR, "CamMag")
CURRENT_JOB_FILE = os.path.join(BASE_DIR, "current_job.json")
DEFAULT_JOB_FILE = os.path.join(BASE_DIR, "default_job.json")

# Ensure required directories exist
os.makedirs(PROJ_MAG_DIR, exist_ok=True)
os.makedirs(CAM_MAG_DIR, exist_ok=True)

# Global reference to the engine subprocess
engine_process = None

def load_job_state():
    """
    State Loader with Fallback Logic.
    Attempts to load the user's active session ('current_job.json').
    If the file is missing or corrupted, it falls back to the safe defaults ('default_job.json').
    """
    # Attempt to load the active session first
    if os.path.exists(CURRENT_JOB_FILE):
        try:
            with open(CURRENT_JOB_FILE, "r") as f: 
                return json.load(f)
        except json.JSONDecodeError:
            pass # File was corrupted or empty, proceed to fallback
            
    # Fallback to the default job template
    if os.path.exists(DEFAULT_JOB_FILE):
        try:
            with open(DEFAULT_JOB_FILE, "r") as f: 
                return json.load(f)
        except json.JSONDecodeError:
            pass

    # Ultimate fallback if everything is missing
    return {}

@app.route('/', methods=['GET'])
def index():
    """Serves the main HTML user interface."""
    return render_template('index.html')

@app.route('/status', methods=['GET'])
def get_status():
    """
    Polled every second by main.js. 
    Provides the current UI parameter state and engine progress data.
    """
    global engine_process
    
    # Always read the latest parameters from disk to support multi-device syncing.
    params = load_job_state()
    
    # Calculate available disk space on the root partition.
    try:
        statvfs = os.statvfs('/')
        disk_free = (statvfs.f_frsize * statvfs.f_bavail) / (1024**3)
        disk_str = f"FREE: {disk_free:.1f}GB"
    except:
        disk_str = "DISK UNKNOWN"

    # Determine if the engine subprocess is currently running.
    status = "idle"
    msg = "VOP Engine Ready"
    
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

    return jsonify({
        "status": status, 
        "msg": msg, 
        "current": current_frame, 
        "total": 0, # Total frames would be calculated dynamically in a full implementation
        "eta": 0,
        "disk": disk_str,
        "params": params
    })

@app.route('/sync_state', methods=['POST'])
def sync_state():
    """
    Receives state updates pushed by the UI and writes them to the current job file.
    """
    new_state = request.json
    
    # Write directly to the active session file.
    with open(CURRENT_JOB_FILE, "w") as f:
        json.dump(new_state, f, indent=4)
        
    # Echo back the timestamp to confirm the write was successful.
    return jsonify({"status": "ok", "new_sync": new_state.get('last_sync', 0)})

@app.route('/preview', methods=['POST'])
def preview():
    """
    Triggers a single-frame operation. 
    This handles both 'Proj Probe' (synthetic render) and 'Cam View' (physical hardware capture).
    """
    data = request.json
    
    # Write the job parameters to a temporary file for the engine to consume.
    job_file = "/tmp/vop_job.json"
    with open(job_file, "w") as f:
        json.dump(data, f)
        
    # Dispatch the engine script as a blocking subprocess. 
    # Because it is a preview, we wait for it to finish so the UI knows exactly when the image is ready.
    subprocess.run(["python3", os.path.join(BASE_DIR, "engine.py"), "--job", job_file])
    return jsonify({"status": "ok"})

@app.route('/execute_sequence', methods=['POST'])
def execute_sequence():
    """
    Triggers a full timeline sequence render.
    """
    global engine_process
    data = request.json
    
    # Prevent starting a new job if the engine is already running.
    if engine_process is not None and engine_process.poll() is None:
         return jsonify({"status": "error", "msg": "Engine is already running."}), 400

    job_file = "/tmp/vop_job.json"
    with open(job_file, "w") as f:
        json.dump(data, f)
        
    # Dispatch the engine script as a non-blocking background process.
    engine_process = subprocess.Popen(["python3", os.path.join(BASE_DIR, "engine.py"), "--job", job_file])
    return jsonify({"status": "started"})

@app.route('/upload_target', methods=['POST'])
def upload_target():
    """
    Receives image files from the browser and saves them to the ProjMag.
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
        
    # Clear out old files from the magazine to prevent clutter.
    for f in os.listdir(PROJ_MAG_DIR):
        os.remove(os.path.join(PROJ_MAG_DIR, f))
        
    # Save the new file.
    filename = file.filename
    file.save(os.path.join(PROJ_MAG_DIR, filename))
    
    return jsonify({"status": "ok", "filename": filename})

@app.route('/panic', methods=['POST'])
def panic():
    """
    Emergency stop. Kills the Python engine process and any hanging camera processes.
    """
    global engine_process
    if engine_process is not None:
        engine_process.kill()
        engine_process = None
        
    # Force kill any rogue rpicam-still processes at the system level.
    subprocess.run(["pkill", "-9", "rpicam-still"])
    return jsonify({"status": "panic_executed"})

@app.route('/nuke_mag', methods=['POST'])
def nuke_mag():
    """
    Wipes all accumulated TIFF exposures from the CamMag directory.
    """
    for f in os.listdir(CAM_MAG_DIR):
        if f.endswith(".tif"):
            os.remove(os.path.join(CAM_MAG_DIR, f))
    return jsonify({"status": "mag_cleared"})

if __name__ == '__main__':
    # Binds the Flask server to all interfaces (0.0.0.0) on port 5000, 
    # allowing access from the laptop, phone, or any other device on the local network.
    app.run(host='0.0.0.0', port=5000)