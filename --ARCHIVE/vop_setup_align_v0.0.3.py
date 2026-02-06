"""
VOP Module:     vop_setup_align_v0.0.3.py
Version:        v0.0.3
Description:    All-in-one Setup & Alignment Utility.
                Corrected shader syntax for GLSL compiler.
"""
import os, sys, time, subprocess, numpy as np
import moderngl, pygame

# --- CONFIGURATION ---
DESKTOP_IP = "192.168.2.8"
STREAM_PORT = "5000"

def prepare_system():
    """Surgically cleans background tasks and grabs HDMI plane."""
    print("🧹 Cleaning up background processes...")
    my_pid = os.getpid()
    subprocess.run("sudo killall -9 rpicam-vid rpicam-still 2>/dev/null", shell=True)
    
    # Surgical kill of other python processes
    cmd = f"ps -ef | grep python | grep -v grep | grep -v {my_pid} | awk '{{print $2}}' | xargs -r sudo kill -9"
    subprocess.run(cmd, shell=True)
    
    print("🔑 Seizing HDMI control (switching to tty7)...")
    subprocess.run("sudo chvt 7", shell=True)
    
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    os.environ["SDL_VIDEO_KMSDRM_FORCE_MODE"] = "1"
    os.environ["SDL_VIDEO_KMSDRM_DEVICE"] = "/dev/dri/card0"
    if "DISPLAY" in os.environ:
        del os.environ["DISPLAY"]

def start_stream():
    """Background high-gain stream optimized for zero latency."""
    cmd = [
        "sudo", "rpicam-vid", "-t", "0", "--inline", "--width", "1280", "--height", "720",
        "--framerate", "30", "--codec", "h264", "--gain", "12.0", "--denoise", "cdn_off",
        "--bitrate", "3000000", "--profile", "baseline", "--level", "4", "--g", "10",
        "--flush", "-o", f"udp://{DESKTOP_IP}:{STREAM_PORT}?pkt_size=1316"
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# --- SHADERS ---
VERTEX_SHADER = """
#version 300 es
in vec2 in_v;
in vec2 in_t;
out vec2 v_texcoord;
void main() {
    gl_Position = vec4(in_v, 0.0, 1.0);
    v_texcoord = in_t;
}
"""

FRAGMENT_SHADER = """
#version 300 es
precision highp float;
in vec2 v_texcoord;
out vec4 f_color;

void main() {
    vec2 uv = v_texcoord;
    float color = 0.0;
    
    // 1. Siemens Star (Focus Pattern)
    vec2 center_uv = (uv - 0.5) * 2.0;
    float dist = length(center_uv);
    if (dist < 0.35) {
        float angle = atan(center_uv.y, center_uv.x);
        color = step(0.0, sin(angle * 64.0)); 
        color *= smoothstep(0.01, 0.04, dist);
    }

    // 2. Corner Crosshairs (Targets at 10% Inset)
    float thick = 0.0015;
    float len = 0.04;
    vec2 i = vec2(0.1, 0.1); 
    
    bool h = (abs(uv.x-i.x)<thick && abs(uv.y-i.y)<len) || (abs(uv.x-(1.0-i.x))<thick && abs(uv.y-i.y)<len) ||
             (abs(uv.x-i.x)<thick && abs(uv.y-(1.0-i.y))<len) || (abs(uv.x-(1.0-i.x))<thick && abs(uv.y-(1.0-i.y))<len);
    bool v = (abs(uv.y-i.y)<thick && abs(uv.x-i.x)<len) || (abs(uv.y-(1.0-i.y))<thick && abs(uv.x-i.x)<len) ||
             (abs(uv.y-i.y)<thick && abs(uv.x-(1.0-i.x))<len) || (abs(uv.y-(1.0-i.y))<thick && abs(uv.x-(1.0-i.x))<len);
    
    if (h || v) color = 1.0;
    f_color = vec4(vec3(color), 1.0);
}
"""

def run():
    prepare_system()
    stream_proc = start_stream()
    
    pygame.init()
    try:
        screen = pygame.display.set_mode((0,0), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
        ctx = moderngl.create_context(require=300)
    except Exception as e:
        print(f"CRITICAL: DRM Seizure Failed: {e}")
        stream_proc.terminate(); pygame.quit(); sys.exit(1)

    vbo = ctx.buffer(np.array([-1,-1,0,0, 1,-1,1,0, -1,1,0,1, 1,1,1,1], 'f4'))
    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    vao = ctx.vertex_array(prog, [(vbo, '2f 2f', 'in_v', 'in_t')], mode=moderngl.TRIANGLE_STRIP)

    print("\n✅ SETUP COMPLETE. RIG IS LIVE.")
    print("Alignment targets projected. Camera streaming to desktop.")
    print("Press 'Q' on the PI KEYBOARD to exit.")

    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_q: running = False
        ctx.clear(0,0,0); vao.render(); pygame.display.flip()
        time.sleep(0.01)
    
    print("🧹 Cleaning up...")
    stream_proc.terminate()
    pygame.quit()
    subprocess.run("sudo chvt 1", shell=True)

if __name__ == "__main__":
    run()