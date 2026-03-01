"""
VOP Module:     interpolator.py
Version:        v0.1.11
Description:    Timeline state evaluation and interpolation mathematics.
                This reads the exposure sheet and calculates where things should be on frames in-between keys.
"""
import numpy as np

def hex_to_rgb(h):
    """
    Converts a standard HTML hex color string (e.g. #FF0000) from the UI
    into a normalized numpy float array [1.0, 0.0, 0.0] for the math operations.
    """
    h = h.lstrip('#')
    return np.array([int(h[i:i+2], 16)/255.0 for i in (0, 2, 4)])

def ensure_vec3(arr, default_val=0.0):
    """
    Sanity check for 3D coordinates. If a user accidentally types "0,0" into the POS field
    instead of "0,0,-1", this function intercepts it and pads the array with a default value
    so the 3D matrix math doesn't crash from missing axes.
    """
    arr = np.array(arr, dtype=float)
    if arr.ndim != 1: return np.array([default_val]*3)
    if arr.shape[0] < 3: return np.pad(arr, (0, 3 - arr.shape[0]), 'constant', constant_values=default_val)
    if arr.shape[0] > 3: return arr[:3]
    return arr

# --- INTERPOLATION MATHEMATICS ---
# 't' is always a normalized percentage between 0.0 (start) and 1.0 (end).

# Linear Interpolation (Constant Speed)
def lerp(a, b, t): return a + (b - a) * t

# Smoothstep (Accelerates slowly, cruises, then decelerates to a stop)
def ease_smooth(t): 
    ts = max(0, min(1, t))
    return ts * ts * (3 - 2 * ts)

# Ease In (Starts slow, hits max speed at the end)
def ease_in(t): 
    ts = max(0, min(1, t))
    return ts * ts

# Ease Out (Starts fast, gently coasts to a stop)
def ease_out(t): 
    ts = max(0, min(1, t))
    return 1 - (1 - ts) * (1 - ts)

def catmull_rom(p0, p1, p2, p3, t):
    """
    Calculates the spatial coordinates along a Catmull-Rom spline.
    Unlike standard Bezier curves (where control points just 'pull' the line), 
    Catmull-Rom guarantees that the curve physically passes exactly through every keyframe.
    Requires 4 points to calculate curvature: the previous key, start key, end key, and next key.
    """
    t2 = t * t
    t3 = t2 * t
    return 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3)

