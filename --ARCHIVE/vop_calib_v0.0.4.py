"""
VOP Module:     vop_calib_v0.0.4.py
Version:        v0.0.4
Description:    Phase III - Alignment Utility with Hardened KMS/DRM Init.
"""
import os, sys, time, subprocess, numpy as np
import moderngl, pygame
from pyrr import Matrix44

# --- SETTINGS ---
DESKTOP_IP = "192.168.2.8" 
STREAM_PORT = "5000"

# Forces the Pi 5 to use the hardware plane directly
os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
os.environ["SDL_VIDEO_KMSDRM_FORCE_MODE"] = "1"
# Prevents X11 interference if you're in a desktop session
if "DISPLAY" in os.environ:
    del os.environ["DISPLAY"]

# ... [SHADERS SAME AS v0.0.3] ...

def start_stream():
    cmd = [
        "rpicam-vid", "-t", "0", "--inline", "--width", "1280", "--height", "720",
        "--framerate", "30", "--codec", "h264", "--gain", "12.0", "--denoise", "cdn_off",
        "--bitrate", "3000000", "--flush", 
        "-o", f"udp://{DESKTOP_IP}:{STREAM_PORT}?pkt_size=1316"
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def run_calibration():
    stream_proc = start_stream()
    print(f"DEBUG: Streaming focus feed to {DESKTOP_IP}:{STREAM_PORT}")

    # HARDENED INIT
    pygame.display.init() # Initialize the display module specifically first
    
    try:
        # On Pi 5, we often need to be explicit about the resolution or let it auto-detect
        # If (0,0) fails, we might need to specify (1920, 1080)
        screen = pygame.display.set_mode((0,0), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
        pygame.mouse.set_visible(False)
        
        WIDTH, HEIGHT = screen.get_size()
        ctx = moderngl.create_context(require=310)
    except Exception as e:
        print(f"CRITICAL: Init failed: {e}")
        print("TIP: Try running with 'sudo' or check if another process is using the HDMI.")
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
        proj = Matrix44.perspective_projection(45.0, WIDTH/HEIGHT, 0.1, 1000.0)
        model = Matrix44.from_translation([0, 0, z_dist])
        prog['mvp'].write((proj * model).astype('f4'))
        prog['mode'].value = mode
        vao.render()
        pygame.display.flip()
        time.sleep(0.01)

    stream_proc.terminate()
    pygame.quit()

if __name__ == "__main__":
    run_calibration()