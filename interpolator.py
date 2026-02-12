"""
VOP Module:     interpolator.py
Version:        v0.1.5
Description:    Independent Track Interpolation. Allows bridging gaps per parameter.
"""
import numpy as np

def hex_to_rgb(h):
    h = h.lstrip('#')
    return np.array([int(h[i:i+2], 16)/255.0 for i in (0, 2, 4)])

def lerp(a, b, t): return a + (b - a) * t

# --- Easing Functions ---
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
        # We now store independent tracks
        # Each track is a list of dicts: {'f': frame, 'val': value, 'mode': easing, 'crn': corner_bool}
        self.tracks = {
            'p': [], 'r': [], 'c': [], 'cg': [], 
            's': [], 'sd': [], 'ph': []
        }
        
        # Parsers for each data type
        parsers = {
            'p': lambda x: np.array([float(n) for n in x.split(',')]),
            'r': lambda x: np.array([float(n) for n in x.split(',')]) * 360.0, # 0-1 range to degrees
            'c': lambda x: hex_to_rgb(x),
            'cg': lambda x: hex_to_rgb(x),
            's': float,
            'sd': float,
            'ph': float
        }

        # 1. Scan all input keys to find Frame Numbers
        # We need to iterate the JSON keys to find any f1, f2, f99...
        found_indices = set()
        for k in data.keys():
            if k.startswith('f') and k[1:].isdigit():
                found_indices.add(k[1:])
        
        # 2. Build Tracks
        for idx in found_indices:
            frame_str = str(data.get(f'f{idx}', '')).strip()
            if not frame_str: continue # Skip if frame number is missing
            
            frame = int(frame_str)
            mode = data.get(f'm{idx}', 'S')
            crn = (str(data.get(f'crn{idx}', '')).lower() == 'true')

            # Check each parameter type
            for key_type, parser in parsers.items():
                # Handle special hex naming for colors
                lookup_key = f"{key_type}{idx}_hex" if key_type in ['c', 'cg'] else f"{key_type}{idx}"
                
                raw_val = str(data.get(lookup_key, '')).strip()
                if raw_val:
                    try:
                        val = parser(raw_val)
                        self.tracks[key_type].append({
                            'f': frame,
                            'val': val,
                            'mode': mode,
                            'crn': crn
                        })
                    except: pass # Ignore parse errors

        # 3. Sort all tracks
        for k in self.tracks:
            self.tracks[k].sort(key=lambda x: x['f'])
            
            # If track is empty, inject a default 0-key to prevent crashes
            if not self.tracks[k]:
                defaults = {
                    'p': np.array([0.,0.,-10.]), 'r': np.array([0.,0.,0.]),
                    'c': np.array([1.,1.,1.]), 'cg': np.array([1.,1.,1.]),
                    's': 1.0, 'sd': 1.0, 'ph': 0.5
                }
                self.tracks[k].append({'f': 1, 'val': defaults[k], 'mode': 'S', 'crn': False})

    def _get_val_at_t(self, track_name, frame_float, is_spatial=False):
        track = self.tracks[track_name]
        
        # Case 1: Before first key -> Clamp to first
        if frame_float <= track[0]['f']: return track[0]['val']
        
        # Case 2: After last key -> Clamp to last
        if frame_float >= track[-1]['f']: return track[-1]['val']
        
        # Case 3: Between keys
        idx = 0
        while idx < len(track) - 1 and frame_float > track[idx+1]['f']:
            idx += 1
        
        kA = track[idx]
        kB = track[idx+1]
        
        seg_len = float(kB['f'] - kA['f'])
        if seg_len == 0: return kA['val']
        t = (frame_float - kA['f']) / seg_len

        # Easing
        mode = kA['mode']
        if mode == 'I': t_e = ease_in(t)
        elif mode == 'O': t_e = ease_out(t)
        elif mode == 'L': t_e = t
        else: t_e = ease_smooth(t)

        if is_spatial:
            # Catmull-Rom requires 4 points from THIS specific track
            p1, p2 = kA['val'], kB['val']
            
            # Find P0
            if idx > 0:
                kPrev = track[idx-1]
                p0 = p1 + (p1 - p2) if kA['crn'] else kPrev['val']
            else: p0 = p1 - (p2 - p1)

            # Find P3
            if idx < len(track) - 2:
                kNext = track[idx+2]
                p3 = p2 + (p2 - p1) if kB['crn'] else kNext['val']
            else: p3 = p2 + (p2 - p1)
            
            return catmull_rom(p0, p1, p2, p3, t_e)
        else:
            return lerp(kA['val'], kB['val'], t_e)

    def get_state(self, frame_float):
        return {
            'p': self._get_val_at_t('p', frame_float, is_spatial=True),
            'r': self._get_val_at_t('r', frame_float),
            'c': self._get_val_at_t('c', frame_float), # Colors could be spatial? sticking to linear for now
            'cg': self._get_val_at_t('cg', frame_float),
            's': self._get_val_at_t('s', frame_float),
            'sd': self._get_val_at_t('sd', frame_float),
            'ph': self._get_val_at_t('ph', frame_float)
        }