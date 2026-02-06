"""
VOP Module: config_engine
Version: v0.1.0
Description: Handles config.txt HDMI Handshake, and non-blocking input.
"""

import os, sys, select, pygame

def load_config():
    """
    Reads config.txt and merges it with system defaults. 
    If a key isn't in the file, we use these as safe defaults
    """

    cfg = {
        'SCREEN_WIDTH':         1920,           # Default screen width and height when no HDMI handshake is possible
        'SCREEN_HEIGHT':        1080,           # see above
        'BLACK_CLIP':           0.03,
        'GAMMA':                1.0,
        'GLOBAL_BRIGHTNESS':    1.0,            # Master Fader of the VOP light. 
        'CAMERA_DEVICE':        '/dev/video0',
        'VSYNC_PULL':           0.01,
        'PROJ_MAG':             'ProjMag',      # INPUT: What should be showing on the projector-screen
        'PROJ_BIPACK':          'ProjBiPack',   # INPUT: Here goes holdout mattes and such for the Projector screen.
        'CAM_MAG':              'CamMag',       # Output: Here the live Latent TIFF files will be created and modified. BEWARE, this is modeled after real camera systems, so files here will be altered when exposed.
        'CAM_BIPACK':           'CamBiPack',    # INPUT: Here goes holdout mattes for the recording side. 
        'DEFAULT_DURATION':     0.5             # For now, this sets the amount of time used for the smear duration for each frame. In the future, this will be determined by the shutter speed of the camera when I get hold of a better camera.
    }

    # Check if the user has provided a config file
    if os.path.exists("config.txt"):
        with open("config.txt", "r") as f:
            for line in f:
                # Ignore comments (#) and empty lines
                if "=" in line and not line.startswith("#"):
                    k, v = [x.strip() for x in line.split("=")]
                    try:
                        # Auto-convert numbers; strings stay strings
                        cfg[k] = float(v) if "." in v else int(v)
                    except ValueError:
                        cfg[k] = v
    return cfg

def get_display_res(cfg):
    """
    Performs the HDMI Handshake using KMSDRM.
    KMSDRM also allows us to draw directly to the video buffer without a desktop.
    """

    try:
        # Force Pygame to use the Linux Direct Rendering Manager
        os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
        pygame.display.init()
        info = pygame.display.Info()
        # Get the native resolution of the connected monitor/projector
        res = (info.current_w, info.current_h)
        pygame.display.quit()
        # Return detected res, and True if it's a valid handshake
        return res, (True if res[0] > 0 else False)
    except:
        # Fallback to config.txt values if no monitor is detected
        return (int(cfg['SCREEN_WIDTH']), int(cfg[SCREEN_HEIGHT])), False

def check_for_exit(): 
    """
    Non-blocking terminal check.
    Allows us to 'listen' for an Enter keypress in the CLI while the projector loop is running in the background.
    """
    # Look at standard input (stdin) for 0.0 seconds (don't wait)
    i, o, e = select.select([sys.stdin], [], [], 0.0)
    for s in i:
        if s == sys.stdin:
            sys.stdin.readline() # Clear the key from the buffer
            return True
    return False