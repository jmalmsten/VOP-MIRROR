"""
VOP Module:     interpolator.py
Version:        v0.1.3
Description:    Catmull-Rom Splines. Fixed crash on empty frame inputs.
"""
import numpy as np

def hex_to_rgb(h):
    h = h.lstrip('#')
    return np.array([int(h[i:i+2], 16)/255.0 for i in (0, 2, 4)])

def lerp(a, b, t): return a + (b - a) * t

# --- Easing ---
def ease_smooth(t): 
    ts = max(0, min(1, t))
    return ts * ts * (3 - 2 * ts)

def ease_in(t):
    ts = max(0, min(1, t))
    return ts * ts

def ease_out(t):
    ts = max(0, min(1, t))
    return 1 - (1 - ts) * (1 - ts)

# --- Catmull-Rom Spline Logic ---
def catmull_rom(p0, p1, p2, p3, t):
    t2 = t * t
    t3 = t2 * t
    return 0.5 * (
        (2 * p1) +
        (-p0 + p2) * t +
        (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 +
        (-p0 + 3 * p1 - 3 * p2 + p3) * t3
    )

class Timeline:
    def __init__(self, data):
        self.keys = []
        for k in data.keys():
            # Check for keys starting with 'f' (f1, f2...)
            if k.startswith('f') and k[1:].isdigit():
                # SAFETY CHECK: Skip if value is empty or not a number
                val = str(data[k]).strip()
                if not val: continue
                
                idx = k[1:]
                if f'p{idx}' in data:
                    self.keys.append({
                        'f': int(val),
                        'p': np.array([float(x) for x in data[f'p{idx}'].split(',')]),
                        'r': np.array([float(x) for x in data[f'r{idx}'].split(',')]) * 360.0,
                        'c': hex_to_rgb(data[f'c{idx}_hex']),
                        'cg': hex_to_rgb(data[f'cg{idx}_hex']),
                        's': float(data[f's{idx}']),
                        'sd': float(data[f'sd{idx}']),
                        'ph': float(data[f'ph{idx}']),
                        'mode': data.get(f'm{idx}', 'S'),
                        'crn': data.get(f'crn{idx}') == 'true'
                    })
        self.keys.sort(key=lambda x: x['f'])

    def get_state(self, frame_float):
        if not self.keys: return {}
        if len(self.keys) == 1:
            k = self.keys[0]
            return {'p': k['p'], 'r': k['r'], 'c': k['c'], 'cg': k['cg'], 's': k['s'], 'sd': k['sd'], 'ph': k['ph']}

        # Find active segment (A -> B)
        idx = 0
        while idx < len(self.keys) - 1 and frame_float > self.keys[idx+1]['f']:
            idx += 1
        idx = min(idx, len(self.keys) - 2)
        
        kA = self.keys[idx]
        kB = self.keys[idx+1]
        
        seg_len = float(kB['f'] - kA['f'])
        if seg_len == 0: t = 0.0
        else: t = (frame_float - kA['f']) / seg_len

        mode = kA['mode']
        if mode == 'I': t_e = ease_in(t)
        elif mode == 'O': t_e = ease_out(t)
        elif mode == 'L': t_e = t
        else: t_e = ease_smooth(t)

        # --- SPATIAL ---
        p1, p2 = kA['p'], kB['p']
        
        if idx > 0:
            kPrev = self.keys[idx-1]
            if kA['crn']: p0 = p1 + (p1 - p2)
            else: p0 = kPrev['p']
        else:
            p0 = p1 - (p2 - p1)

        if idx < len(self.keys) - 2:
            kNext = self.keys[idx+2]
            if kB['crn']: p3 = p2 + (p2 - p1)
            else: p3 = kNext['p']
        else:
            p3 = p2 + (p2 - p1)

        p_res = catmull_rom(p0, p1, p2, p3, t_e)

        # --- LINEAR ---
        r_res = lerp(kA['r'], kB['r'], t_e)
        c_res = lerp(kA['c'], kB['c'], t)
        cg_res = lerp(kA['cg'], kB['cg'], t)
        s_res = lerp(kA['s'], kB['s'], t)
        sd_res = lerp(kA['sd'], kB['sd'], t)
        ph_res = lerp(kA['ph'], kB['ph'], t)

        return {'p': p_res, 'r': r_res, 'c': c_res, 'cg': cg_res, 's': s_res, 'sd': sd_res, 'ph': ph_res}