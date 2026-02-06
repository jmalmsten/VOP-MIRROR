"""
VOP Module:         vop_api_v0.0.3.py
Version:            v0.0.3
Description:        Flask API for Phase II (Latent Imaging)
                    - Supports 'preview' and 'smear' modes.
                    - Bridges WebUI to Engine v0.0.1
"""

from flask import Flask, render_template, request, jsonify
import subprocess
import os
import json

app = Flask(__name__)

# Clinical path resolution
ENGINE_PATH = os.path.expanduser("~/vop/smear_3D_v0.0.12.py")
JOB_FILE = os.path.expanduser("~/vop/current_job.json")

@app.route('/')
def index():
    return render_template('vop_ui_v0.0.2.html')

@app.route('/preview', methods=['POST'])
def preview():
    """ Triggers the engine in non-capture mode for positioning. """
    data = request.json
    data['type'] = 'preview' # Tell the engine to just display, not capture

    with open(JOB_FILE, 'w') as f:
        json.dump(data, f, indent=4)
    
    try:
        # We use .wait() for preview so the API stays 'busy'
        # while the Pi monitor shows the frame.
        subprocess.run(["python3", ENGINE_PATH, "--job", JOB_FILE])
        return jsonify({"status": "success", "message": "Preview displayed"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/execute_smear', methods=['POST'])
def execute_smear():
    """ Triggers the engine for a full exposure and additive composite. """
    data = request.json
    data['type'] = 'smear' #  Tell the engine to perform the capture

    with open(JOB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

    try:
        # Popen allows the UI to return 'Triggered' immediately
        # while the 15 second smear runs in the background.
        subprocess.Popen(["python3", ENGINE_PATH, "--job", JOB_FILE ])
        return jsonify({"status": "success", "message": "Optical Smear Triggered"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)