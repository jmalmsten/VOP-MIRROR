"""
VOP Module:     grey_maximizer.py
Version:        v0.0.1
Description:    Displays a split row grayscale ramp with expanded calibration zones for black (0/1) and white (254/255)
"""

import os
import numpy as np
import pygame

# HDMI Resolution Targets
WIDTH, HEIGHT = 1920, 1080

def run_maximizer():
    # Point to the local X server
    os.environ["Display"] = ":0"

    print("Launching Enhanced Grey Maximizer...")
    print("Top Row: 0 to 127 | Bottom Row 128 to 255")
    print("Controls: Press 'Q' or 'ESC' to exit.")

    # Initialize Pygame for the Framebuffer
    pygame.init()
    pygame.mouse.set_visible(False)

    # Create the Fullscreen Display
    try:
        # We use (WIDTH, HEIGHT) to match your monitor's native 1080p
        screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
    except pygame.error as e:
        print(f"X11 Display connection failed: {e}")
        return

    # 1. Logic for expanded ends (10% width for edge blocks)
    edge_w = int(WIDTH * 0.10)
    ramp_w = WIDTH - (edge_w * 2)

    def generate_row(start_val, end_val):
        row = np.zeros(WIDTH, dtype=np.uint8)

        # Left Edge (Value 0 and 1, or 128 and 129)
        row[0:edge_w//2] = start_val
        row[edge_w//2:edge_w] = start_val + 1

        # Middle Ramp (Values between edges)
        middle_vals = np.linspace(start_val + 2, end_val -2, ramp_w, dtype=np.uint8)
        row[edge_w:edge_w + ramp_w] = middle_vals

        # Right Edge (Value 126 and 127, or 254 and 255)
        row[edge_w + ramp_w : edge_w + ramp_w + edge_w//2] = end_val -1
        row[edge_w + ramp_w + edge_w//2:] = end_val

        return row
    
    # 2. Build the rows
    top_row_data = generate_row(0,127)
    bottom_row_data = generate_row(128, 255)

    # 3. Assemble the 3-channel RGB image
    full_image = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    for c in range(3):
        full_image[0:HEIGHT//2, :, c] = top_row_data
        full_image[HEIGHT//2:, :, c] = bottom_row_data

    # Convert to Pygame surface (swap axes for W,H alignment)
    surf = pygame.surfarray.make_surface(full_image.swapaxes(0,1))

    running = True
    while running:
        screen.blit(surf, (0, 0))
        pygame.display.update()

        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN:
                if event.key in [pygame.K_ESCAPE, pygame.K_q]:
                    running = False
            elif event.type == pygame.QUIT:
                running = False
    
    pygame.display.quit()
    pygame.quit()

if __name__ == "__main__":
    run_maximizer()