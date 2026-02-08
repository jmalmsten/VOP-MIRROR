"""
VOP Module:     workprint.py
Version:        v0.0.1
"""
import subprocess, os, time

def generate(cam_mag_dir, workprint_dir, fps):
    ts = time.strftime("%Y%m%d_%H%M%S")
    fname = f"vop_wp_{ts}.mp4"
    out_path = os.path.join(workprint_dir, fname)
    
    cmd = [
        "ffmpeg", "-y", "-framerate", str(fps),
        "-pattern_type", "glob", "-i", os.path.join(cam_mag_dir, "*.tif"),
        "-vf", "scale=2048:1536,format=yuv420p",
        "-c:v", "libx264", "-crf", "23", "-preset", "veryfast", out_path
    ]
    subprocess.run(cmd)
    return fname