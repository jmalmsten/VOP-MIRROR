"""
VOP Studio Orchestrator
Version: v0.0.1
Description: Final Studio Engine for tonight. Added Frame Counters and fixed f-strings.
"""
import os, time, cv2, numpy as np, pygame, subprocess, glob, csv, select, sys
from multiprocessing import Process, Event, Queue, Manager

# --- ALSA SILENCER ---
os.environ['SDL_AUDIODRIVER'] = 'dummy'

def load_config():
    defaults = {
        'SCREEN_WIDTH': 1920, 'SCREEN_HEIGHT': 1080,
        'BLACK_CLIP': 0.03, 'GAMMA': 1.0, 'GLOBAL_BRIGHTNESS': 1.0,
        'CAMERA_DEVICE': '/dev/video0', 'VSYNC_PULL': 0.01,
        'OUTPUT_FOLDER': 'vop_stills', 'PROJECTOR_FOLDER': 'Projector',
        'DEFAULT_DURATION': 0.5
    }
    if os.path.exists("config.txt"):
        with open("config.txt", "r") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    name, val = line.strip().split("=")
                    try: 
                        defaults[name] = float(val) if "." in val else int(val)
                    except: 
                        defaults[name] = val
    return defaults

def get_display_resolution(cfg_w, cfg_h):
    try:
        os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
        pygame.display.init()
        info = pygame.display.Info()
        res = (info.current_w, info.current_h)
        pygame.display.quit()
        return res, True if res[0] > 0 else False
    except:
        return (int(cfg_w), int(cfg_h)), False

def check_for_exit():
    """Checks if 'Enter' was pressed in the terminal without blocking."""
    i, o, e = select.select([sys.stdin], [], [], 0.0)
    for s in i:
        if s == sys.stdin:
            sys.stdin.readline() 
            return True
    return False

# --- GLOBAL INITIALIZATION ---
CFG = load_config()
SCREEN_RES, HANDSHAKE = get_display_resolution(CFG['SCREEN_WIDTH'], CFG['SCREEN_HEIGHT'])

