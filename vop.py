"""
VOP Module:     vop.py
Version:        v0.2.15
Description:    Main Entry Point. Flask Web Server.
                Fixed /get_img_aspect silently tripping on hidden files and 
                breaking the Fit FOV math for non-16:9 masks.
"""
import os
import sys
import json
import subprocess
import logging
import cv2
import glob
import math

sys.path.append(os.path.join(os.path.dirname(__file__), "modules"))
from flask import Flask, jsonify, request, render_template, send_from_directory

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJ_MAG_DIR = os.path.join(BASE_DIR, "ProjMag")
PROJ_BIPACK_DIR = os.path.join(BASE_DIR, "ProjBiPack")
CAM_MAG_DIR = os.path.join(BASE_DIR, "CamMag")
CURRENT_JOB_FILE = os.path.join(BASE_DIR, "current_job.json")

for d in [PROJ_MAG_DIR, PROJ_BIPACK_DIR, CAM_MAG_DIR, os.path.join(BASE_DIR, "WorkPrints")]:
    os.makedirs(d, exist_ok=True)

engine_process = None

def calculate_static_fit_scale(fov, ref_z, img_aspect, screen_width=1920, screen_height=1080):
    z_dist = abs(float(ref_z))
    if z_dist == 0: z_dist = 0.1 
        
    fov_rad = math.radians(float(fov))
    screen_aspect = screen_width / screen_height
    
    # Calculate full physical dimensions of the camera's view
    frustum_h = 2.0 * z_dist * math.tan(fov_rad / 2.0)
    frustum_w = frustum_h * screen_aspect
    
    # The unscaled OpenGL quad spans from -1 to 1, meaning its base size is 2x2 units.
    # We calculate the scale required to fit the width and the height separately,
    # remembering to divide by 2.0 because of the quad's base size.
    scale_for_width = frustum_w / (2.0 * img_aspect)
    scale_for_height = frustum_h / 2.0
    
    # Return whichever scale is smaller to guarantee it fits entirely (letterbox or pillarbox)
    return min(scale_for_width, scale_for_height)

def dispatch_engine(task_type, payload):
    global engine_process
    print(f"\n[VOP SERVER] ACTION: {task_type.upper()}")
    
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
def index(): 
    return render_template('index.html')

@app.route('/status', methods=['GET'])
def status():
    global engine_process
    wp_dir = os.path.join(BASE_DIR, "WorkPrints")
    latest_wp = ""
    try:
        wps = glob.glob(os.path.join(wp_dir, "*.mp4"))
        if wps: latest_wp = os.path.basename(max(wps, key=os.path.getctime))
    except: pass

    params = {}
    if os.path.exists(CURRENT_JOB_FILE):
        try:
            with open(CURRENT_JOB_FILE, 'r') as f: params = json.load(f)
        except: pass

    if engine_process is not None and engine_process.poll() is None:
        try:
            with open("/tmp/vop_heartbeat", "r") as f:
                hb = json.load(f)
                return jsonify({"status": "rendering", "heartbeat": hb, "params": params, "latest_wp": latest_wp})
        except:
            return jsonify({"status": "rendering", "params": params, "latest_wp": latest_wp})
    
    return jsonify({"status": "idle", "params": params, "latest_wp": latest_wp, "workprint": f"/workprints/{latest_wp}" if latest_wp else None})

@app.route('/upload_target', methods=['POST'])
def upload_target():
    print("[VOP SERVER] UPLOADING: ProjMag Target")
    file = request.files['file']
    for f in os.listdir(PROJ_MAG_DIR): os.remove(os.path.join(PROJ_MAG_DIR, f))
    file.save(os.path.join(PROJ_MAG_DIR, file.filename))
    return jsonify({"status": "ok", "filename": file.filename})

@app.route('/upload_proj_bipack', methods=['POST'])
def upload_proj_bipack():
    print("[VOP SERVER] UPLOADING: ProjBiPack Mask")
    file = request.files['file']
    for f in os.listdir(PROJ_BIPACK_DIR): os.remove(os.path.join(PROJ_BIPACK_DIR, f))
    file.save(os.path.join(PROJ_BIPACK_DIR, file.filename))
    return jsonify({"status": "ok", "filename": file.filename})

@app.route('/nuke_proj_mag', methods=['POST'])
def nuke_proj_mag():
    print("[VOP SERVER] ACTION: NUKE PROJ MAG")
    for f in os.listdir(PROJ_MAG_DIR): os.remove(os.path.join(PROJ_MAG_DIR, f))
    return jsonify({"status": "ok"})

@app.route('/nuke_proj_bipack', methods=['POST'])
def nuke_proj_bipack():
    print("[VOP SERVER] ACTION: NUKE PROJ BIPACK")
    for f in os.listdir(PROJ_BIPACK_DIR): os.remove(os.path.join(PROJ_BIPACK_DIR, f))
    return jsonify({"status": "ok"})

@app.route('/get_img_aspect', methods=['GET'])
def get_img_aspect():
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
    dispatch_engine('preview', request.json)
    return jsonify({"status": "started"})

@app.route('/cam_preview', methods=['POST'])
def cam_preview():
    dispatch_engine('cam_preview', request.json)
    return jsonify({"status": "started"})

@app.route('/execute', methods=['POST'])
def execute_seq():
    dispatch_engine('execute', request.json)
    return jsonify({"status": "started"})

@app.route('/panic', methods=['POST'])
def panic():
    print("[VOP SERVER] ACTION: PANIC STOP")
    global engine_process
    if engine_process: engine_process.kill()
    subprocess.run(["pkill", "-9", "rpicam-still"])
    return jsonify({"status": "panic_executed"})

@app.route('/nuke_mag', methods=['POST'])
def nuke_mag():
    print("[VOP SERVER] ACTION: NUKE CAM MAG")
    for f in os.listdir(CAM_MAG_DIR):
        if f.endswith(".tif"): os.remove(os.path.join(CAM_MAG_DIR, f))
    return jsonify({"status": "mag_cleared"})

@app.route('/workprints/<filename>')
def serve_workprint(filename):
    return send_from_directory(os.path.join(BASE_DIR, "WorkPrints"), filename)

if __name__ == '__main__':
    print("=========================================")
    print(" VOP Server is online.")
    print("=========================================")
    app.run(host='0.0.0.0', port=5000, debug=False)