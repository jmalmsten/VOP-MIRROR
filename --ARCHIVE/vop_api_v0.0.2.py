"""
VOP Module:         vop_api_v0.0.2.py
version:            v0.0.2
VOP Version:        v0.3.1
Project Phase:      Phase I: Single Frame Smear
Description:        Receives WebUI data and translates it into a JSON job file for the engine.
"""

from flask import Flask, render_template, request, jsonify
import subprocess
import os
import json

app = Flask(__name__)

# Path Resolution
ENGINE_PATH = os.path.expanduser("~/vop/smear_3D_v0.0.11.py")
JOB_FILE = os.path.expanduser("~/vop/current_job.json")

@app.route('/')
def index():
    return render_template('vop_ui.html')

@app.route('/execute_smear', methods=['POST'])
def execute_smear():
    data = request.json

    # Pack the WebUI data into the JSON Job format
    job_data = {
        "image":            data.get("image"),
        "smear_duration":   float(data.get("smear", 5.0)),
        "pos_start":        data.get("pos_start"),
        "pos_end":          data.get("pos_end"),
        "rot_start":        data.get("rot_start"),
        "rot_end":          data.get("rot_end"),
        "scale_start":      float(data.get("scale_start", 1.0)),
        "scale_end":        float(data.get("scale_end", 1.0)),
        "fov":              float(data.get("fov", 45.0)),
        "gain":             float(data.get("gain", 1.0))
    }

    # Write the job file
    try:
        with open(JOB_FILE, 'w') as f:
            json.dump(job_data, f, indent=4)
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to write job file: {e}"}), 500

    try:
        # Trigger engine v0.0.11 as a background process passing the job file path
        subprocess.Popen(["python3", ENGINE_PATH, "--job", JOB_FILE])
        return jsonify({"status": "success", "message": "Smear Engine Triggered"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)