def projector_worker(trigger_event, stop_event, config_queue, image_cache, live_cfg):
    os.environ["SDL_VIDEODRIVER"] = "kmsdrm"
    pygame.init()
    screen = pygame.display.set_mode(SCREEN_RES, pygame.FULLSCREEN | pygame.HWSURFACE | pygame.DOUBLEBUF)
    pygame.mouse.set_visible(False)
    sw, sh = SCREEN_RES
    
    while not stop_event.is_set():
        if trigger_event.wait(timeout=0.1):
            try: s = config_queue.get(block=False)
            except: continue
            
            if s.get('type') == 'test_pattern':
                img = np.zeros((sh, sw, 3), dtype=np.uint8)
                for x in range(10):
                    val = int((x / 9.0) * 255)
                    cv2.rectangle(img, (x*(sw//10), 0), ((x+1)*(sw//10), sh), (val, val, val), -1)
                screen.blit(pygame.surfarray.make_surface(np.transpose(img, (1, 0, 2))), (0,0))
                pygame.display.flip(); time.sleep(s.get('duration', 5))
            else:
                img_name = s.get('image')
                if img_name not in image_cache:
                    trigger_event.clear(); continue

                img = image_cache[img_name]
                src_pts = np.float32([[0, 0], [img.shape[1], 0], [img.shape[1], img.shape[0]], [0, img.shape[0]]])
                
                # Optical processing
                img_f = img.astype(np.float32) / 255.0
                bc = live_cfg['BLACK_CLIP']
                img_f = np.where(img_f < bc, 0.0, (img_f - bc) / (1.0 - bc))
                if live_cfg['GAMMA'] != 1.0: img_f = np.power(img_f, 1.0 / live_cfg['GAMMA'])
                
                gel_rgb = tuple(int(s.get('color_hex', '#FFFFFF').lstrip('#')[i:i+2], 16) for i in (0, 2, 4))
                gel_bgr = (np.array([gel_rgb[2], gel_rgb[1], gel_rgb[0]], dtype=np.float32) / 255.0) * live_cfg['GLOBAL_BRIGHTNESS']
                processed_img = np.clip(img_f * gel_bgr * 255.0, 0, 255).astype(np.uint8)

                duration = float(s.get('steps', 0.5)) 
                start_time = time.time()
                while (time.time() - start_time) < duration:
                    t = (time.time() - start_time) / duration
                    def get_p(c, a, st): return float(s[f'{c}_{a}_{st}']) * (sw if a == 'x' else sh)
                    
                    curr_pts = np.float32([
                        [(get_p('tl','x','start') + (get_p('tl','x','end') - get_p('tl','x','start')) * t), (get_p('tl','y','start') + (get_p('tl','y','end') - get_p('tl','y','start')) * t)],
                        [(get_p('tr','x','start') + (get_p('tr','x','end') - get_p('tr','x','start')) * t), (get_p('tr','y','start') + (get_p('tr','y','end') - get_p('tr','y','start')) * t)],
                        [(get_p('br','x','start') + (get_p('br','x','end') - get_p('br','x','start')) * t), (get_p('br','y','start') + (get_p('br','y','end') - get_p('br','y','start')) * t)],
                        [(get_p('bl','x','start') + (get_p('bl','x','end') - get_p('bl','x','start')) * t), (get_p('bl','y','start') + (get_p('bl','y','end') - get_p('bl','y','start')) * t)]
                    ])

                    matrix = cv2.getPerspectiveTransform(src_pts, curr_pts)
                    proj = cv2.warpPerspective(processed_img, matrix, SCREEN_RES)
                    screen.blit(pygame.surfarray.make_surface(np.transpose(cv2.cvtColor(proj, cv2.COLOR_BGR2RGB), (1, 0, 2))), (0, 0))
                    pygame.display.flip(); time.sleep(live_cfg['VSYNC_PULL'])

            screen.fill((0,0,0)); pygame.display.flip()
            trigger_event.clear()
    pygame.quit()

def capture_and_accumulate(scene, f_num, exp, foc, wb, is_snap=False):
    cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
    dev = CFG['CAMERA_DEVICE']
    subprocess.run(['v4l2-ctl', '-d', dev, '--set-ctrl=focus_automatic_continuous=0', '--set-ctrl=auto_exposure=1'], check=True)
    subprocess.run(['v4l2-ctl', '-d', dev, f'--set-ctrl=focus_absolute={foc}', f'--set-ctrl=exposure_time_absolute={exp}', f'--set-ctrl=white_balance_temperature={wb}'], check=True)
    time.sleep(0.5); [cap.read() for _ in range(5)]
    success, frame = cap.read(); cap.release()
    if not success: return None
    
    linear = np.power(frame.astype(np.float32) / 255.0, 2.2)
    out_dir = CFG['OUTPUT_FOLDER']
    if is_snap:
        out_name = f"SNAP_{int(time.time())}.tiff"
        cv2.imwrite(os.path.join(out_dir, out_name), (linear * 65535).astype(np.uint16))
        return out_name

    search = os.path.join(out_dir, f"{scene}_{f_num:03d}_exp*.tiff")
    existing = sorted(glob.glob(search))
    count = (int(existing[-1].split("_exp")[-1].split(".")[0]) + 1) if existing else 1
    if existing:
        prev = cv2.imread(existing[-1], cv2.IMREAD_UNCHANGED).astype(np.float32) / 65535.0
        linear = np.clip(prev + linear, 0, 1.0); os.remove(existing[-1])
    
    out_name = f"{scene}_{f_num:03d}_exp{count:03d}.tiff"
    cv2.imwrite(os.path.join(out_dir, out_name), (linear * 65535).astype(np.uint16))
    return out_name

if __name__ == "__main__":
    [os.makedirs(d) for d in [CFG['OUTPUT_FOLDER'], CFG['PROJECTOR_FOLDER']] if not os.path.exists(d)]
    manager = Manager(); shared_cache = manager.dict(); live_cfg = manager.dict()
    live_cfg.update(CFG)

    def update_cache():
        found = 0
        for f in os.listdir(CFG['PROJECTOR_FOLDER']):
            if f.lower().endswith(('.png', '.jpg', '.tiff')):
                img = cv2.imread(os.path.join(CFG['PROJECTOR_FOLDER'], f))
                if img is not None: shared_cache[f] = img; found += 1
        print(f"RAM Cache: {found} images loaded.")

    update_cache()
    trigger, stop, configs = Event(), Event(), Queue()
    p_proc = Process(target=projector_worker, args=(trigger, stop, configs, shared_cache, live_cfg)); p_proc.start()

    print(f"\nVOP Studio Online | Res: {SCREEN_RES[0]}x{SCREEN_RES[1]} | Type 'help' for commands")
    
    try:
        while True:
            cmd_input = input(f"\nVOP Studio > ")
            cmd = cmd_input.split()
            if not cmd: continue
            action = cmd[0].lower()
            target_csv = cmd[1] if len(cmd) > 1 else "x-sheet_filled.csv"
            
            if action == 'q': break
            elif action == 'help': print("\ndry, run, snap, test [sec], status, reload, q")
            elif action == 'status': print(f"Cache: {list(shared_cache.keys())}\nOptical: Clip={live_cfg['BLACK_CLIP']}, Gamma={live_cfg['GAMMA']}")
            elif action == 'reload':
                live_cfg.update(load_config()); update_cache(); print("Reloaded.")
            elif action == 'test':
                configs.put({'type': 'test_pattern', 'duration': int(cmd[1]) if len(cmd)>1 else 10}); trigger.set()
            elif action == 'snap':
                if not os.path.exists(target_csv): continue
                with open(target_csv, 'r') as f:
                    row = next(csv.DictReader(f))
                    configs.put(row); trigger.set()
                    print(f"Snap saved.")
            elif action in ['run', 'dry']:
                if not os.path.exists(target_csv): continue
                print(f"Starting {action} run... [HIT ENTER TO STOP]")
                is_looping = True
                while is_looping:
                    with open(target_csv, 'r') as f:
                        for row in csv.DictReader(f):
                            if check_for_exit():
                                is_looping = False; break
                            print(f"\r Processing Frame: {row['frame']} ", end="", flush=True)
                            configs.put(row); trigger.set()
                            while trigger.is_set(): time.sleep(0.01)
                            if action == 'run':
                                capture_and_accumulate("scene01", int(row['frame']), row['exposure'], row['focus'], row['wb'])
                    if action == 'run': is_looping = False
                print(f"\n{action.capitalize()} halted.")
    finally:
        stop.set(); p_proc.terminate(); p_proc.join()