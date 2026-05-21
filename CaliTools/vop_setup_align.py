"""
VOP Module:     vop_setup_align_v0.0.15.py
Version:        v0.0.15
Description:    Low-latency alignment. Uses all-intra frames for zero lag.
"""

#
###########################################################################
#
#                                   VOP
#                       Copyright (C) 2025  jmalmsten
#
#     This program is free software: you can redistribute it and/or modify 
#     it under the terms of the GNU Affero General Public License as 
#     published by the Free Software Foundation, either version 3 of the 
#     License, or (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful, but 
#     WITHOUT ANY WARRANTY; without even the implied warranty of 
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU 
#     Affero General Public License for more details.
#
#     You should have received a copy of the GNU Affero General Public 
#     License along with this program.  If not, see 
#     <http://www.gnu.org/licenses/>.
#
#     Source code for this application can be found at 
#     https://codeberg.org/jmalmsten-com/VOP
#
###########################################################################


import os, sys, time, subprocess, numpy as np
import moderngl, pygame
import signal

# ---------------------------------------------------------
# CLEAN SHUTDOWN HANDLING
# ---------------------------------------------------------
# Module-level flag the render loop polls each iteration. We use a 
# flag rather than calling sys.exit() inside the signal handler 
# because pygame + moderngl + KMSDRM all need orderly teardown - 
# slamming exit() mid-frame can leave KMSDRM locked and force a 
# reboot to recover (which is exactly the symptom this fixes).
_shutdown_requested = False

def _handle_shutdown_signal(signum, frame):
    """
    Signal handler for SIGTERM (sent by systemd, sudo reboot, or 
    `kill <pid>` from SSH) and SIGINT (Ctrl+C). Just flips a flag - 
    the main loop checks it each iteration and exits cleanly.
    
    This is the same pattern engine.py uses for the main daemon, 
    kept consistent so both processes have the same shutdown 
    semantics: receive signal -> release KMSDRM -> exit.
    """
    global _shutdown_requested
    print(f"\nReceived signal {signum} - shutting down cleanly...")
    _shutdown_requested = True

# Register the handler for both SIGTERM (the standard 'please quit' 
# signal used by systemd and reboot) and SIGINT (Ctrl+C). The 
# default for both is to kill the process instantly, which doesn't 
# give pygame.quit() a chance to release the KMSDRM lock.
signal.signal(signal.SIGTERM, _handle_shutdown_signal)
signal.signal(signal.SIGINT,  _handle_shutdown_signal)

# --- STATIC CONFIG ---
DESKTOP_IP = "192.168.2.8"
PORT = "5555"



def prepare_system():
    subprocess.run("sudo killall -q -9 rpicam-vid rpicam-still 2>/dev/null", shell=True)
    subprocess.run("sudo chvt 7", shell=True)
    os.environ.pop("XDG_RUNTIME_DIR", None)
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    os.environ["SDL_VIDEO_KMSDRM_DEVICE"] = "/dev/dri/card0"
    if "DISPLAY" in os.environ: del os.environ["DISPLAY"]

def start_stream():
    print(f"3. Connecting to Desktop at {DESKTOP_IP}:{PORT}...")
    # 2028x1520 picks the IMX477's "2028x1520 [40.01 fps - (0, 0)/4056x3040 crop]"
    # sensor mode. The crop region of (0,0)/4056x3040 means it's the FULL sensor 
    # 2x2-binned down - every photosite is contributing, no hidden window. 
    # That's critical for alignment: a smaller mode like 1280x720 puts the 
    # sensor into a cropped readout (typically 2028x1080's (0,440)/4056x2160 
    # window, then software-scaled), so the operator would be aligning 
    # against a frame that doesn't match what real captures will see.
    # 
    # 30 fps was chosen rather than the mode's 40 fps max so the H.264 
    # encoder has comfortable headroom on the Pi 4 - alignment doesn't 
    # need maximum framerate, just smoothness for the human eye.
    # 
    # --intra 1: Every frame is a keyframe (Zero latency seeking)
    # --inline: Keeps headers in every packet
    cmd = [
        "sudo", "rpicam-vid", "-t", "0", "--inline", 
        "--width", "2028", "--height", "1520",
        "--framerate", "30", "--codec", "h264", 
        "--profile", "baseline", "--intra", "1", "--inline",
        "-o", f"tcp://{DESKTOP_IP}:{PORT}"
    ]
    return subprocess.Popen(cmd)

