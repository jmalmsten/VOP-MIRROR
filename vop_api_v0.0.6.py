"""
VOP Module:     vop_api_v0.0.6.py
Version:        v0.0.6
Description:    Phase III - Portable Synchronous API.
                Dynamically resolves paths for public repo compatibility.
"""
from flask import Flask, render_template, request, jsonify
import subprocess, os, json

app = Flask(__name__)

# --- DYNAMIC PATH RESOLUTION ---
# Finds the directory where this script actually lives
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_PATH = os.path.join(BASE_DIR, "smear_3D_v0.0.17.py")
JOB_FILE = os.path.join(BASE_DIR, "current_job.json")

@app.route('/')
def index(): 
    # Points to the latest UI version
    return render_template('vop_ui_v0.0.3.html')

@app.route('/preview', methods=['POST'])
@app.route('/execute_smear', methods=['POST'])
def handle():
    data = request.json
    is_preview = request.path == '/preview'
    data['type'] = 'preview' if is_preview else 'smear'
    
    with open(JOB_FILE, 'w') as f: 
        json.dump(data, f, indent=4)
    
    try:
        # We use run() with capture_output for better error handling in v0.0.6
        result = subprocess.run(
            ["python3", ENGINE_PATH, "--job", JOB_FILE],
            capture_output=True,
            text=True
        )
        
        output_str = result.stdout
        
        if "VOP_STATUS: COMPLETE" in output_str or is_preview:
            return jsonify({"status": "SUCCESS", "message": "Latent Written to CamMag"}), 200
        else:
            # Capture stderr if the engine crashed
            error_detail = result.stderr if result.stderr else "Unknown Engine Error"
            return jsonify({"status": "ERROR", "message": error_detail}), 500
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)