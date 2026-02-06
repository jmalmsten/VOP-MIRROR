"""
VOP Module:     vop_setup_align_v0.1.0.py
Version:        v0.0.10
Description:    Hardened KMSDRM & TCP Alignment Utility.
                Forces environment variables and verifies TTY seizure.
"""
import os, sys, time, subprocess, numpy as np
import moderngl, pygame

# --- STATIC CONFIG ---
PI_IP = "192.168.2.3"
DESKTOP_IP = "192.168.2.8"

def prepare_system():
    print("1. [CLEANUP] Clearing camera processes...")
    subprocess.run("sudo killall -q -9 rpicam-vid rpicam-still 2>/dev/null", shell=True)
    
    print("2. [DRM] Seizing HDMI control (Switching to tty7)...")
    # We switch to tty7 to ensure the console isn't using the HDMI plane
    subprocess.run("sudo chvt 7", shell=True)
    time.sleep(0.5)
    
    # Set Environment Variables explicitly for this process
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    os.environ["SDL_VIDEO_KMSDRM_FORCE_MODE"] = "1"
    os.environ["SDL_VIDEO_KMSDRM_DEVICE"] = "/dev/dri/card0"
    if "DISPLAY" in os.environ:
        del os.environ["DISPLAY"]

def start_stream():
    print("3. [STREAM] Starting TCP Server on port 5000...")
    cmd = [
        "sudo", "rpicam-vid", "-t", "0", 
        "--width", "1280", "--height", "720",
        "--framerate", "30", "--codec", "h264", 
        "--gain", "12.0", "--denoise", "cdn_off",
        "--profile", "baseline", "--flush", 
        "--tuning-file", "/usr/share/libcamera/ipa/rpi/pisp/imx477.json",
        "--listen", "-o", "tcp://0.0.0.0:5000"
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    time.sleep(1.0)
    if proc.poll() is not None:
        print(f"CRITICAL: rpicam-vid died: {proc.stderr.read()}")
        sys.exit(1)
    return proc

# --- SHADERS (Optical Alignment) ---
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
    
    print("4. [SDL] Initializing graphics...")
    pygame.init()
    try:
        # We explicitly request 1080p to help KMSDRM find the mode
        pygame.display.set_mode((0,0), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
        ctx = moderngl.create_context(require=300)
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        print("Suggestion: Run with 'sudo -E python3 vop_setup_align_v0.1.0.py'")
        stream_proc.terminate(); pygame.quit(); sys.exit(1)

    vbo = ctx.buffer(np.array([-1,-1,0,0, 1,-1,1,0, -1,1,0,1, 1,1,1,1], 'f4'))
    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    vao = ctx.vertex_array(prog, [(vbo, '2f 2f', 'in_v', 'in_t')], mode=moderngl.TRIANGLE_STRIP)

    print("\n🚀 SYSTEM ONLINE.")
    print("Connect leDesktop ffplay to 192.168.2.3:5000")

    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_q: running = False
        ctx.clear(0,0,0); vao.render(); pygame.display.flip()
        time.sleep(0.01)
    
    stream_proc.terminate(); pygame.quit()
    subprocess.run("sudo chvt 1", shell=True)

if __name__ == "__main__": run()