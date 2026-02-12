"""
VOP Module:     interpolator.py
Version:        v0.1.6
Description:    Added 'stp' (Step) track for Optical Printer logic.
"""
import numpy as np

def hex_to_rgb(h):
    h = h.lstrip('#')
    return np.array([int(h[i:i+2], 16)/255.0 for i in (0, 2, 4)])

def lerp(a, b, t): return a + (b - a) * t

def ease_smooth(t): 
    ts = max(0, min(1, t))
    return ts * ts * (3 - 2 * ts)
def ease_in(t):
    ts = max(0, min(1, t))
    return ts * ts
def ease_out(t):
    ts = max(0, min(1, t))
    return 1 - (1 - ts) * (1 - ts)

def catmull_rom(p0, p1, p2, p3, t):
    t2 = t * t; t3 = t2 * t
    return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)

class Timeline:
    def __init__(self, data):
        self.tracks = {
            'p': [], 'r': [], 'c': [], 'cg': [], 
            's': [], 'sd': [], 'ph': [], 'stp': []
        }
        
        parsers = {
            'p': lambda x: np.array([float(n) for n in x.split(',')]),
            'r': lambda x: np.array([float(n) for n in x.split(',')]) * 360.0,
            'c': lambda x: hex_to_rgb(x),
            'cg': lambda x: hex_to_rgb(x),
            's': float, 'sd': float, 'ph': float, 
            'stp': float # Step/Speed of Source
        }

        found_indices = set()
        for k in data.keys():
            if k.startswith('f') and k[1:].isdigit():
                found_indices.add(k[1:])
        
        for idx in found_indices:
            frame_str = str(data.get(f'f{idx}', '')).strip()
            if not frame_str: continue 
            
            frame = int(frame_str)
            mode = data.get(f'm{idx}', 'S')
            crn = (str(data.get(f'crn{idx}', '')).lower() == 'true')

            for key_type, parser in parsers.items():
                lookup_key = f"{key_type}{idx}_hex" if key_type in ['c', 'cg'] else f"{key_type}{idx}"
                raw_val = str(data.get(lookup_key, '')).strip()
                if raw_val:
                    try:
                        val = parser(raw_val)
                        self.tracks[key_type].append({'f': frame, 'val': val, 'mode': mode, 'crn': crn})
                    except: pass

        for k in self.tracks:
            self.tracks[k].sort(key=lambda x: x['f'])
            if not self.tracks[k]:
                defaults = {
                    'p': np.array([0.,0.,-10.]), 'r': np.array([0.,0.,0.]),
                    'c': np.array([1.,1.,1.]), 'cg': np.array([1.,1.,1.]),
                    's': 1.0, 'sd': 1.0, 'ph': 0.5, 'stp': 1.0
                }
                self.tracks[k].append({'f': 1, 'val': defaults[k], 'mode': 'S', 'crn': False})

    def _get_val_at_t(self, track_name, frame_float, is_spatial=False):
        track = self.tracks[track_name]
        if frame_float <= track[0]['f']: return track[0]['val']
        if frame_float >= track[-1]['f']: return track[-1]['val']
        
        idx = 0
        while idx < len(track) - 1 and frame_float > track[idx+1]['f']: idx += 1
        
        kA, kB = track[idx], track[idx+1]
        seg_len = float(kB['f'] - kA['f'])
        if seg_len == 0: return kA['val']
        t = (frame_float - kA['f']) / seg_len

        mode = kA['mode']
        t_e = ease_in(t) if mode == 'I' else ease_out(t) if mode == 'O' else t if mode == 'L' else ease_smooth(t)

        if is_spatial:
            p1, p2 = kA['val'], kB['val']
            kPrev = track[idx-1] if idx > 0 else None
            p0 = p1 + (p1 - p2) if kA['crn'] else kPrev['val'] if kPrev else p1 - (p2 - p1)
            
            kNext = track[idx+2] if idx < len(track) - 2 else None
            p3 = p2 + (p2 - p1) if kB['crn'] else kNext['val'] if kNext else p2 + (p2 - p1)
            
            return catmull_rom(p0, p1, p2, p3, t_e)
        else:
            return lerp(kA['val'], kB['val'], t_e)

    def get_state(self, frame_float):
        return {
            'p': self._get_val_at_t('p', frame_float, is_spatial=True),
            'r': self._get_val_at_t('r', frame_float),
            'c': self._get_val_at_t('c', frame_float),
            'cg': self._get_val_at_t('cg', frame_float),
            's': self._get_val_at_t('s', frame_float),
            'sd': self._get_val_at_t('sd', frame_float),
            'ph': self._get_val_at_t('ph', frame_float),
            'stp': self._get_val_at_t('stp', frame_float)
        }