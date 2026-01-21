"""
VOP Module:     vop_smear_8.py
Version:        v0.0.9
Description:    SSH-Optimized VOP Previewer.
                - Decodes ANSI Escape Sequences for Arrow Keys over SSH.
                - Left/Right/Down: Start/End/Middle.
                - Enter: Capture.
                - Backspace/ESC: Quit.
"""

import os
import time
import sys
import tty
import termios
import select
import subprocess
import argparse
import pygame
import datetime

# --- Transformation Engine ---
def get_transformed_surface(source_img, progress, rot_start, rot_end, scale_start, scale_end, tilt_start, tilt_end):
    curr_scale = scale_start + (progress * (scale_end - scale_start))
    current_rot = rot_start + (progress * (rot_end - rot_start))
    tilt_val = tilt_start + (progress * (tilt_end - tilt_start))
    
    scaled_w = max(1, int(source_img.get_width() * curr_scale))
    scaled_h = max(1, int(source_img.get_height() * curr_scale))
    working_img = pygame.transform.scale(source_img, (scaled_w, scaled_h))
    rotated_img = pygame.transform.rotate(working_img, current_rot)
    
    w, h = rotated_img.get_size()
    warped_surf = pygame.Surface((w, h), pygame.SRCALPHA)
    for x in range(w):
        # Apply vertical wedge tilt
        slice_h = int(h * (1.0 - (tilt_val * x / w)))
        slice_h = max(1, slice_h)
        pixel_slice = rotated_img.subsurface((x, 0, 1, h))
        scaled_slice = pygame.transform.scale(pixel_slice, (1, slice_h))
        warped_surf.blit(scaled_slice, (x, (h - slice_h) // 2))
    return warped_surf

# --- SSH Terminal Decoding ---
def get_ssh_key():
    """Reads and decodes multi-byte escape sequences from SSH stdin."""
    if not select.select([sys.stdin], [], [], 0)[0]:
        return None
    
    char = sys.stdin.read(1)
    if char == '\x1b': # Escape character
        # Read the next two characters for arrow codes (^[[C, etc)
        seq = sys.stdin.read(2)
        if seq == '[D': return 'LEFT'
        if seq == '[C': return 'RIGHT'
        if seq == '[B': return 'DOWN'
        if seq == '[A': return 'UP'
    elif char == '\r' or char == '\n':
        return 'ENTER'
    elif char == '\x7f' or char == '\x1b':
        return 'QUIT'
    return char

def run_vop(args):
    VERSION = "v0.0.9"
    PRO_MAG_DIR = os.path.expanduser("~/vop/ProjMag")
    
    # Timing Setup
    SAFETY_BUFFER_MS = 500.0
    TOTAL_SMEAR_MS = float(args.smear * 1000.0)
    EXPOSURE_MS = TOTAL_SMEAR_MS + (SAFETY_BUFFER_MS * 2)
    SHUTTER_US = int(EXPOSURE_MS * 1000)
    
    START_BLACK_1 = 1000.0
    START_SMEAR   = START_BLACK_1 + SAFETY_BUFFER_MS
    START_BLACK_2 = START_SMEAR + TOTAL_SMEAR_MS
    END_ALL       = START_BLACK_2 + SAFETY_BUFFER_MS

    # Init Graphics
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    pygame.init()
    pygame.mouse.set_visible(False)
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    WIDTH, HEIGHT = screen.get_size()
    
    # Load Asset
    img_path = os.path.join(PRO_MAG_DIR, args.image)
    source_img = pygame.image.load(img_path).convert_alpha()
    x1, y1 = map(float, args.pos_start.split(','))
    x2, y2 = map(float, args.pos_end.split(','))

    # Save terminal settings for restoration
    old_settings = termios.tcgetattr(sys.stdin)
    try:
        tty.setraw(sys.stdin.fileno()) # Enter Raw Mode for direct key capture
        
        print("\r\nVOP 9 READY. [LEFT]=Start, [DOWN]=Mid, [RIGHT]=End | [ENTER]=Capture | [ESC]=Exit\r\n")

        previewing = True
        preview_progress = 0.5 

        while previewing:
            # 1. Check SSH Keys
            key = get_ssh_key()
            if key == 'LEFT':    preview_progress = 0.0
            if key == 'DOWN':    preview_progress = 0.5
            if key == 'RIGHT':   preview_progress = 1.0
            if key == 'ENTER':   previewing = False
            if key == 'QUIT':    return

            # 2. Check Physical Keyboard (Fallback)
            for event in pygame.event.get():
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_LEFT:  preview_progress = 0.0
                    if event.key == pygame.K_DOWN:  preview_progress = 0.5
                    if event.key == pygame.K_RIGHT: preview_progress = 1.0
                    if event.key == pygame.K_RETURN: previewing = False

            # --- Render Preview ---
            screen.fill((20, 20, 20))
            curr_x = int((x1 + (preview_progress * (x2 - x1))) * WIDTH)
            curr_y = int((y1 + (preview_progress * (y2 - y1))) * HEIGHT)
            surf = get_transformed_surface(source_img, preview_progress, args.rot_start, args.rot_end, args.scale_start, args.scale_end, args.tilt_start, args.tilt_end)
            rect = surf.get_rect(center=(curr_x, curr_y))
            screen.blit(surf, rect.topleft)
            pygame.display.update()

    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings) # Restore terminal

    # --- Capture Mode (v0.0.8 Logic Preserved) ---
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ImageSmear_{VERSION}_{timestamp}.jpg"
    metadata = f"VOP:{VERSION}|TILT:{args.tilt_start}>{args.tilt_end}"

    anchor_time = time.time()
    captured = False
    running = True

    while running:
        elapsed = (time.time() - anchor_time) * 1000
        if elapsed > END_ALL + 2000: running = False; continue

        if START_SMEAR <= elapsed < START_BLACK_2:
            progress = (elapsed - START_SMEAR) / TOTAL_SMEAR_MS
            curr_x = int((x1 + (progress * (x2 - x1))) * WIDTH)
            curr_y = int((y1 + (progress * (y2 - y1))) * HEIGHT)
            surf = get_transformed_surface(source_img, progress, args.rot_start, args.rot_end, args.scale_start, args.scale_end, args.tilt_start, args.tilt_end)
            rect = surf.get_rect(center=(curr_x, curr_y))
            screen.fill((0,0,0))
            screen.blit(surf, rect.topleft)
        else:
            screen.fill((0, 0, 0))
        
        pygame.display.update()

        if not captured and elapsed >= (START_BLACK_1 - args.offset):
            subprocess.Popen(["rpicam-still", "-o", filename, "--shutter", str(SHUTTER_US), "--gain", str(args.gain), "--immediate", "--awbgains", "3.18,1.45", "--exif", f"EXIF.UserComment={metadata}", "-n"])
            captured = True

    pygame.quit()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=str, required=True)
    parser.add_argument("--offset", type=int, default=718)
    parser.add_argument("--smear", type=float, default=8.0)
    parser.add_argument("--gain", type=float, default=1.0)
    parser.add_argument("--rot_start", type=float, default=0.0)
    parser.add_argument("--rot_end", type=float, default=0.0)
    parser.add_argument("--pos_start", type=str, default="0.5,0.5")
    parser.add_argument("--pos_end", type=str, default="0.5,0.5")
    parser.add_argument("--scale_start", type=float, default=1.0)
    parser.add_argument("--scale_end", type=float, default=1.0)
    parser.add_argument("--tilt_start", type=float, default=0.0)
    parser.add_argument("--tilt_end", type=float, default=0.0)
    run_vop(parser.parse_args())