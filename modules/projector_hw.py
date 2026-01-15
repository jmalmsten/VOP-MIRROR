"""
VOP Module: projector_hw
Version: v0.1.0
Description: Handles the KMS/DRM display worker and the projector Bi-Pack math.
"""
import os, time, pygame, cv2, numpy as np
from multiprocessing import Process

def worker(trigger, stop, queue, cache, bp_cache, cfg, res):
    """
    Background process for HDMI output.
    Using a Process keeps the UI snappy while the GPU is busy warping
    """

    # Force the use of the Linux Direct Rendering Manager (No X11 required)
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    pygame.init()

    # Setup the hardware screen buffer
    screen = pygame.display.set_mode(res, pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF)
    pygame.mouse.set_visible(False)
    sw, sh = res

    while not stop.is_set():
        # Wait for the main script to trigger a frame capture/projection
        if trigger.wait(timeout=0.1):
            try:
                # Pull the interpolated frame data from the queue
                s = queue.get(block=False)
            except:
                continue
            
            # --- TEST PATTERN LOGIC --- 
            if s.get('type') == 'test_pattern':
                img = np.zeros((sh, sw, 3), dtype=np.uint8)
                for x in range(10):
                    val = int((x / 9.0) * 255)
                    cv2.rectangle(img, (x*(sw//10), 0), ((x+1)*(sw//10), sh), (val, val, val), -1)
                
                surf = pygame.surfarray.make_surface(np.transpose(img, (1, 0, 2)))
                screen.blit(surf, (0, 0))
                pygame.display.flip()
                time.sleep(s.get('duration', 5))
            
            # --- PRODUCTION PROJECTION ---
            else:
                # 1. Fetch the primary frame from ProjMag (RAM Cache)
                img_base = cache.get(s['image'])
                if img_base is None:
                    trigger.clear()
                    continue
                
                # 2. PROJ-BIPACK Multiplication
                # If a file with the SAME NAME exists in ProjBiPack, we multiply them.
                # Mathematically: Base * (Matte / 255.0)
                img_matte = bp_cache.get(s['image'])
                if img_matte is not None:
                    # Convert to float for math, then back to 8 bit. 
                    img_f = (img_base.astype(np.float32) * img_matte.astype(np.float32) / 255.0)
                    img = img_f.astype(np.uint8)
                else:
                    img = img_base

                # 3. OPTICAL PROCESSING (Gamma adjustment if needed)
                img_f = img.astype(np.float32) / 255.0
                if cfg['GAMMA'] != 1.0:
                    img_f = np.power(img_f, 1.0 / cfg['GAMMA'])

                # 4. COLOR GEL: Convert HEX to BGR
                rgb = [int(s['color_hex'].lstrip('#')[i:i+2], 16) for i in (0, 2, 4)]
                gel = (np.array([rgb[2], rgb[1], rgb[0]], dtype=np.float32) / 255.0) * cfg['GLOBAL_BRIGHTNESS']
                proc = np.clip(img_f * gel * 255.0, 0, 255).astype(np.uint8)

                # 5. SHUTTER SMEAR LOOP
                # Open the 'shutter' for for the duration and interpolate coordinates
                start_time = time.time()
                duration = float(s['steps'])
                while (time.time() - start_time) < duration:
                    t = (time.time() - start_time) / duration

                    # Map 0.0-1.0 coords to actual pixel locations
                    def p(c, a, st): return float(s[f'{c}_{a}_{st}']) * (sw if a == 'x' else sh)

                    # Perspective Transform Matrix calculation
                    dst = np.float32([
                        [(p('tl','x','start') + (p('tl','x','end')-p('tl','x','start'))*t), (p('tl','y','start') + (p('tl','y','end')-p('tl','y','start'))*t)],
                        [(p('tr','x','start') + (p('tr','x','end')-p('tr','x','start'))*t), (p('tr','y','start') + (p('tr','y','end')-p('tr','y','start'))*t)],
                        [(p('br','x','start') + (p('br','x','end')-p('br','x','start'))*t), (p('br','y','start') + (p('br','y','end')-p('br','y','start'))*t)],
                        [(p('bl','x','start') + (p('bl','x','end')-p('bl','x','start'))*t), (p('bl','y','start') + (p('bl','y','end')-p('bl','y','start'))*t)]
                    ])
                    src = np.float32([[0,0],[img.shape[1],0],[img.shape[1],img.shape[0]],[0,img.shape[0]]])

                    # Warp the image to the 4 corners and Blit to screen
                    mat = cv2.getPerspectiveTransform(src, dst)
                    proj = cv2.warpPerspective(proc, mat, (sw, sh))
                    rgb_proj = cv2.cvtColor(proj, cv2.COLOR_BGR2RGB)

                    surf = pygame.surfarray.make_surface(np.transpose(rgb_proj, (1, 0, 2)))
                    screen.blit(surf, (0, 0))
                    pygame.display.flip()
                    # Slight delay to prevent CPU pegging (VSYNC alignment)
                    time.sleep(cfg['VSYNC_PULL'])
                
            # Close Shutter: Clear to black and signal completion
            screen.fill((0,0,0))
            pygame.display.flip()
            trigger.clear()
    pygame.quit()
                    

                