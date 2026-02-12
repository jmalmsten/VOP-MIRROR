"""
VOP Module:     app.py
Version:        v0.9.9
Description:    Phase V Orchestrator. Fixes Panic/Workprint bug.
"""
import subprocess, os, json, time, glob, shutil, threading, logging
from flask import Flask, render_template, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename

app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.addFilter(lambda r: "/status" not in r.getMessage())

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.join(BASE_DIR, "engine.py")
CURRENT_FILE = os.path.join(BASE_DIR, "current_job.json")
CAM_MAG_DIR = os.path.join(BASE_DIR, "CamMag")
PROJ_MAG_DIR = os.path.join(BASE_DIR, "ProjMag")
WORKPRINT_DIR = os.path.join(BASE_DIR, "WorkPrints")
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

progress_state = {"current": 0, "total": 0, "msg": "Idle", "status": "idle", "eta": 0, "disk": "0 GB", "latest_wp": ""}

def init_state():
    for d in [CAM_MAG_DIR, PROJ_MAG_DIR, WORKPRINT_DIR]: os.makedirs(d, exist_ok=True)
    if not os.path.exists(CURRENT_FILE):
        with open(CURRENT_FILE, 'w') as f: json.dump({"v": "0.9.9", "last_sync": 0}, f)

init_state()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def run_job_thread(data):
    global progress_state
    
    frames = []
    for k, v in data.items():
        if k.startswith('f') and k[1:].isdigit() and str(v).strip():
            try: frames.append(int(v))
            except: pass
    
    if not frames:
        print("CRITICAL: No valid frames found.")
        return

    f_start, f_end = min(frames), max(frames)
    total = (f_end - f_start) + 1
    
    progress_state.update({"current": 0, "total": total, "status": "running", "msg": "Exposing..."})
    
    if os.path.exists("/tmp/vop_heartbeat"): os.remove("/tmp/vop_heartbeat")
    
    with open("/tmp/vop_job.json", 'w') as f: json.dump(data, f)
    proc = subprocess.Popen(["python3", ENGINE_PATH, "--job", "/tmp/vop_job.json"])
    start_time = time.time()
    
    processed = 0
    while proc.poll() is None:
        if os.path.exists("/tmp/vop_heartbeat"):
            processed += 1
            os.remove("/tmp/vop_heartbeat")
            progress_state["current"] = processed
            if processed > 0:
                avg = (time.time() - start_time) / processed
                progress_state["eta"] = int(avg * (total - processed))
        time.sleep(0.5)

    # --- PANIC FIX ---
    # Only generate workprint if process exited cleanly (0)
    if proc.returncode == 0:
        if len(glob.glob(os.path.join(CAM_MAG_DIR, "*.tif"))) > 0:
            progress_state["msg"] = "Workprinting..."
            wp_name = f"vop_wp_{time.strftime('%H%M%S')}.mp4"
            subprocess.run(["ffmpeg", "-y", "-framerate", str(data.get('fps', 24)), "-pattern_type", "glob", "-i", os.path.join(CAM_MAG_DIR, "*.tif"),
                            "-vf", "scale=2048:1536,format=yuv420p", "-c:v", "libx264", "-crf", "23", os.path.join(WORKPRINT_DIR, wp_name)])
            progress_state["latest_wp"] = wp_name
            progress_state.update({"status": "idle", "msg": "COMPLETE", "current": total, "eta": 0})
    else:
        # If killed or crashed
        progress_state.update({"status": "idle", "msg": "ABORTED", "current": 0, "eta": 0})

@app.route('/upload_target', methods=['POST'])
def upload_target():
    if 'file' not in request.files: return jsonify({"status": "NO FILE"}), 400
    file = request.files['file']
    if file.filename == '': return jsonify({"status": "NO NAME"}), 400
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(os.path.join(PROJ_MAG_DIR, filename))
        return jsonify({"status": "SUCCESS", "filename": filename})
    return jsonify({"status": "BAD TYPE"}), 400

@app.route('/status')
def get_status():
    free_gb = shutil.disk_usage(BASE_DIR).free / (1024.0**3)
    progress_state["disk"] = f"{free_gb:.1f} GB"
    with open(CURRENT_FILE, 'r') as f: params = json.load(f)
    return jsonify({**progress_state, "params": params})

@app.route('/preview', methods=['POST'])
def preview():
    if progress_state["status"] == "running": return jsonify({"status": "BUSY"}), 423
    data = request.json
    with open(CURRENT_FILE, 'w') as f: json.dump(data, f, indent=4)
    with open("/tmp/vop_job.json", 'w') as f: json.dump(data, f)
    subprocess.run(["python3", ENGINE_PATH, "--job", "/tmp/vop_job.json"])
    return jsonify({"status": "SUCCESS"})

@app.route('/sync_state', methods=['POST'])
def sync_state():
    data = request.json
    with open(CURRENT_FILE, 'r') as f: server_data = json.load(f)
    if data.get('force_overwrite') or float(data.get('last_sync', 0)) >= float(server_data.get('last_sync', 0)):
        data['last_sync'] = time.time()
        with open(CURRENT_FILE, 'w') as f: json.dump(data, f, indent=4)
        return jsonify({"status": "SUCCESS", "new_sync": data['last_sync']})
    return jsonify({"status": "CONFLICT", "server_params": server_data}), 409

@app.route('/execute_sequence', methods=['POST'])
def execute():
    threading.Thread(target=run_job_thread, args=(request.json,)).start()
    return jsonify({"status": "STARTED"})

@app.route('/panic', methods=['POST'])
def panic():
    subprocess.run(["pkill", "-9", "-f", "engine.py"])
    subprocess.run(["pkill", "-9", "-f", "rpicam-still"])
    # Status update handled by polling loop in thread
    return jsonify({"status": "ABORTED"})

@app.route('/nuke_mag', methods=['POST'])
def nuke():
    for f in glob.glob(os.path.join(CAM_MAG_DIR, "*.tif")): os.remove(f)
    return jsonify({"status": "CLEAN"})

@app.route('/')
def index(): return render_template('index.html')

@app.route('/download/<path:filename>')
def download(filename): return send_from_directory(WORKPRINT_DIR, filename, as_attachment=True)

if __name__ == "__main__": app.run(host='0.0.0.0', port=5000)