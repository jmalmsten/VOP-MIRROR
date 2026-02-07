"""
VOP Module:     app.py
Version:        v0.4.33-api
Description:    Phase IV Baseline - Timestamped WorkPrints & Parallel Engine.
"""
import subprocess, os, json, numpy as np, time, logging, glob, shutil
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# --- LOG SILENCER ---
class StatusFilter(logging.Filter):
    def filter(self, record):
        return "/status" not in record.getMessage()

log = logging.getLogger('werkzeug')
log.addFilter(StatusFilter())

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.join(BASE_DIR, "engine.py")
JOB_FILE = "/tmp/vop_job.json"
WORKPRINT_DIR = os.path.join(BASE_DIR, "WorkPrints")
CAM_MAG_DIR = os.path.join(BASE_DIR, "CamMag")

for d in [WORKPRINT_DIR, CAM_MAG_DIR]: os.makedirs(d, exist_ok=True)

progress_state = {"current": 0, "total": 0, "start_time": 0, "msg": "Idle", "status": "idle"}

def update_status(current, total, msg="Exposing", status="running"):
    global progress_state
    if current == 1: progress_state["start_time"] = time.time()
    progress_state.update({"current": current, "total": total, "msg": msg, "status": status})

def lerp(v1, v2, t): return v1 + (v2 - v1) * t
def lerp_vec(v1, v2, t): return v1 + (v2 - v1) * t

def generate_workprint(fps, burn_in):
    """FFmpeg safe WorkPrint generation with Timestamped filename."""
    ts = time.strftime("%Y%m%d_%H%M%S")
    output_filename = f"vop_workprint_{ts}.mp4"
    output_path = os.path.join(WORKPRINT_DIR, output_filename)
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    
    if not glob.glob(os.path.join(CAM_MAG_DIR, "*.tif")): return False
    
    v_filter = "scale=2048:1536:flags=neighbor,lutrgb=r=gammaval(2.2):g=gammaval(2.2):b=gammaval(2.2),format=yuv420p"
    if burn_in and os.path.exists(font):
        v_filter += f",drawtext=fontfile='{font}':text='FR\\: %{{n}}':x=w-tw-40:y=h-th-40:fontsize=48:fontcolor=white:box=1:boxcolor=black@0.6"

    cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", os.path.join(CAM_MAG_DIR, "latent_%04d.tif"),
           "-vf", v_filter, "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast", output_path]
    
    print(f"[{time.strftime('%H:%M:%S')}] AUDIT: Encoding WorkPrint -> {output_filename}")
    return subprocess.run(cmd, capture_output=True).returncode == 0

@app.route('/status')
def get_status(): return jsonify(progress_state)
@app.route('/')
def index(): return render_template('index.html')

@app.route('/preview', methods=['POST'])
def preview():
    data = request.json
    p1, p2 = np.array([float(x) for x in data['p_start'].split(',')]), np.array([float(x) for x in data['p_end'].split(',')])
    r1, r2 = np.array([float(x) for x in data['r_start'].split(',')]), np.array([float(x) for x in data['r_end'].split(',')])
    t_p = float(data.get('preview_p', 0.0))
    pos, rot = lerp_vec(p1, p2, t_p), lerp_vec(r1, r2, t_p)
    
    job = data.copy()
    job.update({"p_start": f"{pos[0]},{pos[1]},{pos[2]}", "p_end": f"{pos[0]},{pos[1]},{pos[2]}",
                "r_start": f"{rot[0]},{rot[1]},{rot[2]}", "r_end": f"{rot[0]},{rot[1]},{rot[2]}", "type": "preview"})
    with open(JOB_FILE, 'w') as f: json.dump(job, f, indent=4)
    subprocess.run(["python3", ENGINE_PATH, "--job", JOB_FILE])
    return jsonify({"status": "SUCCESS"}), 200

@app.route('/execute_sequence', methods=['POST'])
def execute_sequence():
    data = request.json
    f_start, f_end = int(data['f_start']), int(data['f_end'])
    total_seq = max(1, (f_end - f_start) + 1)
    
    p1, p2 = np.array([float(x) for x in data['p_start'].split(',')]), np.array([float(x) for x in data['p_end'].split(',')])
    r1, r2 = np.array([float(x) for x in data['r_start'].split(',')]), np.array([float(x) for x in data['r_end'].split(',')])
    s1, s2 = float(data['s_start']), float(data['s_end'])
    ph1, ph2 = float(data['ph_start']), float(data['ph_end'])

    update_status(0, total_seq, "Exposing Sequence...", "running")
    for i in range(total_seq):
        update_status(i + 1, total_seq)
        t_center = i / (total_seq - 1) if total_seq > 1 else 0
        t_step = 1.0 / (total_seq - 1) if total_seq > 1 else 0
        
        cur_sm, cur_ph = lerp(s1, s2, t_center), lerp(ph1, ph2, t_center)
        win_size = t_step * float(data.get('shutter_disc', 0.5))
        t_s, t_e = t_center - (win_size * cur_ph), t_center + (win_size * (1.0 - cur_ph))
        
        ps, pe = lerp_vec(p1, p2, t_s), lerp_vec(p1, p2, t_e)
        rs, re = lerp_vec(r1, r2, t_s), lerp_vec(r1, r2, t_e)
        
        job = data.copy()
        job.update({"p_start": f"{ps[0]},{ps[1]},{ps[2]}", "p_end": f"{pe[0]},{pe[1]},{pe[2]}",
                    "r_start": f"{rs[0]},{rs[1]},{rs[2]}", "r_end": f"{re[0]},{re[1]},{re[2]}",
                    "smear": cur_sm, "frame": f_start + i})
        with open(JOB_FILE, 'w') as f: json.dump(job, f, indent=4)
        subprocess.run(["python3", ENGINE_PATH, "--job", JOB_FILE])

    update_status(total_seq, total_seq, "Finalizing WorkPrint...", "running")
    generate_workprint(data.get('fps', 24), data.get('burn_in', True))
    update_status(total_seq, total_seq, "COMPLETE", "success")
    return jsonify({"status": "SUCCESS"}), 200

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)