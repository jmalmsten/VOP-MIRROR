"""
VOP Module:     vop_calib_v0.0.5.py
Version:        v0.0.5
Description:    Hardened Alignment Utility. 
                Projects calibration assets to HDMI and starts a high-gain
                low-latency stream to leDesktop.
"""
import os, sys, time, subprocess, numpy as np
import moderngl, pygame
from pyrr import Matrix44

# --- SETTINGS ---
# Ensure this matches your desktop IP
DESKTOP_IP = "192.168.2.8" 
STREAM_PORT = "5000"

# Forces hardware plane access for Pi 5
os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
os.environ["SDL_VIDEO_KMSDRM_FORCE_MODE"] = "1"

# --- SHADERS ---
VERTEX_SHADER = """
#version 310 es
precision highp float;
in vec3 in_position;
in vec2 in_texcoord;
out vec2 v_texcoord;
uniform mat4 mvp;
void main() {
    gl_Position = mvp * vec4(in_position, 1.0);
    v_texcoord = in_texcoord;
}
"""

FRAGMENT_SHADER = """
#version 310 es
precision highp float;
in vec2 v_texcoord;
out vec4 f_color;
uniform int mode; 

void main() {
    vec2 uv = v_texcoord;
    if (mode == 0) {
        // Focus Grid
        float grid = step(0.99, fract(uv.x * 40.0)) + step(0.99, fract(uv.y * 40.0));
        f_color = vec4(vec3(grid), 1.0);
    } else if (mode == 1) {
        // Crosshair
        float x = step(0.499, uv.x) * step(uv.x, 0.501);
        float y = step(0.499, uv.y) * step(uv.y, 0.501);
        f_color = vec4(vec3(max(x, y)), 1.0);
    } else {
        // Flat White
        f_color = vec4(1.0, 1.0, 1.0, 1.0);
    }
}
"""

def start_stream():
    """Background high-gain stream for alignment."""
    cmd = [
        "rpicam-vid", "-t", "0", "--inline", "--width", "1280", "--height", "720",
        "--framerate", "30", "--codec", "h264", "--gain", "12.0", "--denoise", "cdn_off",
        "--bitrate", "3000000", "--flush", 
        "-o", f"udp://{DESKTOP_IP}:{STREAM_PORT}?pkt_size=1316"
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def run_calibration():
    # 1. Clear any existing DRM locks just in case
    stream_proc = start_stream()
    print(f"DEBUG: Streaming focus feed to {DESKTOP_IP}:{STREAM_PORT}")

    # 2. Hardened Init
    pygame.init()
    
    # Remove DISPLAY to prevent SDL from trying to use X11 via SSH
    if "DISPLAY" in os.environ:
        del os.environ["DISPLAY"]

    try:
        # Establish DRM plane
        screen = pygame.display.set_mode((0,0), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
        WIDTH, HEIGHT = screen.get_size()
        ctx = moderngl.create_context(require=310)
    except Exception as e:
        print(f"CRITICAL: Init failed: {e}")
        stream_proc.terminate()
        pygame.quit()
        sys.exit(1)

    # 3. Geometry Setup
    vertices = np.array([-1,-1,0,0,0, 1,-1,0,1,0, -1,1,0,0,1, 1,1,0,1,1], dtype='f4')
    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    vbo = ctx.buffer(vertices)
    vao = ctx.vertex_array(prog, [(vbo, '3f 2f', 'in_position', 'in_texcoord')], mode=moderngl.TRIANGLE_STRIP)

    mode = 0
    z_dist = 5.0
    running = True

    print("\n--- CALIBRATION ENGINE ONLINE ---")
    print("1: Grid | 2: Crosshair | 3: White | UP/DOWN: Z-Distance | Q: Quit")

    while running:
        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_1: mode = 0
                if event.key == pygame.K_2: mode = 1
                if event.key == pygame.K_3: mode = 2
                if event.key == pygame.K_UP: z_dist -= 0.1
                if event.key == pygame.K_DOWN: z_dist += 0.1
                if event.key == pygame.K_q: running = False

        ctx.clear(0, 0, 0)
        
        # 45 degree FOV proxy matching the smear engine
        proj = Matrix44.perspective_projection(45.0, WIDTH/HEIGHT, 0.1, 1000.0)
        model = Matrix44.from_translation([0, 0, z_dist])
        
        prog['mvp'].write((proj * model).astype('f4'))
        prog['mode'].value = mode
        vao.render()
        
        pygame.display.flip()
        time.sleep(0.01)

    # Cleanup
    print("DEBUG: Terminating stream and HDMI context...")
    stream_proc.terminate()
    pygame.quit()

if __name__ == "__main__":
    run_calibration()