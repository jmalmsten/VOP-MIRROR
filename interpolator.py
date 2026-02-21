"""
VOP Module:     interpolator.py
Version:        v0.1.10
Description:    Timeline state evaluation and interpolation mathematics.
"""
import numpy as np

def hex_to_rgb(h):
    """
    Converts a standard HTML hex color string (e.g. #FF0000) to a normalized numpy array [1.0, 0.0, 0.0].
    """
    h = h.lstrip('#')
    return np.array([int(h[i:i+2], 16)/255.0 for i in (0, 2, 4)])

def ensure_vec3(arr, default_val=0.0):
    """
    Validation function to ensure spatial coordinates are strictly 3-component arrays.
    Prevents runtime crashes if the user inputs incomplete coordinates like '0,0' instead of '0,0,-1'.
    """
    arr = np.array(arr, dtype=float)
    if arr.ndim != 1: 
        return np.array([default_val]*3)
    # Pad with default values if there are too few elements.
    if arr.shape[0] < 3: 
        return np.pad(arr, (0, 3 - arr.shape[0]), 'constant', constant_values=default_val)
    # Truncate if there are too many elements.
    if arr.shape[0] > 3: 
        return arr[:3]
    return arr

# Mathematical interpolation algorithms:
# Linear Interpolation. Finds the exact midpoint based on percentage t.
def lerp(a, b, t): return a + (b - a) * t

# Smoothstep easing (accelerates then decelerates).
def ease_smooth(t): 
    ts = max(0, min(1, t))
    return ts * ts * (3 - 2 * ts)

# Ease-in (accelerates from rest).
def ease_in(t): 
    ts = max(0, min(1, t))
    return ts * ts

# Ease-out (decelerates to rest).
def ease_out(t): 
    ts = max(0, min(1, t))
    return 1 - (1 - ts) * (1 - ts)

def catmull_rom(p0, p1, p2, p3, t):
    """
    Calculates the spatial coordinates along a Catmull-Rom spline.
    This provides smooth, curved 3D motion paths that pass exactly through the keyframes,
    unlike bezier curves which only use points as distant attractors.
    """
    t2 = t * t
    t3 = t2 * t
    return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)

