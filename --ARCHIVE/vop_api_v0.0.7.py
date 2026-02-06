"""
VOP Module:     vop_api_v0.0.7.py
Version:        v0.0.7
Description:    Phase III - Merged 3D & Chromatic API.
                Points to Engine v0.0.18 and UI v0.0.4.
"""
from flask import Flask, render_template, request, jsonify
import subprocess, os, json

app = Flask(__name__)

# --- DYNAMIC PATH RESOLUTION ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Updated to point to the new Merged Engine
ENGINE_PATH = os.path.join(BASE_DIR, "smear_3D_v0.0.18.py")
JOB_FILE = os.path.join(BASE_DIR, "current_job.json")

@app.route('/')
def index(): 
    # Points to the latest UI version we just built
    return render_template('vop_ui_v0.0.4.html')

@app.route('/preview', methods=['POST'])
@app.route('/execute_smear', methods=['POST'])
def handle():
    data = request.json
    is_preview = request.path == '/preview'
    data['type'] = 'preview' if is_preview else 'smear'
    
    # Save the incoming JSON (now including c_start and c_end arrays)
    with open(JOB_FILE, 'w') as f: 
        json.dump(data, f, indent=4)
    
    try:
        # Trigger the 3D Engine v0.0.18
        result = subprocess.run(
            ["python3", ENGINE_PATH, "--job", JOB_FILE],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            return jsonify({"status": "SUCCESS", "message": "Latent Written to CamMag"}), 200
        else:
            return jsonify({"status": "ERROR", "message": result.stderr}), 500
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)