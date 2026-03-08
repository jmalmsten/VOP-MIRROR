"""
VOP Module:     vop.py
Version:        v0.2.7
Description:    Main Entry Point. Flask Web Server.
                Synchronized heartbeat payload keys for frontend UI parsing.
"""
import os
import sys
import json
import subprocess
import logging
import cv2
import glob

sys.path.append(os.path.join(os.path.dirname(__file__), "modules"))
from flask import Flask, jsonify, request, render_template, send_from_directory

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ_MAG_DIR = os.path.join(BASE_DIR, "ProjMag")
CAM_MAG_DIR = os.path.join(BASE_DIR, "CamMag")
CURRENT_JOB_FILE = os.path.join(BASE_DIR, "current_job.json")

os.makedirs(PROJ_MAG_DIR, exist_ok=True)
os.makedirs(CAM_MAG_DIR, exist_ok=True)
os.makedirs(os.path.join(BASE_DIR, "WorkPrints"), exist_ok=True)

engine_process = None

def dispatch_engine(task_type, payload):
    global engine_process
    print(f"\n[UI ACTION] Executing Task: {task_type.upper()}")
    
    payload['type'] = task_type
    
    with open(CURRENT_JOB_FILE, 'w') as f:
        json.dump(payload, f, indent=4)
        
    if engine_process is not None and engine_process.poll() is None:
        engine_process.kill()
        
    engine_script = os.path.join(BASE_DIR, "modules", "engine.py")
    engine_process = subprocess.Popen([sys.executable, engine_script, "--job", CURRENT_JOB_FILE])
    
    if task_type in ['preview', 'cam_preview']:
        engine_process.wait()

@app.route('/')
def index(): return render_template('index.html')

@app.route('/status', methods=['GET'])
def status():
    global engine_process
    
    wp_dir = os.path.join(BASE_DIR, "WorkPrints")
    latest_wp = ""
    try:
        wps = glob.glob(os.path.join(wp_dir, "*.mp4"))
        if wps: latest_wp = os.path.basename(max(wps, key=os.path.getctime))
    except: pass

    if engine_process is not None:
        if engine_process.poll() is None:
            try:
                with open("/tmp/vop_heartbeat", "r") as f:
                    hb = json.load(f)
                    return jsonify({
                        "status": "running", 
                        "current": hb.get("current", 0), 
                        "total": hb.get("total", 1), 
                        "eta": hb.get("eta", 0), 
                        "disk": f"{hb.get('est_mb', 0)} MB", 
                        "msg": hb.get("msg", "RENDERING"),
                        "latest_wp": latest_wp
                    })
            except:
                return jsonify({
                    "status": "running", 
                    "current": 0, "total": 1, "eta": 0, "disk": "0 MB", 
                    "msg": "STARTING...", 
                    "latest_wp": latest_wp
                })
        else:
            engine_process = None
            return jsonify({"status": "idle", "latest_wp": latest_wp})
    return jsonify({"status": "idle", "latest_wp": latest_wp})

@app.route('/get_img_aspect', methods=['GET'])
def get_img_aspect():
    try:
        files = [f for f in os.listdir(PROJ_MAG_DIR) if os.path.isfile(os.path.join(PROJ_MAG_DIR, f))]
        if files:
            img = cv2.imread(os.path.join(PROJ_MAG_DIR, files[0]))
            if img is not None: return jsonify({"aspect": img.shape[1] / img.shape[0]})
    except: pass
    return jsonify({"aspect": 1.777})

@app.route('/preview', methods=['POST'])
def preview():
    dispatch_engine('preview', request.json)
    return jsonify({"status": "started", "task": "preview"})

@app.route('/cam_preview', methods=['POST'])
def cam_preview():
    dispatch_engine('cam_preview', request.json)
    return jsonify({"status": "started", "task": "cam_preview"})

@app.route('/execute', methods=['POST'])
def execute_seq():
    dispatch_engine('execute', request.json)
    return jsonify({"status": "started", "task": "execute"})

@app.route('/trigger_task', methods=['POST'])
def trigger_legacy():
    payload = request.json
    dispatch_engine(payload.get('type', 'preview'), payload)
    return jsonify({"status": "started"})

@app.route('/upload_target', methods=['POST'])
def upload_target():
    print("\n[UI ACTION] Uploading new file to ProjMag...")
    if 'file' not in request.files: return jsonify({"error": "No file"}), 400
    file = request.files['file']
    for f in os.listdir(PROJ_MAG_DIR): os.remove(os.path.join(PROJ_MAG_DIR, f))
    file.save(os.path.join(PROJ_MAG_DIR, file.filename))
    print(f"[UI ACTION] Upload complete: {file.filename}")
    return jsonify({"status": "ok", "filename": file.filename})

@app.route('/panic', methods=['POST'])
def panic():
    print("\n[UI ACTION] Button Pressed: PANIC STOP!")
    global engine_process
    if engine_process is not None:
        engine_process.kill()
        engine_process = None
    subprocess.run(["pkill", "-9", "rpicam-still"])
    return jsonify({"status": "panic_executed"})

@app.route('/nuke_mag', methods=['POST'])
def nuke_mag():
    print("\n[UI ACTION] Button Pressed: NUKE MAG")
    for f in os.listdir(CAM_MAG_DIR):
        if f.endswith(".tif"): os.remove(os.path.join(CAM_MAG_DIR, f))
    return jsonify({"status": "mag_cleared"})

@app.route('/workprints/<filename>')
def serve_workprint(filename):
    return send_from_directory(os.path.join(BASE_DIR, "WorkPrints"), filename)

if __name__ == '__main__':
    print("=========================================")
    print(" VOP Server (v0.2.7) is online.")
    print("=========================================")
    app.run(host='0.0.0.0', port=5000, debug=False)