"""
VOP Module:     app.py
Version:        v0.6.1
Description:    Restored ETA and Color persistence.
"""
import subprocess, os, json, time, glob, shutil, logging
from flask import Flask, render_template, request, jsonify, send_from_directory
import interpolator

app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.addFilter(lambda r: "/status" not in r.getMessage())

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.join(BASE_DIR, "engine.py")
STATE_FILE = os.path.join(BASE_DIR, "vop_state.json")
CAM_MAG_DIR = os.path.join(BASE_DIR, "CamMag")
WORKPRINT_DIR = os.path.join(BASE_DIR, "WorkPrints")

progress_state = {"current": 0, "total": 0, "msg": "Idle", "status": "idle", "eta": 0, "latest_wp": ""}

# Default White for all keys
DEFAULT_STATE = {
    "c1_hex": "#ffffff", "c2_hex": "#ffffff", "c3_hex": "#ffffff"
}

@app.route('/status')
def get_status():
    free_gb = shutil.disk_usage(CAM_MAG_DIR).free / (1024**3)
    try:
        with open(STATE_FILE, 'r') as f: params = json.load(f)
    except: params = DEFAULT_STATE
    return jsonify({**progress_state, "disk_free_gb": free_gb, "params": params})

@app.route('/')
def index(): return render_template('index.html')

@app.route('/preview', methods=['POST'])
def preview():
    data = request.json
    with open(STATE_FILE, 'w') as f: json.dump(data, f, indent=4)
    f1, f3 = int(data['f1']), int(data['f3'])
    t_c = (int(data['probe_frame']) - f1) / (f3 - f1) if f3 != f1 else 0
    t_step = 1.0 / (f3 - f1) if f3 != f1 else 0
    st = interpolator.get_state_at_t(t_c, data)
    actual_t = t_c + (t_step * st['sd'] * (float(data['probe_sub']) - st['ph']))
    ps = interpolator.get_state_at_t(actual_t, data)
    
    job = {**data, 
           "p_start": ",".join(map(str, ps['p'])), "p_end": ",".join(map(str, ps['p'])),
           "r_start": ",".join(map(str, ps['r'])), "r_end": ",".join(map(str, ps['r'])), 
           "c_start": ps['c'].tolist(), "c_end": ps['c'].tolist(), "type": "preview"}
    
    with open("/tmp/vop_job.json", 'w') as f: json.dump(job, f)
    subprocess.run(["python3", ENGINE_PATH, "--job", "/tmp/vop_job.json"])
    return jsonify({"status": "SUCCESS", "timestamp": time.time()})

@app.route('/execute_sequence', methods=['POST'])
def execute():
    global progress_state
    data = request.json
    with open(STATE_FILE, 'w') as f: json.dump(data, f, indent=4)
    f1, f3 = int(data['f1']), int(data['f3'])
    total = (f3 - f1) + 1
    progress_state.update({"current": 0, "total": total, "status": "running", "msg": "Exposing..."})
    
    start_time = time.time()
    for i in range(total):
        if progress_state["status"] == "panic": break
        t_c = i / (total - 1) if total > 1 else 0
        t_step = 1.0 / (total - 1) if total > 1 else 0
        
        if i > 2:
            avg = (time.time() - start_time) / i
            progress_state["eta"] = int(avg * (total - i))

        st = interpolator.get_state_at_t(t_c, data)
        t_s = t_c - (t_step * st['sd'] * st['ph'])
        t_e = t_c + (t_step * st['sd'] * (1.0 - st['ph']))
        s_st, e_st = interpolator.get_state_at_t(t_s, data), interpolator.get_state_at_t(t_e, data)
        
        job = {**data, 
               "p_start": ",".join(map(str, s_st['p'])), "p_end": ",".join(map(str, e_st['p'])),
               "r_start": ",".join(map(str, s_st['r'])), "r_end": ",".join(map(str, e_st['r'])),
               "c_start": s_st['c'].tolist(), "c_end": e_st['c'].tolist(),
               "smear": st['s'], "frame": f1 + i}
               
        with open("/tmp/vop_job.json", 'w') as f: json.dump(job, f)
        subprocess.run(["python3", ENGINE_PATH, "--job", "/tmp/vop_job.json"])
        progress_state["current"] = i + 1

    if progress_state["status"] != "panic":
        progress_state["msg"] = "Workprinting..."
        ts = time.strftime("%Y%m%d_%H%M%S")
        wp_name = f"vop_wp_{ts}.mp4"
        cmd = ["ffmpeg", "-y", "-framerate", str(data.get('fps', 24)), "-pattern_type", "glob", "-i", os.path.join(CAM_MAG_DIR, "*.tif"),
               "-vf", "scale=2048:1536,format=yuv420p", "-c:v", "libx264", "-crf", "23", os.path.join(WORKPRINT_DIR, wp_name)]
        subprocess.run(cmd)
        progress_state.update({"status": "idle", "msg": "COMPLETE", "latest_wp": wp_name, "eta": 0})
    return jsonify({"status": "SUCCESS"})

@app.route('/panic', methods=['POST'])
def panic():
    global progress_state
    progress_state["status"] = "panic"
    subprocess.run(["pkill", "-9", "-f", "engine.py"])
    subprocess.run(["pkill", "-9", "-f", "rpicam-still"])
    return jsonify({"status": "ABORTED"})

@app.route('/nuke_mag', methods=['POST'])
def nuke():
    for f in glob.glob(os.path.join(CAM_MAG_DIR, "*.tif")): os.remove(f)
    return jsonify({"status": "CLEAN"})

@app.route('/download/<path:filename>')
def download(filename): return send_from_directory(WORKPRINT_DIR, filename, as_attachment=True)

if __name__ == "__main__": app.run(host='0.0.0.0', port=5000)