# --- SHADERS (Targets & Focus) ---
VERTEX_SHADER = """
#version 300 es
in vec2 in_v; in vec2 in_t; out vec2 v_tex;
void main() { gl_Position = vec4(in_v, 0.0, 1.0); v_tex = in_t; }
"""
FRAGMENT_SHADER = """
#version 300 es
precision highp float;
in vec2 v_tex; out vec4 f_col;
void main() {
    vec2 uv = v_tex; float c = 0.0;
    vec2 c_uv = (uv - 0.5) * 2.0; float d = length(c_uv);
    if (d < 0.35) {
        float a = atan(c_uv.y, c_uv.x);
        c = step(0.0, sin(a * 64.0)) * smoothstep(0.01, 0.04, d);
    }
    float t = 0.0015; float l = 0.04; vec2 i = vec2(0.1); 
    bool h = (abs(uv.x-i.x)<t && abs(uv.y-i.y)<l) || (abs(uv.x-(1.0-i.x))<t && abs(uv.y-i.y)<l) ||
             (abs(uv.x-i.x)<t && abs(uv.y-(1.0-i.y))<l) || (abs(uv.x-(1.0-i.x))<t && abs(uv.y-(1.0-i.y))<l);
    bool v = (abs(uv.y-i.y)<t && abs(uv.x-i.x)<l) || (abs(uv.y-(1.0-i.y))<t && abs(uv.x-i.x)<l) ||
             (abs(uv.y-i.y)<t && abs(uv.x-(1.0-i.x))<l) || (abs(uv.y-(1.0-i.y))<t && abs(uv.x-(1.0-i.x))<l);
    if (h || v) c = 1.0;
    f_col = vec4(vec3(c), 1.0);
}
"""

def run():
    prepare_system()
    stream_proc = start_stream()
    pygame.init()
    
    # ---------------------------------------------------------
    # DISPLAY RESOLUTION DISCOVERY
    # ---------------------------------------------------------
    # Same EDID-via-pygame handshake the main engine uses. Pulls the 
    # connected panel's native resolution from KMS so the alignment 
    # targets render at the actual corner pixels - not a fictional 
    # 1920x1080 grid scaled by the GPU into the real frame.
    #
    # This matters specifically for alignment because the corner 
    # crosshairs and center spoke pattern only land correctly when 
    # rendered at native resolution. Even a small scaler-induced 
    # offset would make the camera-to-screen alignment slightly off, 
    # which defeats the whole point of this tool.
    #
    # Note: this query is done BEFORE the set_mode() try block below, 
    # not nested inside it - so the except clauses match cleanly and 
    # the rest of run() stays at one indentation level.
    try:
        sizes = pygame.display.get_desktop_sizes()
        SCREEN_W, SCREEN_H = sizes[0] if sizes else (1920, 1080)
    except (AttributeError, pygame.error):
        SCREEN_W, SCREEN_H = 1920, 1080
    print(f"Alignment tool: using {SCREEN_W}x{SCREEN_H} from EDID")
    
    # Now the original set_mode try block, unchanged except for 
    # using SCREEN_W/SCREEN_H instead of hardcoded 1920/1080.
    try:
        pygame.display.set_mode((SCREEN_W, SCREEN_H), pygame.OPENGL | pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
        ctx = moderngl.create_context(require=300)
    except Exception as e:
        print(f"SDL Error: {e}"); stream_proc.terminate(); pygame.quit(); sys.exit(1)

    vbo = ctx.buffer(np.array([-1,-1,0,0, 1,-1,1,0, -1,1,0,1, 1,1,1,1], 'f4'))
    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    vao = ctx.vertex_array(prog, [(vbo, '2f 2f', 'in_v', 'in_t')], mode=moderngl.TRIANGLE_STRIP)

    print("\n✅ ALIGNMENT TOOL LIVE.")
    running = True
    # Loop exits on either: 'q' on the physical keyboard (sets running=False) 
    # OR a signal from outside (sets _shutdown_requested via the handler).
    # Both paths fall through to the same cleanup below.
    while running and not _shutdown_requested:
        for ev in pygame.event.get():
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_q: running = False
        ctx.clear(0,0,0); vao.render(); pygame.display.flip()
        time.sleep(0.01)
    
    stream_proc.terminate(); pygame.quit(); subprocess.run("sudo chvt 1", shell=True)

if __name__ == "__main__": run()