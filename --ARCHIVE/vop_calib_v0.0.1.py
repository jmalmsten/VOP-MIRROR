"""
VOP Module:     vop_calib_v0.0.1.py
Version:        v0.0.1
Description:    HDMI Alignment & Calibration Tool.
                Projects focus grids and 3D bounds for physical alignment.
"""
import os, sys, time, numpy as np
import moderngl, pygame
from pyrr import Matrix44

# Environment Configuration
os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
os.environ["SDL_VIDEO_KMSDRM_FORCE_MODE"] = "1"

# Shaders (Standard VOP Shaders)
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
# A specialized calibration shader that generates a grid programmatically
FRAGMENT_SHADER = """
#version 310 es
precision highp float;
in vec2 v_texcoord;
out vec4 f_color;
uniform int mode; // 0: Grid, 1: Crosshair, 2: Solid White

void main() {
    vec2 uv = v_texcoord;
    if (mode == 0) {
        // Procedural Grid
        float grid = step(0.98, fract(uv.x * 20.0)) + step(0.98, fract(uv.y * 20.0));
        f_color = vec4(vec3(grid), 1.0);
    } else if (mode == 1) {
        // Center Crosshair
        float thickness = 0.002;
        float x = step(0.5 - thickness, uv.x) * step(uv.x, 0.5 + thickness);
        float y = step(0.5 - thickness, uv.y) * step(uv.y, 0.5 + thickness);
        f_color = vec4(vec3(max(x, y)), 1.0);
    } else {
        f_color = vec4(1.0, 1.0, 1.0, 1.0);
    }
}
"""

def run_calibration():
    pygame.init()
    pygame.mouse.set_visible(False)
    screen = pygame.display.set_mode((0,0), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
    WIDTH, HEIGHT = screen.get_size()
    ctx = moderngl.create_context(require=310)

    # Setup Geometry
    vertices = np.array([-1,-1,0,0,0, 1,-1,0,1,0, -1,1,0,0,1, 1,1,0,1,1], dtype='f4')
    prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
    vbo = ctx.buffer(vertices)
    vao = ctx.vertex_array(prog, [(vbo, '3f 2f', 'in_position', 'in_texcoord')], mode=moderngl.TRIANGLE_STRIP)

    mode = 0
    z_dist = 5.0
    running = True

    print("--- CALIBRATION CONTROLS ---")
    print("1: Grid | 2: Crosshair | 3: White | UP/DOWN: Adjust Z-Depth | Q: Quit")

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
        
        # Calculate Projection
        proj = Matrix44.perspective_projection(45.0, WIDTH/HEIGHT, 0.1, 1000.0)
        model = Matrix44.from_translation([0, 0, z_dist])
        
        prog['mvp'].write((proj * model).astype('f4'))
        prog['mode'].value = mode
        vao.render()
        
        pygame.display.flip()
        time.sleep(0.01)

    pygame.quit()

if __name__ == "__main__":
    run_calibration()