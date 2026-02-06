"""
VOP Module:     vop_align_2d_v0.0.1.py
Version:        v0.0.1
Description:    2D Optical Alignment Tool. 
                Projects corner targets and a center focus chart.
"""
import os, sys, subprocess, numpy as np
import moderngl, pygame

# Configuration
DESKTOP_IP = "192.168.2.8"
os.environ["SDL_VIDEODRIVER"] = "kmsdrm"

# --- SHADER: Procedural Focus & Targets ---
FRAGMENT_SHADER = """
#version 300 es
precision highp float;
in vec2 v_texcoord;
out vec4 f_color;

void main() {
    vec2 uv = v_texcoord;
    float color = 0.0;
    
    // 1. High Frequency Center Pattern (Siemens Star style)
    vec2 center_uv = (uv - 0.5) * 2.0;
    float dist = length(center_uv);
    if (dist < 0.3) {
        float angle = atan(center_uv.y, center_uv.x);
        color = step(0.0, sin(angle * 32.0)); // 32 radial spokes
    }

    // 2. Corner Crosshairs (Targets at 10% inset)
    float thickness = 0.001;
    float size = 0.05;
    vec2 inset = vec2(0.1, 0.1);
    
    // Check all 4 corners
    vec2 corners[4] = vec2[](inset, vec2(1.0-inset.x, inset.y), 
                             vec2(inset.x, 1.0-inset.y), 1.0-inset);
    
    for(int i=0; i<4; i++) {
        float x_line = step(corners[i].x - thickness, uv.x) * step(uv.x, corners[i].x + thickness) 
                       * step(corners[i].y - size, uv.y) * step(uv.y, corners[i].y + size);
        float y_line = step(corners[i].y - thickness, uv.y) * step(uv.y, corners[i].y + thickness) 
                       * step(corners[i].x - size, uv.x) * step(uv.x, corners[i].x + size);
        color = max(color, max(x_line, y_line));
    }

    f_color = vec4(vec3(color), 1.0);
}
"""

# ... [Standard Vertex Shader & Stream Logic same as v0.0.7] ...

def start_stream():
    cmd = [
        "rpicam-vid", "-t", "0", "--inline", "--width", "1280", "--height", "720",
        "--framerate", "30", "--codec", "h264", "--gain", "12.0", "--denoise", "cdn_off",
        "--bitrate", "3000000", "--flush", "-o", f"udp://{DESKTOP_IP}:5000?pkt_size=1316"
    ]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def run():
    stream = start_stream()
    pygame.init()
    screen = pygame.display.set_mode((0,0), pygame.OPENGL | pygame.FULLSCREEN)
    ctx = moderngl.create_context(require=300)
    
    # 2D Fullscreen Quad
    vbo = ctx.buffer(np.array([-1,-1,0,0, 1,-1,1,0, -1,1,0,1, 1,1,1,1], 'f4'))
    prog = ctx.program(vertex_shader="""#version 300 es
        in vec2 in_vert; in vec2 in_tex; out vec2 v_texcoord;
        void main() { gl_Position = vec4(in_vert, 0, 1); v_texcoord = in_tex; }""",
        fragment_shader=FRAGMENT_SHADER)
    vao = ctx.vertex_array(prog, [(vbo, '2f 2f', 'in_vert', 'in_tex')], mode=moderngl.TRIANGLE_STRIP)

    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.KEYDOWN and ev.key == pygame.K_q: running = False
        ctx.clear(0,0,0); vao.render(); pygame.display.flip()
    
    stream.terminate(); pygame.quit()

if __name__ == "__main__": run()