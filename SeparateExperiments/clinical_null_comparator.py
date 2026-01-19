"""
VOP Module:     clinical_null_comparator.py
Version:        v0.0.2
Description:    Split-screen comparator with instant extreme snapping.
                Left Side:  UP/DOWN (+/- 1), Q (255), A (0)
                Right Side: RIGHT/LEFT (+/- 1), W (255), S (0)
"""

import os
import pygame

# Hardware Resolution
WIDTH, HEIGHT = 1920, 1080

def run_comparator():
    # Force use of the local frame buffer
    os.environ["DISPLAY"] = ":0"
    pygame.init()
    
    # Set to fullscreen
    try:
        screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.FULLSCREEN)
    except pygame.error:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        
    pygame.mouse.set_visible(False)
    font = pygame.font.SysFont("monospace", 42, bold=True)

    # Initial calibration state (start near middle to see a seam)
    left_val = 127
    right_val = 128
    
    print("Clinical Null Comparator v0.0.2")
    print("--- Controls ---")
    print("Left Side:  [UP/DOWN] +/-1 | [Q] 255 | [A] 0")
    print("Right Side: [RGHT/LFT] +/-1 | [W] 255 | [S] 0")
    print("Exit:       [ESC] or [X]")

    running = True
    while running:
        # 1. Render the two halves (No borders/lines)
        pygame.draw.rect(screen, (left_val, left_val, left_val), (0, 0, WIDTH//2, HEIGHT))
        pygame.draw.rect(screen, (right_val, right_val, right_val), (WIDTH//2, 0, WIDTH//2, HEIGHT))

        # 2. Render status text with shadow for legibility across all values
        def draw_labeled_val(val, x, y, side_name):
            text = f"{side_name}: {val}"
            # Shadow
            shadow = font.render(text, True, (20, 20, 20))
            screen.blit(shadow, (x + 2, y + 2))
            # Main Label (Red for high contrast on dark/light)
            label = font.render(text, True, (255, 50, 50))
            screen.blit(label, (x, y))

        draw_labeled_val(left_val, 60, HEIGHT - 100, "LEFT")
        draw_labeled_val(right_val, WIDTH - 300, HEIGHT - 100, "RIGHT")

        pygame.display.update()

        # 3. Handle Keyboard Events
        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN:
                # --- LEFT SIDE CONTROLS ---
                if event.key == pygame.K_UP:
                    left_val = min(255, left_val + 1)
                elif event.key == pygame.K_DOWN:
                    left_val = max(0, left_val - 1)
                elif event.key == pygame.K_q:
                    left_val = 255
                elif event.key == pygame.K_a:
                    left_val = 0
                
                # --- RIGHT SIDE CONTROLS ---
                elif event.key == pygame.K_RIGHT:
                    right_val = min(255, right_val + 1)
                elif event.key == pygame.K_LEFT:
                    right_val = max(0, right_val - 1)
                elif event.key == pygame.K_w:
                    right_val = 255
                elif event.key == pygame.K_s:
                    right_val = 0
                
                # --- EXIT ---
                elif event.key in [pygame.K_ESCAPE, pygame.K_x]:
                    running = False
            
            elif event.type == pygame.QUIT:
                running = False
    
    pygame.quit()

if __name__ == "__main__":
    run_comparator()