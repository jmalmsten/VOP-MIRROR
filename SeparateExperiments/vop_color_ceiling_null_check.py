"""
VOP Module:     vop_color_ceiling_null_check.py
Version:        v0.0.1
Description:    Split-screen null-comparator for finding physical color ceilings.
                Left Side:  UP/DOWN (+/- 1), Q (255), A (0)
                Right Side: RIGHT/LEFT (+/- 1), W (255), S (0)
                Channel:    C (Toggle Red/Green/Blue)
"""

import os
import pygame

def run_limit_check():
    os.environ["DISPLAY"] = ":0"
    pygame.init()
    
    # Hardware Resolution
    WIDTH, HEIGHT = 1920, 1080
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
    pygame.mouse.set_visible(False)
    font = pygame.font.SysFont("monospace", 42, bold=True)

    # Initial calibration state
    left_val = 127
    right_val = 128
    
    # Channel Toggle (0:R, 1:G, 2:B)
    channel = 0 
    channels = ["RED", "GREEN", "BLUE"]

    print("VOP Color Ceiling Null-Check v0.0.1")
    print("--- Controls ---")
    print("Channel Toggle: [C]")
    print("Left Side:  [UP/DOWN] +/-1 | [Q] 255 | [A] 0")
    print("Right Side: [RGHT/LFT] +/-1 | [W] 255 | [S] 0")
    print("Exit:       [ESC] or [X]")

    running = True
    while running:
        # 1. Prepare Colors
        l_color = [0, 0, 0]
        r_color = [0, 0, 0]
        l_color[channel] = left_val
        r_color[channel] = right_val

        # 2. Render the two halves
        pygame.draw.rect(screen, tuple(l_color), (0, 0, WIDTH//2, HEIGHT))
        pygame.draw.rect(screen, tuple(r_color), (WIDTH//2, 0, WIDTH//2, HEIGHT))

        # 3. Render status text with shadow
        def draw_status(x, y, side, val, ch_name):
            text = f"{side} {ch_name}: {val}"
            shadow = font.render(text, True, (20, 20, 20))
            label = font.render(text, True, (255, 255, 255))
            screen.blit(shadow, (x + 2, y + 2))
            screen.blit(label, (x, y))

        draw_status(60, HEIGHT - 100, "LEFT", left_val, channels[channel])
        draw_status(WIDTH - 450, HEIGHT - 100, "RIGHT", right_val, channels[channel])

        pygame.display.update()

        # 4. Keyboard Logic
        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN:
                # Channel Toggle
                if event.key == pygame.K_c:
                    channel = (channel + 1) % 3
                
                # LEFT SIDE
                elif event.key == pygame.K_UP:    left_val = min(255, left_val + 1)
                elif event.key == pygame.K_DOWN:  left_val = max(0, left_val - 1)
                elif event.key == pygame.K_q:     left_val = 255
                elif event.key == pygame.K_a:     left_val = 0
                
                # RIGHT SIDE
                elif event.key == pygame.K_RIGHT: right_val = min(255, right_val + 1)
                elif event.key == pygame.K_LEFT:  right_val = max(0, right_val - 1)
                elif event.key == pygame.K_w:     right_val = 255
                elif event.key == pygame.K_s:     right_val = 0
                
                # EXIT
                elif event.key in [pygame.K_ESCAPE, pygame.K_x]:
                    running = False
    
    pygame.quit()

if __name__ == "__main__":
    run_limit_check()