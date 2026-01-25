"""
VOP Module:     kiss_engine_v0.0.1.py
Version:        v0.0.1
Description:    Minimalist KMSDRM color filler for sanity testing and learning how flask web-apps work. 
"""
import os
import sys
import argparse
import time
import pygame
import moderngl

# Force KMSDRM
os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
os.environ["SDL_VIDEO_KMSDRM_FORCE_MODE"] = "1"
os.environ["SDL_DRM_DEVICE"] = "/dev/dri/card0"

def run_kiss(color_str):
    pygame.init()
    pygame.mouse.set_visible(False)

    # Simple color parsing "1,0,0" -> (1.0, 0.0, 0.0)
    rgb = [float(x) for x in color_str.split(',')]

    try:
        # Request GLES 3.1 context
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 1)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_ES)

        pygame.display.set_mode((0, 0), pygame.OPENGL | pygame.DOUBLEBUF | pygame.FULLSCREEN)
        ctx = moderngl.create_context(require=310)

        # Fill screen
        ctx.clear(rgb[0], rgb[1], rgb[2])
        pygame.display.flip()

        # Keep alive just long enough to see it
        time.sleep(0.1)

    finally:
        pygame.quit()
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--color", default="0,0,0")
    args = parser.parse_args()
    run_kiss(args.color)