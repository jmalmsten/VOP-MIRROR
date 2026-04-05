#!/usr/bin/env python3
# VOP Idle Screen
# Location:     modules/idle_screen.py
# Description:  A fun little idle screen animation that should be running when the VOP HDMI screen is not being used.

import pygame
import os
import sys
import socket

# Force Pygame to bypass X11 and use the hardware framebuffer
os.environ["SDL_VIDEODRIVER"] = "kmsdrm"

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8",80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def main():
    # Explicitly initialize the display module to catch the REAL error
    try:
        pygame.display.init()
    except pygame.error as e:
        print(f"\n[CRITICAL ERROR] SDL2 Video Subsystem Failed: {e}")
        print("Check KMSDRM permissions or device availability.\n")
        sys.exit(1)

    pygame.font.init()
        
    # Auto-detect resolution
    infoObject = pygame.display.Info()
    screen_w = infoObject.current_w
    screen_h = infoObject.current_h

    # Create the hardware display surface
    screen = pygame.display.set_mode((screen_w, screen_h), pygame.FULLSCREEN)

    # Hiding the mouse after the display context exists
    pygame.mouse.set_visible(False)

    BLACK = (0, 0, 0)
    WHITE = (255, 255, 255)
    
    # Find the graphic in the graphics folder one level up.
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    img_path = os.path.join(base_dir, "graphics", "branding.png")

    try:
        logo = pygame.image.load(img_path).convert_alpha()
    except FileNotFoundError:
        print(f"Error: Could not load branding at {img_path}")
        sys.exit(1)
    
    logo_w, logo_h = logo.get_rect().size

    # Initial vectors
    x, y = 100, 100
    dx, dy = 3, 3

    sys_font = pygame.font.SysFont("monospace", 36, bold=True)
    ip_addr = get_local_ip()
    port = sys.argv[1] if len(sys.argv) > 1 else "5000"
    telemetry_text = sys_font.render(f"VOP ENGINE | {ip_addr}:{port}", True, WHITE)

    # --- UNIFIED BOUNDING BOX CALCULATION --- #
    # Retrieve dimensions of the rendered text surface

    text_w = telemetry_text.get_width()
    text_h = telemetry_text.get_height()
    padding = 20 # Pixels of vertical space between the logo and the text

    # Calculate the local physical dimensions required to hold both elements
    # The width is dictated by whichever element is wider
    box_w = max(logo_w, text_h)
    # The height is the sum of both elements plus the padding
    box_h = logo_h + padding + text_h
    
    clock = pygame.time.Clock()
    running = True
    
    while running:
        screen.fill(BLACK)

        # Update the top-left coordinate of the unified bounding box
        x += dx
        y += dy

        # DVD Bounce Collision
        # Evaluated against the combined width and height to prevent either element from clipping
        if x <= 0 or (x + box_w) >= screen_w:
            dx *= -1
        if y <= 0 or (y + box_h) >= screen_h:
            dy *= -1

        # Calculate the internal rendering coordinates for the logo
        # Centers the logo horizontally inside the bounding box
        logo_draw_x = x + (box_w - logo_w) // 2
        logo_draw_y = y

        # Calculate the internal rendering coordinates for the text
        # Centers the text horizontally below the logo
        text_draw_x = x + (boxw - textw) // 2
        text_draw_y = y + logo_h + padding

        # Draw elements to the buffer at their computed offsets
        screen.blit(logo, (logo_draw_x,logo_draw_y))
        screen.blit(telemetry_text, (text_draw_x, text_draw_y))

        pygame.display.flip()
        clock.tick(60)
if __name__ == "__main__":
    main()