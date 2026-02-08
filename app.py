"""
VOP Module:     app.py
Version:        v0.5.1-api
Description:    Phase V - Quadratic Bézier Curves & Parameter Toggles.
"""
import subprocess, os, json, numpy as np, time, logging, glob, shutil, signal
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

class StatusFilter(logging.Filter):
    def filter(self, record): return "/status" not in record.getMessage()

log = logging.getLogger('werkzeug')
log.addFilter(StatusFilter())

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.join(BASE_DIR, "engine.py")
JOB_FILE = "/tmp/vop_job.json"
CONFIG_FILE = os.path.join(BASE_DIR, "vop_config.json")
WORKPRINT_DIR = os.path.join(BASE_DIR, "WorkPrints")
CAM_MAG_DIR = os.path.join(BASE_DIR, "CamMag")

for d in [WORKPRINT_DIR, CAM_MAG_DIR]: os.makedirs(d, exist_ok=True)

DEFAULT_PARAMS = {
    "f1": 1, "f2": 24, "f3": 48,
    "fps": 24, "gain": 1.0, "fov": 45, "image": "vop_logo_mockup_400px.png",
    "awb_r": 3.18, "awb_b": 1.45,
    "p1": "0.0,0.0,-5.0", "p2": "0.0,0.0,-3.5", "p3": "0.0,0.0,-2.0",
    "r1": "0.0,0.0,0.0", "r2": "0.0,0.0,0.0", "r3": "0.0,0.0,0.0",
    "s1": 1.0, "s2": 1.0, "s3": 1.0,
    "ph1": 0.5, "ph2": 0.5, "ph3": 0.5,
    "sd1": 0.5, "sd2": 0.5, "sd3": 0.5,
    "c1_hex": "#ff0000", "c2_hex": "#00ff00", "c3_hex": "#0000ff",
    "p_mode": "linear", "r_mode": "linear", "s_mode": "linear",
    "tiff_compression": "zip", "version": "0.5.1"
}

current_proc = None
progress_state = {"current": 0, "total": 0, "msg": "Idle", "status": "idle", "eta": 0, "params": DEFAULT_PARAMS}

def save_config(params):
    with open(CONFIG_FILE, 'w') as f: json.dump(params, f, indent=4)

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
                if cfg.get("version") == DEFAULT_PARAMS["version"]: return cfg
        except: pass
    return DEFAULT_PARAMS

progress_state["params"] = load_config()

def lerp(v1, v2, t): return v1 + (v2 - v1) * t
def lerp_vec(v1, v2, t): return v1 + (v2 - v1) * t

def quadratic_bezier(p0, p1, p2, t):
    """Standard 3-point Bézier formula: (1-t)^2*P0 + 2(1-t)t*P1 + t^2*P2"""
    return (1-t)**2 * p0 + 2*(1-t)*t * p1 + t**2 * p2

def hex_to_rgb(hex_str):
    h = hex_str.lstrip('#')
    return [int(h[i:i+2], 16)/255.0 for i in (0, 2, 4)]

def get_state_at_t(t, data):
    """
    t is 0.0 to 1.0 across the entire f1 -> f3 range.
    Handles Linear vs Smooth toggles.
    """
    f1, f2, f3 = int(data['f1']), int(data['f2']), int(data['f3'])
    
    # --- Helper for segment determination (Linear fallback) ---
    if t <= (f2-f1)/(f3-f1) if f3!=f1 else 0:
        seg_t = t / ((f2-f1)/(f3-f1)) if f2!=f1 else 0
        k_s, k_e = "1", "2"
    else:
        seg_t = (t - (f2-f1)/(f3-f1)) / ((f3-f2)/(f3-f1)) if f3!=f2 else 0
        k_s, k_e = "2", "3"

    def calc_param(key, is_vec=False):
        v0, v1, v2 = data[f'{key}1'], data[f'{key}2'], data[f'{key}3']
        if is_vec:
            v0, v1, v2 = np.array([float(x) for x in v0.split(',')]), \
                         np.array([float(x) for x in v1.split(',')]), \
                         np.array([float(x) for x in v2.split(',')])
        else:
            v0, v1, v2 = float(v0), float(v1), float(v2)

        if data.get(f'{key}_mode') == 'smooth':
            return quadratic_bezier(v0, v1, v2, t)
        else:
            # Linear Piecewise
            vs, ve = (v0, v1) if k_s == "1" else (v1, v2)
            return lerp_vec(vs, ve, seg_t) if is_vec else lerp(vs, ve, seg_t)

    return {
        "p": calc_param('p', True),
        "r": calc_param('r', True),
        "s": calc_param('s'),
        "ph": lerp(float(data[f'ph{k_s}']), float(data[f'ph{k_e}']), seg_t),
        "sd": lerp(float(data[f'sd{k_s}']), float(data[f'sd{k_e}']), seg_t),
        "c_s": hex_to_rgb(data[f'c{k_s}_hex']),
        "c_e": hex_to_rgb(data[f'c{k_e}_hex']),
        "seg_t": seg_t
    }

