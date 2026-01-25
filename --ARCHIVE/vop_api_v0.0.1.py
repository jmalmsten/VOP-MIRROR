"""
VOP Module:     vop_api_v0.0.1.py
version:        v0.0.1
Description:    KISS Flask API for Red/Black testing
                - Dynamically resolves user home directory
"""

from flask import Flask, render_template, request, jsonify
import subprocess
import os

app = Flask(__name__)

# Dynamically resolve path to ensure portability across users
ENGINE = os.path.expanduser("~/vop/kiss_engine_v0.0.1.py")

@app.route('/')
def index():
    return render_template('kiss.html')

@app.route('/set_color', methods=['POST'])
def set_color():
    color = request.json.get('color', '0,0,0')

    # Run the engine
    try:
        subprocess.run(["python3", ENGINE, "--color", color])
        return jsonify({"status:": "ok"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
    