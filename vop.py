"""
VOP Module:     vop.py
Version:        v0.2.15
Location:       vop.py
Description:    Main Entry Point. Flask Web Server.               
"""
import os
import sys
import json
import subprocess
import logging
import cv2
import glob
import math
import socket

idle_process = None

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

def launch_idle_screen(port=5000):
    # Spawns the Pygame idle screen as a non-blocking background process
    # using the global idle_process tracker initialized at the top of the file.
    global idle_process
    
    # Ensure no duplicate processes are spawned to prevent framebuffer lockups
    kill_idle_screen()

    idle_path = os.path.join(BASE_DIR, "modules", "idle_screen.py")
    # sys.executable ensures the subprocess uses the active venv Python binary
    idle_process = subprocess.Popen([sys.executable, idle_path, str(port)])

def kill_idle_screen():
    # Terminates the Pygame process to free up the hardware framebuffer for the engine.
    global idle_process
    if idle_process is not None and idle_process.poll() is None:
        idle_process.kill()
        idle_process = None

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

    if ext in video_ext:
        print(f"[VOP SERVER] Video detected! Extracting {filepath} to TIFF sequence...")

        # The output pattern guarantees files like 0000.tif, 0001.tif, etc.
        output_pattern = os.path.join(target_dir, "%04d.tif")

        cmd = [
            "ffmpeg", "-y", "-i", filepath,
            "-start_number", "0",
            output_pattern
        ]

        try:
            # Supress output to keep the terminal clean, but let errors bubble up
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("[VOP SERVER] Frame extraction complete.")

            # Clean up the original video container
            os.remove(filepath)
        
        except subprocess.CalledProcessError as e:
            print("[VOP SERVER] CRITICAL: FFMPEG ingestion failed: {e}")
            
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

    ## Terminate the idle screen immediately before launching the render engine
    ## This prevents KMSDRM resource locking conflicts on the Pi hardware.
    kill_idle_screen()
    
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
    global engine_process, idle_process
    wp_dir = os.path.join(BASE_DIR, "WorkPrints")
    latest_wp = ""
    try:
        wps = glob.glob(os.path.join(wp_dir, "*.mp4"))
        if wps: latest_wp = os.path.basename(max(wps, key=os.path.getctime))
    except: pass
    
    # v0.2.17 Update: Base dictionary merge for robust state hydration
    params = {}
    
    # 1. ALWAYS load the default configuration first to establish the baseline
    default_job_file = os.path.join(BASE_DIR, "configs", "default_job.json")
    if os.path.exists(default_job_file):
        try:
            with open(default_job_file, 'r') as f: 
                params = json.load(f)
        except: pass

    # 2. Layer the active session over the top to overwrite defaults with user choices
    if os.path.exists(CURRENT_JOB_FILE):
        try:
            with open(CURRENT_JOB_FILE, 'r') as f: 
                active_job = json.load(f)
                if active_job:
                    params.update(active_job)
        except: pass

    # 3. Engine heartbeat check and required Flask return statements
    if engine_process is not None and engine_process.poll() is None:
        try:
            with open("/tmp/vop_heartbeat", "r") as f:
                hb = json.load(f)
                return jsonify({"status": "rendering", "heartbeat": hb, "params": params, "latest_wp": latest_wp})
        except:
            return jsonify({"status": "rendering", "params": params, "latest_wp": latest_wp})
    
    # 4. ENGINE IS DEAD/IDLE
    # If the engine is not running, but the idle screen is also dead, revive it.
    if idle_process is None or idle_process.poll() is not None:
        launch_idle_screen(5000)

    return jsonify({"status": "idle", "params": params, "latest_wp": latest_wp, "workprint": f"/workprints/{latest_wp}" if latest_wp else None})

@app.route('/upload_target', methods=['POST'])
def upload_target():
    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    print(f"[VOP SERVER] ACTION: UPLOAD PROJ MAG -> {file.filename}")

    # Clear out the old files
    for f in os.listdir(PROJ_MAG_DIR):
        os.remove(os.path.join(PROJ_MAG_DIR, f))
    
    # Save the new file
    filepath = os.path.join(PROJ_MAG_DIR, file.filename)
    file.save(filepath)
    
    # Kick off the ingestion module ---
    process_video_ingestion(filepath, PROJ_MAG_DIR)

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

    # Ensure the idle screen is also terminated on a hard stop command
    kill_idle_screen()

    if engine_process: engine_process.kill()
    subprocess.run(["pkill", "-9", "rpicam-still"])
    return jsonify({"status": "panic_executed"})

@app.route('/nuke_mag', methods=['POST'])
def nuke_mag():
    print("[VOP SERVER] ACTION: NUKE CAM MAG")
    for f in os.listdir(CAM_MAG_DIR):
        if f.endswith(".tif"): os.remove(os.path.join(CAM_MAG_DIR, f))
    return jsonify({"status": "mag_cleared"})

@app.route('/nuke_job', methods=['POST'])
def nuke_job():
    print("[VOP SERVER] ACTION: NUKE CURRENT JOB")
    if os.path.exists(CURRENT_JOB_FILE):
        os.remove(CURRENT_JOB_FILE)
    return jsonify({"status": "job_nuked"})

@app.route('/workprints/<filename>')
def serve_workprint(filename):
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
        
if __name__ == '__main__':
    port = 5000
    ip_addr = get_ip()

    # Clear terminal space and print the formatted telemetry block
    print("\n" + "="*50)
    print(f" VOP Server is online.")
    print(f" Status: Waiting for jobs")
    print(f" WebGUI: http://{ip_addr}:{port}")
    print("="*50 + "\n" )

    # Launch the idle screen to the monitor upon initial system startup
    launch_idle_screen(port)

    app.run(host='0.0.0.0', port=port, debug=False)