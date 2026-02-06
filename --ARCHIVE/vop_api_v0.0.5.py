"""
VOP Module:     vop_api_v0.0.5.py
Version:        v0.0.5
Description:    Phase II/III - Synchronous Execution API.
"""
from flask import Flask, render_template, request, jsonify
import subprocess, os, json

app = Flask(__name__)
ENGINE_PATH = os.path.expanduser("~/vop/smear_3D_v0.0.16.py")
JOB_FILE = os.path.expanduser("~/vop/current_job.json")

@app.route('/')
def index(): return render_template('vop_ui_v0.0.3.html')

@app.route('/preview', methods=['POST'])
@app.route('/execute_smear', methods=['POST'])
def handle():
    data = request.json
    is_preview = request.path == '/preview'
    data['type'] = 'preview' if is_preview else 'smear'
    with open(JOB_FILE, 'w') as f: json.dump(data, f, indent=4)
    
    try:
        # We use .check_output to wait for the engine and read its print statements
        result = subprocess.check_output(["python3", ENGINE_PATH, "--job", JOB_FILE], stderr=subprocess.STDOUT)
        output_str = result.decode('utf-8')
        
        if "VOP_STATUS: COMPLETE" in output_str or is_preview:
            return jsonify({"status": "SUCCESS", "message": "Latent Written to CamMag"}), 200
        else:
            return jsonify({"status": "ERROR", "message": "Engine failed to finalize"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)