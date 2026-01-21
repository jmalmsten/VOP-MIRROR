"""
VOP Module:     Image-smear_7.py
Version:        v0.0.7
Description:    VOP Keyframe Previewer & Smear System.
                - Preview Mode: Use 'S', 'M', 'E' to verify spatial states.
                - Capture Mode: Executes 10s smear with EXIF metadata logging.
                - Order: Scale -> Rotate -> Pseudo-3D Perspective Warp.
"""

import os
import time
import subprocess
import argparse
import pygame
import datetime

# --- Clinical Transformation Function ---
def get_transformed_surface(source_img, progress, rot_start, rot_end, scale_start, scale_end, pers_start, pers_end):
    """
    Calculates the spatial state of the image at any given 'progress' (0.0 to 1.0).
    Applies transformations in the order: Scale -> Rotate -> Perspective.
    """
    # 1. Linear Interpolation of Transformation Values
    curr_scale = scale_start + (progress * (scale_end - scale_start))
    current_rot = rot_start + (progress * (rot_end - rot_start))
    pers_val = pers_start + (progress * (pers_end - pers_start))
    
    # 2. Apply Scale & Rotation
    # We use pygame.transform.rotozoom if we wanted both, but separate calls 
    # allow for finer control over scaling algorithms.
    scaled_w = max(1, int(source_img.get_width() * curr_scale))
    scaled_h = max(1, int(source_img.get_height() * curr_scale))
    working_img = pygame.transform.scale(source_img, (scaled_w, scaled_h))
    rotated_img = pygame.transform.rotate(working_img, current_rot)
    
    # 3. Apply Perspective Warp (Vertical Slice Scaling)
    # This simulates a 3D tilt by progressively scaling the height of 1-pixel slices.
    w, h = rotated_img.get_size()
    warped_surf = pygame.Surface((w, h), pygame.SRCALPHA)
    for x in range(w):
        # Height of the current vertical column decreases based on pers_val
        slice_h = int(h * (1.0 - (pers_val * x / w)))
        if slice_h <= 0: slice_h = 1
        
        # Extract the source column and scale it
        pixel_slice = rotated_img.subsurface((x, 0, 1, h))
        scaled_slice = pygame.transform.scale(pixel_slice, (1, slice_h))
        
        # Blit the slice centered vertically to maintain horizontal axis
        warped_surf.blit(scaled_slice, (x, (h - slice_h) // 2))
        
    return warped_surf

def run_vop(args):
    # --- Config & Paths ---
    VERSION = "v0.0.7"
    PRO_MAG_DIR = os.path.expanduser("~/vop/ProjMag")
    
    # Timing logic (v0.0.4 Anchor Method)
    SAFETY_BUFFER_MS = 500.0
    TOTAL_SMEAR_MS = float(args.smear * 1000.0)
    EXPOSURE_MS = TOTAL_SMEAR_MS + (SAFETY_BUFFER_MS * 2)
    SHUTTER_US = int(EXPOSURE_MS * 1000)
    
    # Milestone Markers
    START_BLACK_1 = 1000.0 # Settling time
    START_SMEAR   = START_BLACK_1 + SAFETY_BUFFER_MS
    START_BLACK_2 = START_SMEAR + TOTAL_SMEAR_MS
    END_ALL       = START_BLACK_2 + SAFETY_BUFFER_MS

    # --- Pygame Initialization ---
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    pygame.init()
    pygame.mouse.set_visible(False)
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    WIDTH, HEIGHT = screen.get_size()
    
    # Load Source Lineart
    img_path = os.path.join(PRO_MAG_DIR, args.image)
    if not os.path.exists(img_path):
        print(f"ERROR: Image not found at {img_path}")
        pygame.quit()
        return
    source_img = pygame.image.load(img_path).convert_alpha() # Use alpha for clean warping
    
    # Parse Position Coordinates
    x1, y1 = map(float, args.pos_start.split(','))
    x2, y2 = map(float, args.pos_end.split(','))

    # --- STATE 1: INTERACTIVE PREVIEW ---
    previewing = True
    preview_progress = 0.5 # Start at middle for immediate feedback
    font = pygame.font.SysFont("monospace", 24, bold=True)

    print("VOP PREVIEW MODE: [S]tart, [M]iddle, [E]nd | [SPACE] to capture | [ESC] to abort.")

    while previewing:
        for event in pygame.event.get():
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_s: preview_progress = 0.0
                if event.key == pygame.K_m: preview_progress = 0.5
                if event.key == pygame.K_e: preview_progress = 1.0
                if event.key == pygame.K_SPACE: previewing = False # Switch to Capture State
                if event.key == pygame.K_ESCAPE: pygame.quit(); return

        # Render background for preview (light gray to see frame bounds)
        screen.fill((30, 30, 30))
        
        # Calculate current position based on normalized coordinates
        curr_x = int((x1 + (preview_progress * (x2 - x1))) * WIDTH)
        curr_y = int((y1 + (preview_progress * (y2 - y1))) * HEIGHT)
        
        # Get the transformation for this frame
        transformed_surf = get_transformed_surface(
            source_img, preview_progress, 
            args.rot_start, args.rot_end, 
            args.scale_start, args.scale_end, 
            args.pers_start, args.pers_end
        )
        
        # Blit centered at current target
        rect = transformed_surf.get_rect(center=(curr_x, curr_y))
        screen.blit(transformed_surf, rect.topleft)
        
        # UI Overlay
        ui_label = font.render(f"PREVIEW: {int(preview_progress*100)}% | POS: {curr_x},{curr_y}", True, (0, 255, 0))
        screen.blit(ui_label, (20, 20))
        pygame.display.update()

    # --- STATE 2: CAPTURE MODE (HIGH PRECISION) ---
    print("PREVIEW CLOSED. INITIATING 10s CAPTURE SEQUENCE...")
    
    # Filename & Metadata
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ImageSmear_{VERSION}_{timestamp}.jpg"
    metadata = (f"VOP:{VERSION}|IMG:{args.image}|OFF:{args.offset}|"
                f"SMEAR:{args.smear}|POS:{args.pos_start}>{args.pos_end}|"
                f"ROT:{args.rot_start}>{args.rot_end}|PER:{args.pers_start}>{args.pers_end}")

    # Anchor Time Reset for Capture
    anchor_time = time.time()
    captured = False
    running = True

    while running:
        elapsed = (time.time() - anchor_time) * 1000
        
        # Termination Buffer
        if elapsed > END_ALL + 2000:
            running = False
            continue

        # Coordinate & Phase Logic
        if elapsed < START_SMEAR:
            # Black Buffer 1 (Pre-Exposure)
            color_bg = (0, 0, 0)
            show_image = False
        elif elapsed < START_BLACK_2:
            # ACTIVE SMEAR PERIOD
            progress = (elapsed - START_SMEAR) / TOTAL_SMEAR_MS
            curr_x = int((x1 + (progress * (x2 - x1))) * WIDTH)
            curr_y = int((y1 + (progress * (y2 - y1))) * HEIGHT)
            
            transformed_surf = get_transformed_surface(
                source_img, progress, 
                args.rot_start, args.rot_end, 
                args.scale_start, args.scale_end, 
                args.pers_start, args.pers_end
            )
            rect = transformed_surf.get_rect(center=(curr_x, curr_y))
            color_bg = (0, 0, 0)
            show_image = True
        else:
            # Black Buffer 2 (Post-Exposure)
            color_bg = (0, 0, 0)
            show_image = False

        # Rendering for Exposure
        screen.fill(color_bg)
        if show_image:
            screen.blit(transformed_surf, rect.topleft)
        pygame.display.update()

        # Trigger Command
        trigger_target = START_BLACK_1 - args.offset
        if not captured and elapsed >= trigger_target:
            cmd = [
                "rpicam-still", "-o", filename,
                "--shutter", str(SHUTTER_US),
                "--gain", str(args.gain),
                "--immediate", "--awbgains", "3.18,1.45",
                "--exif", f"EXIF.UserComment={metadata}", "-n"
            ]
            subprocess.Popen(cmd)
            print(f"CAM_OPEN: {int(elapsed)}ms | Shutter: {SHUTTER_US}us")
            captured = True

    pygame.quit()
    print(f"SEQUENCE COMPLETE. Output: {filename}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", type=str, required=True, help="Filename in ~/vop/ProjMag")
    parser.add_argument("--offset", type=int, default=718, help="Trigger offset in ms")
    parser.add_argument("--smear", type=float, default=8.0, help="Duration in seconds")
    parser.add_argument("--gain", type=float, default=1.0, help="Analog Gain")
    parser.add_argument("--rot_start", type=float, default=0.0)
    parser.add_argument("--rot_end", type=float, default=0.0)
    parser.add_argument("--pos_start", type=str, default="0.5,0.5")
    parser.add_argument("--pos_end", type=str, default="0.5,0.5")
    parser.add_argument("--scale_start", type=float, default=1.0)
    parser.add_argument("--scale_end", type=float, default=1.0)
    parser.add_argument("--pers_start", type=float, default=0.0)
    parser.add_argument("--pers_end", type=float, default=0.0)
    
    args = parser.parse_args()
    run_vop(args)