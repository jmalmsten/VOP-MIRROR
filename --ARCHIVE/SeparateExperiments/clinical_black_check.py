"""
VOP Module:     clinical_black_check.py

Version:        v0.0.3
Description:    Clinical black floor test. Supports Numpad and Top Row keys.
                Tests values 0 through 9 to find the monitor's "wake up" point.

Version:        v0.0.1
Description:    Fills the screen with specific low-level grey values (0,1,2)
                to test monitor "floor" and hardware lifting.
"""

import os
import pygame

def run_check():
    os.environ["DISPLAY"] = ":0"
    pygame.init()
    
    try:
        screen = pygame.display.set_mode((1920, 1080), pygame.FULLSCREEN)
    except pygame.error:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        
    pygame.mouse.set_visible(False)

    current_val = 0
    running = True

    print("Clinical Black Check v0.0.3")
    print("Keys 0-9 (Top row or Numpad) to change value. Q to quit.")

    # Map both top row and numpad keys to the same values
    key_map = {
        pygame.K_0: 0, pygame.K_KP0: 0,
        pygame.K_1: 1, pygame.K_KP1: 1,
        pygame.K_2: 2, pygame.K_KP2: 2,
        pygame.K_3: 3, pygame.K_KP3: 3,
        pygame.K_4: 4, pygame.K_KP4: 4,
        pygame.K_5: 5, pygame.K_KP5: 5,
        pygame.K_6: 10, pygame.K_KP6: 10, # Jumps to 10
        pygame.K_7: 15, pygame.K_KP7: 15, # Jumps to 15
        pygame.K_8: 20, pygame.K_KP8: 20, # Jumps to 20
        pygame.K_9: 25, pygame.K_KP9: 25  # Jumps to 25
    }

    while running:
        screen.fill((current_val, current_val, current_val))
        pygame.display.update()

        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN:
                if event.key in key_map:
                    current_val = key_map[event.key]
                    print(f"Active Value: {current_val}")
                elif event.key in [pygame.K_q, pygame.K_ESCAPE]:
                    running = False
            elif event.type == pygame.QUIT:
                running = False
    
    pygame.quit()

if __name__ == "__main__":
    run_check()