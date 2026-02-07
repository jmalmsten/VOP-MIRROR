"""
VOP Module:     app.py
Version:        v0.4.38-api
Description:    Phase IV Final Baseline - Fixed WorkPrint and Subframe Math.
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
    "f_start": 1, "f_end": 24, "shutter_disc": 0.5, "fps": 24, "gain": 1.0, 
    "fov": 45, "image": "vop_logo_mockup_400px.png", "awb_r": 3.18, "awb_b": 1.45,
    "p_start": "0.0,0.0,-5.0", "p_end": "0.0,0.0,-2.0",
    "r_start": "0.0,0.0,0.0", "r_end": "0.0,0.0,0.0",
    "s_start": 1.0, "s_end": 4.0, "ph_start": 0.5, "ph_end": 0.5,
    "c_start": [1,0,0], "c_end": [0,0,1], 
    "c_start_hex": "#ff0000", "c_end_hex": "#0000ff",
    "tiff_compression": "zip", "version": "0.4.38"
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

def generate_workprint(fps, burn_in):
    ts = time.strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(WORKPRINT_DIR, f"vop_workprint_{ts}.mp4")
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    
    # Check for latent files
    files = glob.glob(os.path.join(CAM_MAG_DIR, "latent_*.tif"))
    if not files: return False
    
    vf = "scale=2048:1536:flags=neighbor,lutrgb=r=gammaval(2.2):g=gammaval(2.2):b=gammaval(2.2),format=yuv420p"
    if burn_in and os.path.exists(font):
        vf += f",drawtext=fontfile='{font}':text='FR\\: %{{n}}':x=w-tw-40:y=h-th-40:fontsize=48:fontcolor=white:box=1:boxcolor=black@0.6"
    
    cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-pattern_type", "glob", "-i", os.path.join(CAM_MAG_DIR, "*.tif"),
           "-vf", vf, "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast", output_path]
    
    res = subprocess.run(cmd, capture_output=True)
    return res.returncode == 0

@app.route('/status')
def get_status(): return jsonify(progress_state)

@app.route('/panic', methods=['POST'])
def panic():
    global current_proc, progress_state
    if current_proc:
        os.kill(current_proc.pid, signal.SIGTERM)
        current_proc = None
        progress_state.update({"status": "error", "msg": "KILLED", "eta": 0})
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
    f_start, f_end = int(data['f_start']), int(data['f_end'])
    target_f = int(data.get('probe_frame', f_start))
    sub_t = float(data.get('probe_sub', 0.5))
    
    total_frames = max(1, (f_end - f_start))
    t_center = (target_f - f_start) / total_frames if total_frames > 0 else 0
    t_step = 1.0 / total_frames if total_frames > 0 else 0
    
    cur_ph = lerp(float(data['ph_start']), float(data['ph_end']), t_center)
    win_size = t_step * float(data['shutter_disc'])
    actual_t = lerp(t_center - (win_size * cur_ph), t_center + (win_size * (1.0 - cur_ph)), sub_t)
    
    p1, p2 = np.array([float(x) for x in data['p_start'].split(',')]), np.array([float(x) for x in data['p_end'].split(',')])
    r1, r2 = np.array([float(x) for x in data['r_start'].split(',')]), np.array([float(x) for x in data['r_end'].split(',')])
    pos, rot = lerp_vec(p1, p2, actual_t), lerp_vec(r1, r2, actual_t)
    
    job = data.copy()
    job.update({"p_start": f"{pos[0]},{pos[1]},{pos[2]}", "p_end": f"{pos[0]},{pos[1]},{pos[2]}",
                "r_start": f"{rot[0]},{rot[1]},{rot[2]}", "r_end": f"{rot[0]},{rot[1]},{rot[2]}",
                "preview_p": actual_t, "type": "preview"})
    with open(JOB_FILE, 'w') as f: json.dump(job, f)
    subprocess.run(["python3", ENGINE_PATH, "--job", JOB_FILE])
    return jsonify({"status": "SUCCESS"})

@app.route('/execute_sequence', methods=['POST'])
def execute_sequence():
    global current_proc, progress_state
    data = request.json
    save_config(data)
    progress_state["params"] = data
    f_start, f_end = int(data['f_start']), int(data['f_end'])
    total_seq = max(1, (f_end - f_start) + 1)
    s1, s2 = float(data['s_start']), float(data['s_end'])
    avg_overhead = 4.5
    
    progress_state.update({"current": 0, "total": total_seq, "msg": "Exposing...", "status": "running"})
    for i in range(total_seq):
        if progress_state["status"] != "running": break
        t_center = i / (total_seq - 1) if total_seq > 1 else 0
        t_step = 1.0 / (total_seq - 1) if total_seq > 1 else 0
        cur_sm = lerp(s1, s2, t_center)
        cur_ph = lerp(float(data['ph_start']), float(data['ph_end']), t_center)
        
        rem_frames = total_seq - i
        rem_smear = sum([lerp(s1, s2, j/(total_seq-1)) for j in range(i, total_seq)]) if total_seq > 1 else cur_sm
        progress_state["eta"] = rem_smear + (rem_frames * avg_overhead)
        progress_state["current"] = i + 1

        win_size = t_step * float(data['shutter_disc'])
        t_s, t_e = t_center - (win_size * cur_ph), t_center + (win_size * (1.0 - cur_ph))
        
        ps, pe = lerp_vec(np.array([float(x) for x in data['p_start'].split(',')]), np.array([float(x) for x in data['p_end'].split(',')]), t_s), \
                 lerp_vec(np.array([float(x) for x in data['p_start'].split(',')]), np.array([float(x) for x in data['p_end'].split(',')]), t_e)
        rs, re = lerp_vec(np.array([float(x) for x in data['r_start'].split(',')]), np.array([float(x) for x in data['r_end'].split(',')]), t_s), \
                 lerp_vec(np.array([float(x) for x in data['r_start'].split(',')]), np.array([float(x) for x in data['r_end'].split(',')]), t_e)

        job = data.copy()
        job.update({"p_start": f"{ps[0]},{ps[1]},{ps[2]}", "p_end": f"{pe[0]},{pe[1]},{pe[2]}",
                    "r_start": f"{rs[0]},{rs[1]},{rs[2]}", "r_end": f"{re[0]},{re[1]},{re[2]}",
                    "smear": cur_sm, "frame": f_start + i})
        with open(JOB_FILE, 'w') as f: json.dump(job, f)
        current_proc = subprocess.Popen(["python3", ENGINE_PATH, "--job", JOB_FILE])
        current_proc.wait()

    if progress_state["status"] == "running":
        progress_state["msg"] = "Writing Disk..."
        time.sleep(3) # Wait for final async save
        progress_state["msg"] = "WorkPrint..."
        generate_workprint(data.get('fps', 24), True)
        progress_state.update({"status": "success", "msg": "COMPLETE", "eta": 0})
    return jsonify({"status": "SUCCESS"})

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)