"""
VOP Module:     app.py
Version:        v0.4.31-api
Description:    Phase IV Baseline. Fixed AWB inputs.
"""
import subprocess, os, json, numpy as np, time, logging, glob, shutil
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

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

def check_disk_space():
    total, used, free = shutil.disk_usage(BASE_DIR)
    return free / (1024**3)

def lerp(v1, v2, t): return v1 + (v2 - v1) * t
def lerp_vec(v1, v2, t): return v1 + (v2 - v1) * t

def generate_workprint(fps, burn_in, meta_list):
    output_path = os.path.join(WORKPRINT_DIR, "vop_workprint_latest.mp4")
    font = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    if not glob.glob(os.path.join(CAM_MAG_DIR, "*.tif")): return False
    
    v_base = "scale=2048:1536:flags=neighbor,lutrgb=r=gammaval(2.2):g=gammaval(2.2):b=gammaval(2.2),format=yuv420p"
    if burn_in and os.path.exists(font):
        meta_file = os.path.join(WORKPRINT_DIR, "ffmpeg_metadata.txt")
        with open(meta_file, 'w') as f:
            for i, m in enumerate(meta_list):
                f.write(f"{i} metadata add vop_time='{m['dur']:.2f}s';\n")
                f.write(f"{i} metadata add vop_xyz='{m['tx_pos']}';\n")
                f.write(f"{i} metadata add vop_pyr='{m['tx_rot']}';\n")
                f.write(f"{i} metadata add vop_sm='{m['smear']:.2f}s';\n")
                f.write(f"{i} metadata add vop_ph='{m['phase']:.2f}';\n")
        
        vf = f"{v_base},sendcmd=f='{meta_file}'," \
             f"drawtext=fontfile='{font}':text='PROC\\: %{{metadata\\:vop_time}}':x=40:y=h-th-40:fontsize=30:fontcolor=white:box=1:boxcolor=black@0.7," \
             f"drawtext=fontfile='{font}':text='SMEAR\\: %{{metadata\\:vop_sm}} ph %{{metadata\\:vop_ph}}':x=40:y=h-th-80:fontsize=30:fontcolor=white:box=1:boxcolor=black@0.7," \
             f"drawtext=fontfile='{font}':text='FR\\: %{{n}}':x=w-tw-40:y=h-th-40:fontsize=36:fontcolor=white:box=1:boxcolor=black@0.7," \
             f"drawtext=fontfile='{font}':text='XYZ\\: %{{metadata\\:vop_xyz}}':x=(w-tw)/2:y=h-th-80:fontsize=28:fontcolor=yellow:box=1:boxcolor=black@0.7," \
             f"drawtext=fontfile='{font}':text='PYR\\: %{{metadata\\:vop_pyr}}':x=(w-tw)/2:y=h-th-35:fontsize=28:fontcolor=cyan:box=1:boxcolor=black@0.7"
    else: vf = v_base

    cmd = ["ffmpeg", "-y", "-framerate", str(fps), "-i", os.path.join(CAM_MAG_DIR, "latent_%04d.tif"),
           "-vf", vf, "-c:v", "libx264", "-crf", "23", "-preset", "ultrafast", output_path]
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
    s1, s2 = float(data['s_start']), float(data['s_end'])
    ph1, ph2 = float(data['ph_start']), float(data['ph_end'])
    t_p = float(data.get('preview_p', 0.0))
    pos, rot, sm, ph = lerp_vec(p1, p2, t_p), lerp_vec(r1, r2, t_p), lerp(s1, s2, t_p), lerp(ph1, ph2, t_p)
    job = data.copy()
    job.update({"p_start": f"{pos[0]},{pos[1]},{pos[2]}", "p_end": f"{pos[0]},{pos[1]},{pos[2]}",
                "r_start": f"{rot[0]},{rot[1]},{rot[2]}", "r_end": f"{rot[0]},{rot[1]},{rot[2]}",
                "smear": sm, "phase": ph, "type": "preview"})
    with open(JOB_FILE, 'w') as f: json.dump(job, f, indent=4)
    subprocess.run(["python3", ENGINE_PATH, "--job", JOB_FILE])
    return jsonify({"status": "SUCCESS"}), 200

@app.route('/execute_sequence', methods=['POST'])
def execute_sequence():
    if check_disk_space() < 2.0: return jsonify({"status": "ERROR", "message": "Low Disk"}), 400
    data = request.json
    f_start, f_end = int(data['f_start']), int(data['f_end'])
    total_seq = max(1, (f_end - f_start) + 1)
    sh_disc = float(data.get('shutter_disc', 0.5))
    
    p1, p2 = np.array([float(x) for x in data['p_start'].split(',')]), np.array([float(x) for x in data['p_end'].split(',')])
    r1, r2 = np.array([float(x) for x in data['r_start'].split(',')]), np.array([float(x) for x in data['r_end'].split(',')])
    s1, s2 = float(data['s_start']), float(data['s_end'])
    ph1, ph2 = float(data['ph_start']), float(data['ph_end'])

    frame_meta = []
    update_status(0, total_seq, "Exposing Sequence...", "running")
    for i in range(total_seq):
        update_status(i + 1, total_seq)
        start_t = time.time()
        t_center = i / (total_seq - 1) if total_seq > 1 else 0
        t_step = 1.0 / (total_seq - 1) if total_seq > 1 else 0
        cur_sm, cur_ph = lerp(s1, s2, t_center), lerp(ph1, ph2, t_center)
        win_size = t_step * sh_disc
        t_s, t_e = t_center - (win_size * cur_ph), t_center + (win_size * (1.0 - cur_ph))
        ps, pe = lerp_vec(p1, p2, t_s), lerp_vec(p1, p2, t_e)
        rs, re = lerp_vec(r1, r2, t_s), lerp_vec(r1, r2, t_e)
        
        job = data.copy()
        job.update({"p_start": f"{ps[0]},{ps[1]},{ps[2]}", "p_end": f"{pe[0]},{pe[1]},{pe[2]}",
                    "r_start": f"{rs[0]},{rs[1]},{rs[2]}", "r_end": f"{re[0]},{re[1]},{re[2]}",
                    "smear": cur_sm, "frame": f_start + i})
        with open(JOB_FILE, 'w') as f: json.dump(job, f, indent=4)
        subprocess.run(["python3", ENGINE_PATH, "--job", JOB_FILE])
        frame_meta.append({"dur": time.time() - start_t, "tx_pos": f"{ps[0]:.1f}->{pe[0]:.1f}", 
                           "tx_rot": f"{rs[0]:.0f}->{re[0]:.0f}", "smear": cur_sm, "phase": cur_ph})

    generate_workprint(data.get('fps', 24), True, frame_meta)
    update_status(total_seq, total_seq, "COMPLETE", "success")
    return jsonify({"status": "SUCCESS"}), 200

if __name__ == "__main__": app.run(host='0.0.0.0', port=5000)