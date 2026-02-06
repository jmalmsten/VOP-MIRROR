"""
VOP Module:     vop_setup_align_v0.0.1.py
Version:        v0.0.1
Description:    All-in-one Setup & Alignment Utility.
                1. Kills ghost camera/video processes.
                2. Forces HDMI console to release the DRM lock.
                3. Launches high-gain focus stream.
                4. Projects 2D optical alignment targets.
"""
import os, sys, time, subprocess, numpy as np
import moderngl, pygame

# --- CONFIGURATION ---
DESKTOP_IP = "192.168.2.8"
STREAM_PORT = "5000"

def prepare_system():
    """Performs the terminal 'housecleaning' required for KMSDRM."""
    print("🧹 Cleaning up background processes...")
    # Kill any hung camera or python processes
    subprocess.run("sudo killall -9 rpicam-vid rpicam-still python3 2>/dev/null", shell=True)
    
    print("🔑 Seizing HDMI control (switching to tty7)...")
    # Switch TTY to release the console lock on the HDMI port
    subprocess.run("sudo chvt 7", shell=True)
    
    # Set Environment Variables for the current process
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    os.environ["SDL_VIDEO_KMSDRM_FORCE_MODE"] = "1"
    os.environ["SDL_VIDEO_KMSDRM_DEVICE"] = "/dev/dri/card0"
    if "DISPLAY" in os.environ:
        del os.environ["DISPLAY"]

def start_stream():
    """Background high-gain stream for alignment."""
    cmd = [
        "sudo", "rpicam-vid", "-t", "0", "--inline", "--width", "1280", "--height", "720",
        "--framerate", "30", "--codec", "h264", "--gain", "12.0", "--denoise", "cdn_off",
        "--bitrate", "3000000", "--flush", 
        "-o", f"udp://{DESKTOP_IP}:{STREAM_PORT}?pkt_size=1316"
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# --- SHADERS ---
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

    // 2. Corner Crosshairs (Targets)
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

    # Setup 2D Plane
    vbo = ctx.buffer(np.array([-1,-1,0,0, 1,-1,1,0, -1,1,0,1, 1,1,1,1], 'f4'))
    prog = ctx.program(
        vertex_shader="#version 300 es\nin vec2 in_v; in vec2 in_t; out vec2 v_texcoord;\nvoid main(){gl_Position=vec4(in_v,0,1);v_texcoord=in_t;}",
        fragment_shader=FRAGMENT_SHADER)
    vao = ctx.vertex_array(prog, [(vbo, '2f 2f', 'in_v', 'in_t')], mode=moderngl.TRIANGLE_STRIP)

    print("\n✅ SETUP COMPLETE. RIG IS LIVE.")
    print("1. Monitor: Center focus chart & corner targets visible.")
    print("2. Desktop: Run ffplay command to align.")
    print("3. Press 'Q' on the Pi keyboard to close and return to terminal.")

    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_q: running = False
        ctx.clear(0,0,0); vao.render(); pygame.display.flip()
    
    print("🧹 Cleaning up before exit...")
    stream_proc.terminate()
    pygame.quit()
    # Return to tty1 (the default console)
    subprocess.run("sudo chvt 1", shell=True)

if __name__ == "__main__":
    run()