def generate_workprint(fps, burn_in):
    ts = time.strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(WORKPRINT_DIR, f"vop_workprint_{ts}.mp4")
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if not glob.glob(os.path.join(CAM_MAG_DIR, "latent_*.tif")): return False
    vf = "scale=2048:1536:flags=neighbor,lutrgb=r=gammaval(2.2):g=gammaval(2.2):b=gammaval(2.2),format=yuv420p"
    if burn_in and os.path.exists(font):
        vf += f",drawtext=fontfile='{font}':text='FR\\: %{{n}}':x=w-tw-40:y=h-th-40:fontsize=48:fontcolor=white:box=1:boxcolor=black@0.6"
    cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-pattern_type", "glob", "-i", os.path.join(CAM_MAG_DIR, "*.tif"),
           "-vf", vf, "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast", output_path]
    return subprocess.run(cmd, capture_output=True).returncode == 0

@app.route('/status')
def get_status(): return jsonify(progress_state)

@app.route('/panic', methods=['POST'])
def panic():
    global current_proc, progress_state
    if current_proc:
        os.kill(current_proc.pid, signal.SIGTERM)
        current_proc = None
        progress_state.update({"status": "error", "msg": "ABORTED", "eta": 0})
    return jsonify({"status": "SUCCESS"})

@app.route('/nuke_mag', methods=['POST'])
def nuke_mag():
    files = glob.glob(os.path.join(CAM_MAG_DIR, "*.tif"))
    for f in files: os.remove(f)
    return jsonify({"status": "SUCCESS", "count": len(files)})

@app.route('/')
def index(): return render_template('index.html')

@app.route('/preview', methods=['POST'])
def preview():
    data = request.json
    save_config(data)
    progress_state["params"] = data
    f1, f3 = int(data['f1']), int(data['f3'])
    target_f = int(data.get('probe_frame', f1))
    sub_t = float(data.get('probe_sub', 0.5))
    
    global_t_center = (target_f - f1) / (f3 - f1) if f3 != f1 else 0
    t_step = 1.0 / (f3 - f1) if f3 != f1 else 0
    
    state = get_state_at_t(global_t_center, data)
    win_size = t_step * state['sd']
    actual_t = lerp(global_t_center - (win_size * state['ph']), global_t_center + (win_size * (1.0 - state['ph'])), sub_t)
    
    probe_state = get_state_at_t(actual_t, data)
    job = data.copy()
    job.update({
        "p_start": f"{probe_state['p'][0]},{probe_state['p'][1]},{probe_state['p'][2]}",
        "p_end": f"{probe_state['p'][0]},{probe_state['p'][1]},{probe_state['p'][2]}",
        "r_start": f"{probe_state['r'][0]},{probe_state['r'][1]},{probe_state['r'][2]}",
        "r_end": f"{probe_state['r'][0]},{probe_state['r'][1]},{probe_state['r'][2]}",
        "c_start": probe_state['c_s'], "c_end": probe_state['c_e'],
        "preview_p": probe_state['seg_t'], "type": "preview"
    })
    with open(JOB_FILE, 'w') as f: json.dump(job, f)
    subprocess.run(["python3", ENGINE_PATH, "--job", JOB_FILE])
    return jsonify({"status": "SUCCESS"})

@app.route('/execute_sequence', methods=['POST'])
def execute_sequence():
    global current_proc, progress_state
    data = request.json
    save_config(data)
    progress_state["params"] = data
    f1, f3 = int(data['f1']), int(data['f3'])
    total_seq = (f3 - f1) + 1
    
    progress_state.update({"current": 0, "total": total_seq, "msg": "Exposing...", "status": "running"})
    for i in range(total_seq):
        if progress_state["status"] != "running": break
        cur_f = f1 + i
        t_center = i / (total_seq - 1) if total_seq > 1 else 0
        t_step = 1.0 / (total_seq - 1) if total_seq > 1 else 0
        
        state = get_state_at_t(t_center, data)
        progress_state.update({"current": i+1, "eta": (total_seq-i)*(state['s']+4.5)})

        win_size = t_step * state['sd']
        t_s, t_e = t_center - (win_size * state['ph']), t_center + (win_size * (1.0 - state['ph']))
        
        s_state, e_state = get_state_at_t(t_s, data), get_state_at_t(t_e, data)
        
        job = data.copy()
        job.update({
            "p_start": f"{s_state['p'][0]},{s_state['p'][1]},{s_state['p'][2]}",
            "p_end": f"{e_state['p'][0]},{e_state['p'][1]},{e_state['p'][2]}",
            "r_start": f"{s_state['r'][0]},{s_state['r'][1]},{s_state['r'][2]}",
            "r_end": f"{e_state['r'][0]},{e_state['r'][1]},{e_state['r'][2]}",
            "c_start": s_state['c_s'], "c_end": s_state['c_e'],
            "smear": state['s'], "frame": cur_f
        })
        with open(JOB_FILE, 'w') as f: json.dump(job, f)
        current_proc = subprocess.Popen(["python3", ENGINE_PATH, "--job", JOB_FILE])
        current_proc.wait()

    if progress_state["status"] == "running":
        progress_state["msg"] = "WorkPrint..."
        time.sleep(2)
        generate_workprint(data.get('fps', 24), True)
        progress_state.update({"status": "success", "msg": "COMPLETE", "eta": 0})
    return jsonify({"status": "SUCCESS"})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)