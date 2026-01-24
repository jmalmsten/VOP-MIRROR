"""
VOP Module:     vop_monitor_limit_check.py
Version:        v0.0.1
Description:    Manual monitor ceiling check. Find where R, G, or B flatlines.
                Left: Reference (Fixed at 128)
                Right: Test (Variable 0-255)
"""

import os
import pygame

def run_limit_check():
    os.environ["DISPLAY"] = ":0"
    pygame.init()
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    font = pygame.font.SysFont("monospace", 40, bold=True)
    
    val = 128
    mode = 0 # 0:Red, 1:Green, 2:Blue
    modes = ["RED", "GREEN", "BLUE"]
    
    running = True
    while running:
        screen.fill((0, 0, 0))
        
        # Color vector
        color = [0, 0, 0]
        color[mode] = val
        
        # Draw the test block
        pygame.draw.rect(screen, tuple(color), (0, 0, 1920, 1080))
        
        # Label
        txt = font.render(f"MODE: {modes[mode]} | VALUE: {val}", True, (255, 255, 255))
        screen.blit(txt, (50, 50))
        
        pygame.display.update()
        
        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_UP: val = min(255, val + 1)
                elif event.key == pygame.K_DOWN: val = max(0, val - 1)
                elif event.key == pygame.K_RIGHT: val = min(255, val + 5)
                elif event.key == pygame.K_LEFT: val = max(0, val - 5)
                elif event.key == pygame.K_m: mode = (mode + 1) % 3
                elif event.key in [pygame.K_q, pygame.K_ESCAPE]: running = False
    pygame.quit()

if __name__ == "__main__":
    run_limit_check()