class Timeline:
    """
    Reads the raw JSON dictionary and structures it into traversable animation tracks.
    """
    def __init__(self, data):
        # Create an empty list for every animatable parameter.
        self.tracks = {
            'p': [], 'r': [], 'c': [], 'cg': [], 
            's': [], 'sd': [], 'ph': [], 'stp': [], 'src': []
        }
        
        # A dictionary of lambda functions. This maps our parameter keys to the functions 
        # required to safely convert their raw strings into mathematical objects.
        parsers = {
            'p':   lambda x: ensure_vec3([float(n) for n in x.split(',') if n.strip()], 0.0),
            'r':   lambda x: ensure_vec3([float(n) for n in x.split(',') if n.strip()], 0.0) * 360.0,
            'c':   lambda x: hex_to_rgb(x),
            'cg':  lambda x: hex_to_rgb(x),
            's': float, 'sd': float, 'ph': float, 'stp': float, 'src': float
        }

        # Scan the JSON keys for anything that looks like 'f1', 'f20', etc., 
        # to determine which keyframe numbers actually exist in the payload.
        found_indices = set()
        for k in data.keys():
            if k.startswith('f') and k[1:].isdigit():
                found_indices.add(k[1:])
        
        # Iterate through our discovered keyframes.
        for idx in found_indices:
            frame_str = str(data.get(f'f{idx}', '')).strip()
            if not frame_str: continue 
            
            frame = int(frame_str)
            # Retrieve the interpolation mode (S, L, I, O)
            mode = data.get(f'm{idx}', 'S')
            # Check if the 'Corner' flag is checked for sharp path turns.
            crn = (str(data.get(f'crn{idx}', '')).lower() == 'true')

            # Populate the tracks
            for key_type, parser in parsers.items():
                # Color keys have '_hex' appended in the HTML ID, so we account for that here.
                lookup_key = f"{key_type}{idx}_hex" if key_type in ['c', 'cg'] else f"{key_type}{idx}"
                raw_val = str(data.get(lookup_key, '')).strip()
                if raw_val:
                    try:
                        # Parse the value and append the dictionary to the specific track list.
                        val = parser(raw_val)
                        self.tracks[key_type].append({'f': frame, 'val': val, 'mode': mode, 'crn': crn})
                    except: pass

        # Crucial Cleanup: Sort all tracks chronologically by frame number.
        for k in self.tracks:
            self.tracks[k].sort(key=lambda x: x['f'])
            
            # If the user left an entire track blank, inject a safe default at Frame 1 
            # so the engine doesn't crash when it asks for a value.
            if not self.tracks[k]:
                defaults = {
                    'p': np.array([0.,0.,-10.]), 'r': np.array([0.,0.,0.]),
                    'c': np.array([1.,1.,1.]), 'cg': np.array([1.,1.,1.]),
                    's': 1.0, 'sd': 1.0, 'ph': 0.5, 'stp': 1.0, 'src': -1.0
                }
                self.tracks[k].append({'f': 1, 'val': defaults[k], 'mode': 'S', 'crn': False})

    def _get_val_at_t(self, track_name, frame_float, is_spatial=False):
        """
        The core interpolation engine. Given a track and a precise moment in time,
        it calculates the exact value required.
        """
        track = self.tracks[track_name]
        if not track: return 0
        
        # Clamping: If asking for a frame before the start or after the end, just return the extreme limits.
        if frame_float <= track[0]['f']: return track[0]['val']
        if frame_float >= track[-1]['f']: return track[-1]['val']
        
        # Iterate through the track to find the two keyframes surrounding the playhead.
        idx = 0
        while idx < len(track) - 1 and frame_float > track[idx+1]['f']: idx += 1
        
        kA, kB = track[idx], track[idx+1]
        
        # Calculate 't' (the percentage of completion between Key A and Key B)
        seg_len = float(kB['f'] - kA['f'])
        if seg_len == 0: return kA['val']
        t = (frame_float - kA['f']) / seg_len

        # Pass 't' through the easing math determined by the UI dropdown mode.
        mode = kA['mode']
        t_e = ease_in(t) if mode == 'I' else ease_out(t) if mode == 'O' else t if mode == 'L' else ease_smooth(t)

        if is_spatial:
            # Spatial tracks require the Catmull-Rom logic.
            p1, p2 = kA['val'], kB['val']
            # Re-verify the array shapes just in case.
            if p1.shape != (3,): p1 = ensure_vec3(p1)
            if p2.shape != (3,): p2 = ensure_vec3(p2)
            
            kPrev = track[idx-1] if idx > 0 else None
            # If 'Corner' is checked, we deliberately break the Catmull-Rom curve by mirroring 
            # the points linearly, resulting in a sharp angle at the keyframe.
            p0 = p1 + (p1 - p2) if kA['crn'] else (kPrev['val'] if kPrev else p1 - (p2 - p1))
            
            kNext = track[idx+2] if idx < len(track) - 2 else None
            p3 = p2 + (p2 - p1) if kB['crn'] else (kNext['val'] if kNext else p2 + (p2 - p1))
            
            return catmull_rom(p0, p1, p2, p3, t_e)
        else:
            # Non-spatial tracks (like Exposure or Step) just use straight linear mixing.
            return lerp(kA['val'], kB['val'], t_e)

    def get_state(self, frame_float):
        """
        Gathers all track evaluations into a single payload dictionary for a specific frame.
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
        The 'Dumb Stepper' algorithm.
        This calculates which frame from the ProjMag folder should be loaded, based on 
        the explicit SRC anchors and the cumulative STP (Step) values.
        """
        src_track = self.tracks['src']
        anchor_val = 0.0
        anchor_frame = 1
        
        # 1. FIND THE ANCHOR
        # We loop backwards through the SRC track. We want the most recent keyframe 
        # that occurred BEFORE OR ON our current target_frame, that is NOT set to -1 (Auto).
        best_k = None
        for k in reversed(src_track):
            if k['f'] <= target_frame and k['val'] >= 0:
                best_k = k
                break
        
        if best_k:
            anchor_val = best_k['val']
            anchor_frame = best_k['f']
        else:
            # Fallback: Start at 0 on frame 1.
            anchor_val = 0.0 
            anchor_frame = 1
            
        current_playhead = anchor_val
        
        # 2. INTEGRATE THE STEPS
        # We start at the anchor value, and for every frame between the anchor and our current frame,
        # we ask the interpolator for the Step Value, and add it. 
        # This allows you to smoothly transition from Step 1 to Step 0 (freeze frame) over time.
        if target_frame > anchor_frame:
            for f in range(int(anchor_frame), int(target_frame)):
                step = self._get_val_at_t('stp', float(f))
                current_playhead += step
                
        return current_playhead