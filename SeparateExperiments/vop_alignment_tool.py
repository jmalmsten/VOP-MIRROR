"""
VOP Module:     vop_alignment_tool.py
Version:        v0.0.3
Description:    KMS-based Alignment Tool with Feedback Suppression.
                Gain reduced to 4. Uses a green border to break the loop.
                Controls: [SPACE] Toggle X | [Q] Exit
"""

import os
import subprocess
import numpy as np
import pygame

# Hardware Constants
WIDTH, HEIGHT = 1920, 1080
CAM_W, CAM_H = 1280, 720 

def run_alignment():
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    os.environ["DISPLAY"] = ":0"
    
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
    pygame.mouse.set_visible(False)
    
    # Setup camera pipe (Gain reduced to 4 for clinical cleanliness)
    cmd = [
        "rpicam-vid",
        "-t", "0",
        "--width", str(CAM_W),
        "--height", str(CAM_H),
        "--framerate", "30",
        "--shutter", "30000",
        "--gain", "4",
        "--codec", "yuv420",
        "--nopreview",
        "-o", "-"
    ]
    
    pipe = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=10**8)
    frame_size = CAM_W * CAM_H * 3 // 2

    print("Alignment Tool v0.0.3 Running...")
    print("Gain: 4.0 | Suppression: ON")

    show_overlay = True
    running = True
    try:
        while running:
            raw_data = pipe.stdout.read(frame_size)
            if len(raw_data) != frame_size:
                break
            
            # 1. Draw a Green Background (The Target)
            # This breaks the feedback loop by giving the camera something 
            # static and bright to look at at the edges.
            screen.fill((0, 40, 0)) # Dim green to prevent blooming
            
            # 2. Process Camera Frame (B&W for high contrast)
            y_plane = np.frombuffer(raw_data[:CAM_W*CAM_H], dtype=np.uint8).reshape((CAM_H, CAM_W))
            img_surface = pygame.surfarray.make_surface(y_plane.T)
            
            # We display the camera view in a slightly smaller window (90%) 
            # so you can see the monitor's actual edges around it.
            view_w, view_h = int(WIDTH * 0.9), int(HEIGHT * 0.9)
            scaled_surf = pygame.transform.scale(img_surface, (view_w, view_h))
            
            # Center the camera view on the screen
            view_x = (WIDTH - view_w) // 2
            view_y = (HEIGHT - view_h) // 2
            screen.blit(scaled_surf, (view_x, view_y))

            # 3. Draw Overlays
            if show_overlay:
                RED = (255, 0, 0)
                # Diagonal X spanning the whole screen
                pygame.draw.line(screen, RED, (0, 0), (WIDTH, HEIGHT), 2)
                pygame.draw.line(screen, RED, (WIDTH, 0), (0, HEIGHT), 2)
                # Outer Corner Brackets
                pygame.draw.lines(screen, RED, False, [(0, 40), (0, 0), (40, 0)], 4)
                pygame.draw.lines(screen, RED, False, [(WIDTH-40, 0), (WIDTH-1, 0), (WIDTH-1, 40)], 4)

            pygame.display.flip()

            for event in pygame.event.get():
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_SPACE:
                        show_overlay = not show_overlay
                    elif event.key in [pygame.K_q, pygame.K_ESCAPE]:
                        running = False
    finally:
        pipe.terminate()
        pygame.quit()

if __name__ == "__main__":
    run_alignment()