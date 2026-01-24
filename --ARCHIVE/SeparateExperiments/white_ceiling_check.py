"""
VOP Module:     white_ceiling_check.py

Version:        v0.0.2
Description:    High-visibility debug ramp. Includes a black border and
                text to verify scaling and viewport.

Version:        v0.0.1
Description:    Displays the top 20 steps of the white range (235-255).
                Used to set Contrast without clipping.
"""

import os
import pygame

def run_check():
    os.environ["DISPLAY"] = ":0"
    pygame.init()
    
    # Try to force exactly 1920x1080
    screen = pygame.display.set_mode((1920, 1080), pygame.FULLSCREEN)
    pygame.mouse.set_visible(False)
    font = pygame.font.SysFont("monospace", 40)

    # 1. Fill background with BLACK to verify borders
    screen.fill((0, 0, 0))

    # 2. Draw the White Ramp (230 to 255) in a smaller window
    # This leaves a black "frame" around the test so we know we aren't zoomed in.
    inner_rect = pygame.Rect(100, 100, 1720, 880)
    start_val = 230
    end_val = 255
    steps = end_val - start_val + 1
    step_width = inner_rect.width // steps

    for i in range(steps):
        val = start_val + i
        # Draw vertical bars
        pygame.draw.rect(screen, (val, val, val), 
                         (inner_rect.left + (i * step_width), inner_rect.top, step_width, inner_rect.height))

    # 3. Add Labels
    label_low = font.render("Val: 230", True, (255, 0, 0)) # Red text
    label_high = font.render("Val: 255", True, (255, 0, 0))
    screen.blit(label_low, (100, 50))
    screen.blit(label_high, (1600, 50))

    pygame.display.update()

    print("White Ceiling Check v0.0.2")
    print("If you don't see a RED LABEL and a BLACK BORDER, the display is zoomed.")

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN:
                if event.key in [pygame.K_q, pygame.K_ESCAPE]:
                    running = False
    
    pygame.quit()

if __name__ == "__main__":
    run_check()