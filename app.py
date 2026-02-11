"""
VOP Module:     app.py
Version:        v0.8.0
Description:    Phase V Orchestrator. Accurate smear previews and heartbeat sync.
"""
import subprocess, os, json, time, glob, shutil, threading, logging
from flask import Flask, render_template, request, jsonify, send_from_directory
import interpolator

app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.addFilter(lambda r: "/status" not in r.getMessage())

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.join(BASE_DIR, "engine.py")
CURRENT_FILE = os.path.join(BASE_DIR, "current_job.json")
CAM_MAG_DIR = os.path.join(BASE_DIR, "CamMag")
WORKPRINT_DIR = os.path.join(BASE_DIR, "WorkPrints")

progress_state = {"current": 0, "total": 0, "msg": "Idle", "status": "idle", "eta": 0, "disk": "0 GB", "latest_wp": ""}

def init_state():
    for d in [CAM_MAG_DIR, WORKPRINT_DIR]: os.makedirs(d, exist_ok=True)
    if not os.path.exists(CURRENT_FILE):
        with open(CURRENT_FILE, 'w') as f: json.dump({"v": "0.8.0", "last_sync": 0}, f)

init_state()

def run_job_thread(data):
    global progress_state
    f1, f3 = int(data['f1']), int(data['f3'])
    total = (f3 - f1) + 1
    progress_state.update({"current": 0, "total": total, "status": "running", "msg": "Exposing..."})
    
    if os.path.exists("/tmp/vop_heartbeat"): os.remove("/tmp/vop_heartbeat")
    
    sequence = []
    for i in range(total):
        t_c = i / (total - 1) if total > 1 else 0
        t_step = 1.0 / (total - 1) if total > 1 else 0
        st = interpolator.get_state_at_t(t_c, data)
        # Calculate precise smear window
        t_s = t_c - (t_step * st['sd'] * st['ph'])
        t_e = t_c + (t_step * st['sd'] * (1.0 - st['ph']))
        s_st, e_st = interpolator.get_state_at_t(t_s, data), interpolator.get_state_at_t(t_e, data)
        sequence.append({
            "p_start": ",".join(map(str, s_st['p'])), "p_end": ",".join(map(str, e_st['p'])),
            "r_start": ",".join(map(str, s_st['r'])), "r_end": ",".join(map(str, e_st['r'])),
            "c_start": s_st['c'].tolist(), "c_end": e_st['c'].tolist(),
            "cg_start": s_st['cg'].tolist(), "cg_end": e_st['cg'].tolist(),
            "smear": st['s'], "frame": f1 + i
        })
    
    with open("/tmp/vop_job.json", 'w') as f: json.dump({**data, "sequence": sequence}, f)
    proc = subprocess.Popen(["python3", ENGINE_PATH, "--job", "/tmp/vop_job.json"])
    start_time = time.time()
    
    processed = 0
    while proc.poll() is None:
        if os.path.exists("/tmp/vop_heartbeat"):
            processed += 1
            os.remove("/tmp/vop_heartbeat")
            progress_state["current"] = processed
            avg = (time.time() - start_time) / processed
            progress_state["eta"] = int(avg * (total - processed))
        time.sleep(0.5)

    if len(glob.glob(os.path.join(CAM_MAG_DIR, "*.tif"))) > 0:
        progress_state["msg"] = "Workprinting..."
        wp_name = f"vop_wp_{time.strftime('%H%M%S')}.mp4"
        subprocess.run(["ffmpeg", "-y", "-framerate", str(data.get('fps', 24)), "-pattern_type", "glob", "-i", os.path.join(CAM_MAG_DIR, "*.tif"),
                        "-vf", "scale=2048:1536,format=yuv420p", "-c:v", "libx264", "-crf", "23", os.path.join(WORKPRINT_DIR, wp_name)])
        progress_state["latest_wp"] = wp_name

    progress_state.update({"status": "idle", "msg": "COMPLETE", "current": total})

@app.route('/preview', methods=['POST'])
def preview():
    if progress_state["status"] == "running": return jsonify({"status": "BUSY"}), 423
    data = request.json
    f1, f3 = int(data['f1']), int(data['f3'])
    t_c = (int(data['probe_frame']) - f1) / (f3 - f1) if f3 != f1 else 0
    t_step = 1.0 / (f3 - f1) if f3 != f1 else 0
    st = interpolator.get_state_at_t(t_c, data)
    
    # Smear Range for Cam Preview
    t_s = t_c - (t_step * st['sd'] * st['ph'])
    t_e = t_c + (t_step * st['sd'] * (1.0 - st['ph']))
    s_st, e_st = interpolator.get_state_at_t(t_s, data), interpolator.get_state_at_t(t_e, data)
    
    job = {**data, 
           "p_start": ",".join(map(str, s_st['p'])), "p_end": ",".join(map(str, e_st['p'])),
           "r_start": ",".join(map(str, s_st['r'])), "r_end": ",".join(map(str, e_st['r'])),
           "c_start": s_st['c'].tolist(), "c_end": e_st['c'].tolist(),
           "cg_start": s_st['cg'].tolist(), "cg_end": e_st['cg'].tolist(),
           "smear": st['s'], "type": data.get('type', 'preview')}
    
    with open("/tmp/vop_job.json", 'w') as f: json.dump(job, f)
    subprocess.run(["python3", ENGINE_PATH, "--job", "/tmp/vop_job.json"])
    return jsonify({"status": "SUCCESS"})

@app.route('/status')
def get_status():
    free_gb = shutil.disk_usage(BASE_DIR).free / (1024.0**3)
    progress_state["disk"] = f"{free_gb:.1f} GB"
    with open(CURRENT_FILE, 'r') as f: params = json.load(f)
    return jsonify({**progress_state, "params": params})

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
    progress_state["status"] = "idle"
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