"""
VOP Module:     app.py
Version:        v0.4.4-api
Description:    Phase IV - Dual-Key Batch Processor.
                Automated FFMPEG export and Console-style data handling.
"""
from flask import Flask, render_template, request, jsonify
import subprocess, os, json, numpy as np

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.join(BASE_DIR, "engine.py")
JOB_FILE = "/tmp/vop_job.json"
PREVIEW_DIR = os.path.join(BASE_DIR, "Previews")
CAM_MAG_DIR = os.path.join(BASE_DIR, "CamMag")

# Ensure environment is ready
os.makedirs(PREVIEW_DIR, exist_ok=True)

def lerp_vec(v1, v2, t):
    return v1 + (v2 - v1) * t

def generate_preview(fps):
    """Encodes 16-bit linear TIFFs to an 8-bit sRGB MP4."""
    output_path = os.path.join(PREVIEW_DIR, "vop_preview_latest.mp4")
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", os.path.join(CAM_MAG_DIR, "latent_%04d.tif"),
        "-vf", "lutrgb=r=gammaval(2.2):g=gammaval(2.2):b=gammaval(2.2),format=yuv420p",
        "-c:v", "libx264", "-crf", "18",
        output_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, check=True)
        return True
    except subprocess.CalledProcessError:
        return False

@app.route('/')
def index(): 
    return render_template('index.html')

@app.route('/preview', methods=['POST'])
@app.route('/execute_sequence', methods=['POST'])
def handle():
    data = request.json
    is_preview = request.path == '/preview'
    
    f_start = int(data['f_start'])
    f_end = int(data['f_end'])
    total_seq_frames = (f_end - f_start) + 1
    shutter_val = float(data.get('shutter', 0.5)) 
    
    p1 = np.array([float(x) for x in data['p_start'].split(',')])
    p2 = np.array([float(x) for x in data['p_end'].split(',')])
    r1 = np.array([float(x) for x in data['r_start'].split(',')])
    r2 = np.array([float(x) for x in data['r_end'].split(',')])

    def get_frame_job_data(f_idx, is_p=False, p_val=0.0):
        t_center = f_idx / (total_seq_frames - 1) if total_seq_frames > 1 else 0
        if is_p: t_center = p_val
        t_step = 1.0 / (total_seq_frames - 1) if total_seq_frames > 1 else 0
        
        t_s = t_center - (t_step * shutter_val * 0.5)
        t_e = t_center + (t_step * shutter_val * 0.5)

        pos_s, pos_e = lerp_vec(p1, p2, t_s), lerp_vec(p1, p2, t_e)
        rot_s, rot_e = lerp_vec(r1, r2, t_s), lerp_vec(r1, r2, t_e)
        
        job = data.copy()
        job.update({
            "p_start": f"{pos_s[0]},{pos_s[1]},{pos_s[2]}",
            "p_end":   f"{pos_e[0]},{pos_e[1]},{pos_e[2]}",
            "r_start": f"{rot_s[0]},{rot_s[1]},{rot_s[2]}",
            "r_end":   f"{rot_e[0]},{rot_e[1]},{rot_e[2]}",
            "frame": f_start + f_idx,
            "type": "preview" if is_p else "smear"
        })
        return job

    if is_preview:
        p_val = float(data.get('preview_p', 0.5))
        preview_job = get_frame_job_data(0, is_p=True, p_val=p_val)
        preview_job['p_end'], preview_job['r_end'] = preview_job['p_start'], preview_job['r_start']
        with open(JOB_FILE, 'w') as f: json.dump(preview_job, f, indent=4)
        subprocess.run(["python3", ENGINE_PATH, "--job", JOB_FILE])
        return jsonify({"status": "SUCCESS"}), 200

    for i in range(total_seq_frames):
        current_job = get_frame_job_data(i)
        with open(JOB_FILE, 'w') as f: json.dump(current_job, f, indent=4)
        subprocess.run(["python3", ENGINE_PATH, "--job", JOB_FILE])

    # Finalization: Video Render
    video_success = generate_preview(data.get('fps', 24))
    msg = "Sequence & Video Complete" if video_success else "Sequence Complete (Video Failed)"
    return jsonify({"status": "SUCCESS", "message": msg}), 200

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)