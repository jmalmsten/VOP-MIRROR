"""
VOP Studio v0.1.3 - The Cerebrum
Orchestrates the CLI, RAM Cache, and Hardware Subprocesses.
"""
import os, time, cv2, subprocess
from modules import config_engine, xsheet_engine, projector_hw, camera_hw
from multiprocessing import Event, Queue, Manager, Process

# Global Setup from Config
CFG = config_engine.load_config()
RES, HANDSHAKE = config_engine.get_display_res(CFG)

def main():
    print(f"\n--- VOP Studio v0.1.0 | Optical Lab ---")
    print(f"\nHandshake: {RES[0]}x{RES[1]} ({'OK' if HANDSHAKE else 'FALLBACK'})")

    # Ensure all 4 Magazines are ready
    mags = [CFG['PROJ_MAG'], CFG['PROJ_BIPACK'], CFG['CAM_MAG'], CFG['CAM_BIPACK']]
    for d in mags:
        if not os.path.exists(d): os.makedirs(d)
    
    # Setup Shared Memory for Multiprocessing
    m = Manager()
    cache = m.dict()        # ProjMag Cache
    bp_cache = m.dict()     # ProjBiPack Cache
    live_cfg = m.dict()     #
    live_cfg.update(CFG)    #

    def refresh():
        """
        Clears and reloads Projector RAM from the Mags.
        """

        cache.clear()
        bp_cache.clear()

        # Load Main Slides
        for f in os.listdir(CFG['PROJ_MAG']):
            if f.lower().endswith(('.png', '.jpg', '.tiff')):
                img = cv2.imread(os.path.join(CFG['PROJ_MAG'], f))
                if img is not None: cache[f] = img
        # Load Projector BiPackMattes
        for f in os.listdir(CFG['PROJ_BIPACK']):
            if f.lower().endswith(('.png', '.jpg', '.tiff')):
                img = cv2.imread(os.path.join(CFG['PROJ_BIPACK'], f))
                if img is not None: bp_cache[f] = img
        print(f"RAM Loaded: {len(cache)} Slides, {len(bp_cache)} Mattes.")
    
    refresh()

    # Inter-Process Communication
    trigger = Event()
    stop = Event()
    configs = Queue()

    # Launch Projector Process
    p = Process(target=projector_hw.worker, args=(trigger, stop, configs, cache, bp_cache, live_cfg, RES))
    p.start()

    sheet = None
    try: 
        while True:
            # CLI Input
            cmd = input("\nVOP > ").split()
            if not cmd: continue
            action = cmd[0].lower()

            if action == 'q':
                break
            
            elif action == 'reload':
                live_cfg.update(config_engine.load_config())
                refresh()
            
            elif action == 'xsheet':
                sheet = xsheet_engine.XSheet(cmd[1] if len(cmd)>1 else "x-sheet.csv", CFG['DEFAULT_DURATION'])
                print(f"Loaded {sheet.get_total_frames()} frames.")

            elif action in ['dry', 'run']:
                if not sheet: 
                    print("Error: Load Xsheet first!")
                    continue
                # Force resolution ONCE at startup
                try:
                    subprocess.run(['v4l2-ctl', '-d', '/dev/video0', 
                                    '--set-fmt-video=width=1920,height=1080,pixelformat=MJPG'], check=True)
                
                except Exception as e:
                    print(f"Warning: Could not set camera resolution: {e}")

                print(f"Starting {action}... [HIT ENTER TO STOP]")
            
                active = True
                while active:
                    total_f = sheet.get_total_frames()
                    for f in range(1, total_f + 1):
                        if config_engine.check_for_exit():
                            active = False; break
                        
                        # Get interpolated data and send to Projector
                        data = sheet.get_frame_data(f)
                        print(f"\r Processing Frame: {f}/{total_f}", end="", flush=True)
                        configs.put(data)
                        trigger.set()

                        # Wait for Shutter Smear to finish
                        while trigger.is_set():
                            time.sleep(0.01)
                        
                        # SYNC DELAY
                        # The projector process has the data, but the HDMI/Projector bulb
                        # needs a moment to actually show it. .2s is a safe starting point.
                        time.sleep(0.5)
                

                        # Trigger Camera pass in in Run Mode
                        if action == 'run':
                            camera_hw.capture_and_accumulate("scene01", f, data['image'], data['exposure'], data['focus'], data['wb'], live_cfg)
                    
                    if action == 'run': active = False # Production is one-shot; Dry loops

            elif action == 'test':
                configs.put({'type': 'test_pattern', 'duration': int(cmd[1]) if len(cmd)>1 else 5})
                trigger.set()
    finally:
        # Graceful shudown of hardware processes
        stop.set()
        p.terminate()
        p.join()
        print("\nVOP Studio Powered Down.")

if __name__ == "__main__":
    main()