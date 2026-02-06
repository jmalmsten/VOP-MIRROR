"""
VOP Module:     vop_calib_v0.0.2.py
Version:        v0.0.2
Description:    Integrated HDMI Alignment & Low-Latency Streamer.
                - Projects 3D calibration assets to HDMI.
                - Launches rpicam-vid H.264 UDP stream in background.
                - Auto-cleans processes on exit.
"""
import os, sys, time, subprocess, numpy as np
import moderngl, pygame
from pyrr import Matrix44

# --- CONFIGURATION ---
os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
os.environ["SDL_VIDEO_KMSDRM_FORCE_MODE"] = "1"

# Replace with your leDesktop IP
DESKTOP_IP = "192.168.2.8" 
STREAM_PORT = "5000"

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
        // High-Contrast Focus Grid
        float grid = step(0.99, fract(uv.x * 40.0)) + step(0.99, fract(uv.y * 40.0));
        f_color = vec4(vec3(grid), 1.0);
    } else if (mode == 1) {
        // Center-Alignment Crosshair
        float x = step(0.499, uv.x) * step(uv.x, 0.501);
        float y = step(0.499, uv.y) * step(uv.y, 0.501);
        f_color = vec4(vec3(max(x, y)), 1.0);
    } else {
        // Solid White (for flat-field/shading check)
        f_color = vec4(1.0, 1.0, 1.0, 1.0);
    }
}
"""

def start_stream():
    """Launches the high-gain, low-latency background stream."""
    cmd = [
        "rpicam-vid", "-t", "0", "--inline", "--width", "1280", "--height", "720",
        "--framerate", "30", "--codec", "h264", "--gain", "12", "--denoise", "cdn_off",
        "--bitrate", "3000000", "--flush", 
        "-o", f"udp://{DESKTOP_IP}:{STREAM_PORT}?pkt_size=1316"
    ]
    print(f"DEBUG: Starting Stream to {DESKTOP_IP}...")
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def run_calibration():
    # Start the "Night Vision" feed
    stream_proc = start_stream()

    pygame.init()
    pygame.mouse.set_visible(False)
    
    try:
        screen = pygame.display.set_mode((0,0), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
        WIDTH, HEIGHT = screen.get_size()
        ctx = moderngl.create_context(require=310)
    except Exception as e:
        print(f"CRITICAL: Failed to lock HDMI for calibration: {e}")
        stream_proc.terminate()
        sys.exit(1)

    # Setup Assets
    vertices = np.array([-1,-1,0,0,0, 1,-1,0,1,0, -1,1,0,0,1, 1,1,0,1,1], dtype='f4')
    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    vbo = ctx.buffer(vertices)
    vao = ctx.vertex_array(prog, [(vbo, '3f 2f', 'in_position', 'in_texcoord')], mode=moderngl.TRIANGLE_STRIP)

    mode = 0
    z_dist = 5.0
    running = True

    print("\n--- CALIBRATION ACTIVE ---")
    print("KEYS: 1: Grid | 2: Crosshair | 3: Flat White")
    print("      UP/DOWN: Z-Depth | Q: Exit & Stop Stream")

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
        proj = Matrix44.perspective_projection(45.0, WIDTH/HEIGHT, 0.1, 1000.0)
        model = Matrix44.from_translation([0, 0, z_dist])
        
        prog['mvp'].write((proj * model).astype('f4'))
        prog['mode'].value = mode
        vao.render()
        pygame.display.flip()
        time.sleep(0.01)

    # Cleanup
    print("DEBUG: Shutting down stream and HDMI...")
    stream_proc.terminate()
    pygame.quit()

if __name__ == "__main__":
    run_calibration()