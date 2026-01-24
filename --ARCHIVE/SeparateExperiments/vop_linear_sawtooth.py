"""
VOP Module:     vop_linear_sawtooth.py
Version:        v0.0.1
Description:    Linear RGB ramps (0-255-0) to check perceptual flatness.
"""

import os
import pygame

def run_sawtooth():
    os.environ["DISPLAY"] = ":0"
    pygame.init()
    WIDTH, HEIGHT = 1920, 1080
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
    
    # Draw a 0-255-0 Ramp for each channel
    for x in range(WIDTH):
        # Create a triangle wave (0 up to 255 at center, back to 0)
        if x < WIDTH // 2:
            val = int((x / (WIDTH // 2)) * 255)
        else:
            val = int((1 - ((x - WIDTH // 2) / (WIDTH // 2))) * 255)
            
        pygame.draw.line(screen, (val, 0, 0), (x, 0), (x, HEIGHT // 3))
        pygame.draw.line(screen, (0, val, 0), (x, HEIGHT // 3), (x, 2 * HEIGHT // 3))
        pygame.draw.line(screen, (0, 0, val), (x, 2 * HEIGHT // 3), (x, HEIGHT))
        
    pygame.display.update()
    
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN and event.key in [pygame.K_q, pygame.K_ESCAPE]:
                running = False
    pygame.quit()

if __name__ == "__main__":
    run_sawtooth()