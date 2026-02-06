"""
VOP Module:     app.py
Version:        v0.3.3-api
Description:    Flask API for Phase III. Handles 3D and Chromatic SMEAR jobs.
"""
from flask import Flask, render_template, request, jsonify
import subprocess, os, json

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.join(BASE_DIR, "engine.py")
JOB_FILE = "/tmp/vop_job.json"

@app.route('/')
def index(): 
    return render_template('index.html')

@app.route('/preview', methods=['POST'])
@app.route('/execute_smear', methods=['POST'])
def handle():
    data = request.json
    data['type'] = 'preview' if request.path == '/preview' else 'smear'
    
    with open(JOB_FILE, 'w') as f: 
        json.dump(data, f, indent=4)
    
    try:
        # Calling the Engine v0.0.24 (Stable Shutter)
        result = subprocess.run(
            ["python3", ENGINE_PATH, "--job", JOB_FILE],
            capture_output=True, text=True
        )
        
        # We look for the "VOP_STATUS: COMPLETE" printed by engine.py
        if "VOP_STATUS: COMPLETE" in result.stdout or data['type'] == 'preview':
            return jsonify({"status": "SUCCESS", "message": "Engine Complete"}), 200
        else:
            return jsonify({"status": "ERROR", "message": result.stderr}), 500
    except Exception as e:
        return jsonify({"status": "ERROR", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)