class Timeline:
    """
    Parses the JSON job data and builds the keyframe tracks.
    """
    def __init__(self, data):
        # Initialize an empty list for each distinct animatable property.
        self.tracks = {
            'p': [], 'r': [], 'c': [], 'cg': [], 
            's': [], 'sd': [], 'ph': [], 'stp': [], 'src': []
        }
        
        # Dictionary of lambda functions used to parse the string values from JSON into strictly typed variables.
        parsers = {
            'p':   lambda x: ensure_vec3([float(n) for n in x.split(',') if n.strip()], 0.0),
            'r':   lambda x: ensure_vec3([float(n) for n in x.split(',') if n.strip()], 0.0) * 360.0,
            'c':   lambda x: hex_to_rgb(x),
            'cg':  lambda x: hex_to_rgb(x),
            's': float, 'sd': float, 'ph': float, 'stp': float, 'src': float
        }

        # Identify all unique frame indices present in the JSON by looking for keys matching 'f1', 'f2', etc.
        found_indices = set()
        for k in data.keys():
            if k.startswith('f') and k[1:].isdigit():
                found_indices.add(k[1:])
        
        # Iterate over the discovered indices and populate the corresponding tracks.
        for idx in found_indices:
            frame_str = str(data.get(f'f{idx}', '')).strip()
            if not frame_str: continue 
            
            frame = int(frame_str)
            mode = data.get(f'm{idx}', 'S')
            crn = (str(data.get(f'crn{idx}', '')).lower() == 'true')

            # Extract the raw value string for every property at this keyframe index.
            for key_type, parser in parsers.items():
                lookup_key = f"{key_type}{idx}_hex" if key_type in ['c', 'cg'] else f"{key_type}{idx}"
                raw_val = str(data.get(lookup_key, '')).strip()
                if raw_val:
                    try:
                        # Append the parsed value alongside its frame number and interpolation modes.
                        val = parser(raw_val)
                        self.tracks[key_type].append({'f': frame, 'val': val, 'mode': mode, 'crn': crn})
                    except: pass

        # Sort the tracks sequentially by frame number and provide sensible defaults if a track is completely empty.
        for k in self.tracks:
            self.tracks[k].sort(key=lambda x: x['f'])
            if not self.tracks[k]:
                defaults = {
                    'p': np.array([0.,0.,-10.]), 'r': np.array([0.,0.,0.]),
                    'c': np.array([1.,1.,1.]), 'cg': np.array([1.,1.,1.]),
                    's': 1.0, 'sd': 1.0, 'ph': 0.5, 'stp': 1.0, 'src': -1.0
                }
                self.tracks[k].append({'f': 1, 'val': defaults[k], 'mode': 'S', 'crn': False})

    def _get_val_at_t(self, track_name, frame_float, is_spatial=False):
        """
        Evaluates the specific state of a property at an exact sub-frame.
        """
        track = self.tracks[track_name]
        if not track: return 0
        
        # Clamp bounds. If the playhead is before the first keyframe, return the first value.
        if frame_float <= track[0]['f']: return track[0]['val']
        # If the playhead is past the last keyframe, return the last value.
        if frame_float >= track[-1]['f']: return track[-1]['val']
        
        # Find the two keyframes (kA and kB) that the playhead is currently passing between.
        idx = 0
        while idx < len(track) - 1 and frame_float > track[idx+1]['f']: idx += 1
        
        kA, kB = track[idx], track[idx+1]
        
        # Calculate the normalized time 't' (0.0 to 1.0) between keyframe A and B.
        seg_len = float(kB['f'] - kA['f'])
        if seg_len == 0: return kA['val']
        t = (frame_float - kA['f']) / seg_len

        # Pass 't' through the easing functions based on the user's selected interpolation mode.
        mode = kA['mode']
        t_e = ease_in(t) if mode == 'I' else ease_out(t) if mode == 'O' else t if mode == 'L' else ease_smooth(t)

        if is_spatial:
            # Spatial parameters use Catmull-Rom. This requires four control points:
            # The previous key, the start key, the end key, and the next key.
            p1, p2 = kA['val'], kB['val']
            if p1.shape != (3,): p1 = ensure_vec3(p1)
            if p2.shape != (3,): p2 = ensure_vec3(p2)
            
            kPrev = track[idx-1] if idx > 0 else None
            # If the user sets 'Corner' (CRN), we extrapolate linearly to create a sharp turn,
            # otherwise we use the actual previous keyframe.
            p0 = p1 + (p1 - p2) if kA['crn'] else (kPrev['val'] if kPrev else p1 - (p2 - p1))
            
            kNext = track[idx+2] if idx < len(track) - 2 else None
            p3 = p2 + (p2 - p1) if kB['crn'] else (kNext['val'] if kNext else p2 + (p2 - p1))
            
            return catmull_rom(p0, p1, p2, p3, t_e)
        else:
            # Scalar and color parameters use simple linear interpolation.
            return lerp(kA['val'], kB['val'], t_e)

    def get_state(self, frame_float):
        """
        Constructs the entire parameter state payload for a specific point in time.
        """
        return {
            'p': self._get_val_at_t('p', frame_float, is_spatial=True),
            'r': self._get_val_at_t('r', frame_float),
            'c': self._get_val_at_t('c', frame_float),
            'cg': self._get_val_at_t('cg', frame_float),
            's': self._get_val_at_t('s', frame_float),
            'sd': self._get_val_at_t('sd', frame_float),
            'ph': self._get_val_at_t('ph', frame_float),
            'stp': self._get_val_at_t('stp', frame_float),
            'src': self._get_val_at_t('src', frame_float)
        }

    def calculate_playhead_at(self, target_frame):
        """
        Implements the 'Dumb Stepper' logic requested by the user.
        Calculates the source frame index by finding the last explicit anchor and integrating steps.
        """
        src_track = self.tracks['src']
        anchor_val = 0.0
        anchor_frame = 1
        
        # 1. Iterate backwards through the Source Anchor track to find the most recent
        # keyframe that has an explicit value set (not -1).
        best_k = None
        for k in reversed(src_track):
            if k['f'] <= target_frame and k['val'] >= 0:
                best_k = k
                break
        
        if best_k:
            anchor_val = best_k['val']
            anchor_frame = best_k['f']
        else:
            anchor_val = 0.0 
            anchor_frame = 1
            
        current_playhead = anchor_val
        
        # 2. Integrate the Step Values
        # From the frame *after* the anchor up to the target frame, add the step value.
        # This operates discretely, mimicking a mechanical optical printer advancing 1 frame per exposure.
        if target_frame > anchor_frame:
            for f in range(int(anchor_frame), int(target_frame)):
                step = self._get_val_at_t('stp', float(f))
                current_playhead += step
                
        return current_playhead
