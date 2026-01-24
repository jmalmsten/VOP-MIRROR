"""
VOP Module:     clinical_white_ramp.py
Version:        v0.0.1
Description:    High-visibility brick ramp for testing White Clipping.
                Displays large blocks of grayscale values from 200 to 255.
"""

import os
import pygame

def run_check():
    os.environ["DISPLAY"] = ":0"
    pygame.init()
    
    WIDTH, HEIGHT = 1920, 1080
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
    pygame.mouse.set_visible(False)
    font = pygame.font.SysFont("monospace", 30, bold=True)

    # Values to test: We want a broad range at top, then fine-grained at bottom
    # Row 1: 200, 210, 220, 230
    # Row 2: 231, 234, 237, 240
    # Row 3: 241, 242, 243, 244, 245, 246, 247
    # Row 4: 248, 249, 250, 251, 252, 253, 254, 255
    
    rows = [
        [200, 210, 220, 230],
        [231, 234, 237, 240],
        [241, 242, 243, 244, 245, 246, 247],
        [248, 249, 250, 251, 252, 253, 254, 255]
    ]

    screen.fill((0, 0, 0)) # Black background border
    
    row_h = (HEIGHT - 100) // len(rows)
    margin = 50

    for r_idx, row_vals in enumerate(rows):
        col_w = (WIDTH - (margin * 2)) // len(row_vals)
        y_pos = margin + (r_idx * row_h)
        
        for c_idx, val in enumerate(row_vals):
            x_pos = margin + (c_idx * col_w)
            rect = pygame.Rect(x_pos, y_pos, col_w - 5, row_h - 5)
            
            # Draw the Brick
            pygame.draw.rect(screen, (val, val, val), rect)
            
            # Label it (using red for visibility)
            txt = font.render(str(val), True, (255, 0, 0))
            screen.blit(txt, (x_pos + 10, y_pos + 10))

    pygame.display.update()

    print("Clinical White Ramp v0.0.1")
    print("Check Row 4 (Bottom). Can you see the lines between 254 and 255?")

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN:
                if event.key in [pygame.K_q, pygame.K_ESCAPE]:
                    running = False
    
    pygame.quit()

if __name__ == "__main__":
    run_check()