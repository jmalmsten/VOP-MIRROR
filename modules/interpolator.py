"""
VOP Module:     interpolator.py
Version:        v0.2.9
Description:    Timeline state evaluation. 
                Decoupled MDS start/stop colors from the Master node color 
                to prevent channel-clamping during multiplication.
"""
import numpy as np

def hex_to_rgb(h):
    """
    Converts a standard HTML hex color string (e.g. #FF0000) from the UI
    into a normalized numpy float array [1.0, 0.0, 0.0] for the math operations.
    """
    h = h.lstrip('#')
    return np.array([int(h[i:i+2], 16)/255.0 for i in (0, 2, 4)], dtype='f4')

def ensure_vec3(arr_str, default_z=0.0):
    """
    Sanity check for 3D coordinates. Evaluates UI string inputs and 
    pads missing axes to prevent matrix transformation crashes.
    """
    try:
        parts = arr_str.split(',') if isinstance(arr_str, str) else arr_str
        vals = [float(x) for x in parts]
        if len(vals) == 0: return np.array([0.0, 0.0, default_z], dtype='f4')
        if len(vals) == 1: return np.array([vals[0], 0.0, default_z], dtype='f4')
        if len(vals) == 2: return np.array([vals[0], vals[1], default_z], dtype='f4')
        return np.array(vals[:3], dtype='f4')
    except:
        return np.array([0.0, 0.0, default_z], dtype='f4')

def linear_to_oklab(rgb):
    """
    Converts Linear RGB into the Oklab perceptual color space.
    Required for accurate, perceptually uniform color transitions without brightness dips.
    """
    m1 = np.array([[0.41222, 0.53633, 0.05145], [0.21190, 0.68071, 0.10740], [0.08830, 0.28172, 0.62998]], dtype='f4')
    m2 = np.array([[0.21045, 0.79362, -0.00407], [1.97799, -2.42860, 0.45060], [0.02590, 0.78277, -0.80867]], dtype='f4')
    lms = np.dot(m1, rgb)
    return np.dot(m2, np.cbrt(np.maximum(lms, 0)))

def oklab_to_linear(lab):
    """
    Converts Oklab perceptual color space back into Linear RGB for the GPU shader.
    """
    m1_inv = np.array([[1.0, 0.39633, 0.21580], [1.0, -0.10556, -0.06385], [1.0, -0.08948, -1.29148]], dtype='f4')
    m2_inv = np.array([[4.07674, -3.30771, 0.23097], [-1.26843, 2.60975, -0.34131], [-0.00419, -0.70347, 1.70760]], dtype='f4')
    return np.clip(np.dot(m2_inv, np.dot(m1_inv, lab) ** 3), 0.0, 1.0)

class Timeline:
    def __init__(self, job_data):
        self.job = job_data
        
        # Initialize dictionary arrays to hold keyframes for every spatial and temporal property
        self.tracks = {
            'pos': [], 'rot': [], 'pg': [], 'cg': [], 'exp': [], 'sd': [], 'ph': [], 'src': [], 'stp': [],
            'start_p': [], 'stop_p': [], 'start_r': [], 'stop_r': [],
            'start_c': [], 'stop_c': [], 'start_cg': [], 'stop_cg': []
        }
        
        self.mode = job_data.get('smear_mode', 'SSS').lower()
        prefix = "mds_" if self.mode == 'mds' else "sss_"
        
        row_ids = set()
        for k in job_data.keys():
            if k.startswith(prefix + "f"):
                idx = k.replace(prefix + "f", "")
                if idx.isdigit(): row_ids.add(idx)
                
        for idx in sorted(list(row_ids), key=int):
            f_val = float(job_data.get(f"{prefix}f{idx}", 1.0))
            
            p_str = job_data.get(f"{prefix}p{idx}", "0,0,-1.0")
            r_str = job_data.get(f"{prefix}r{idx}", "0,0,0")
            
            pg_hex = job_data.get(f"{prefix}c{idx}_hex", job_data.get(f"{prefix}start_c{idx}_hex", "#ffffff"))
            cg_hex = job_data.get(f"{prefix}cg{idx}_hex", job_data.get(f"{prefix}start_cg{idx}_hex", "#ffffff"))
            
            exp = float(job_data.get(f"{prefix}s{idx}", job_data.get(f"{prefix}exp{idx}", 1.0)))
            sd = float(job_data.get(f"{prefix}sd{idx}", 1.0))
            ph = float(job_data.get(f"{prefix}ph{idx}", 0.5))
            src = float(job_data.get(f"{prefix}src{idx}", -1.0))
            stp = float(job_data.get(f"{prefix}stp{idx}", 1.0))
            
            # Master node tracks
            self.tracks['pos'].append({'f': f_val, 'val': ensure_vec3(p_str, -1.0)})
            self.tracks['rot'].append({'f': f_val, 'val': ensure_vec3(r_str, 0.0)})
            self.tracks['pg'].append({'f': f_val, 'val': hex_to_rgb(pg_hex)})
            self.tracks['cg'].append({'f': f_val, 'val': hex_to_rgb(cg_hex)})
            self.tracks['exp'].append({'f': f_val, 'val': exp})
            self.tracks['sd'].append({'f': f_val, 'val': sd})
            self.tracks['ph'].append({'f': f_val, 'val': ph})
            self.tracks['src'].append({'f': f_val, 'val': src})
            self.tracks['stp'].append({'f': f_val, 'val': stp})

            # Sub-node (Dual-Key) tracks extracted directly from UI JSON
            start_p = ensure_vec3(job_data.get(f"{prefix}start_p{idx}", "0,0,0"), 0.0)
            stop_p = ensure_vec3(job_data.get(f"{prefix}stop_p{idx}", "0,0,0"), 0.0)
            start_r = ensure_vec3(job_data.get(f"{prefix}start_r{idx}", "0,0,0"), 0.0)
            stop_r = ensure_vec3(job_data.get(f"{prefix}stop_r{idx}", "0,0,0"), 0.0)
            start_c = hex_to_rgb(job_data.get(f"{prefix}start_c{idx}_hex", "#ffffff"))
            stop_c = hex_to_rgb(job_data.get(f"{prefix}stop_c{idx}_hex", "#ffffff"))
            start_cg = hex_to_rgb(job_data.get(f"{prefix}start_cg{idx}_hex", "#ffffff"))
            stop_cg = hex_to_rgb(job_data.get(f"{prefix}stop_cg{idx}_hex", "#ffffff"))
            
            self.tracks['start_p'].append({'f': f_val, 'val': start_p})
            self.tracks['stop_p'].append({'f': f_val, 'val': stop_p})
            self.tracks['start_r'].append({'f': f_val, 'val': start_r})
            self.tracks['stop_r'].append({'f': f_val, 'val': stop_r})
            self.tracks['start_c'].append({'f': f_val, 'val': start_c})
            self.tracks['stop_c'].append({'f': f_val, 'val': stop_c})
            self.tracks['start_cg'].append({'f': f_val, 'val': start_cg})
            self.tracks['stop_cg'].append({'f': f_val, 'val': stop_cg})

        # Ensure temporal chronological order for evaluation
        for track in self.tracks.values():
            track.sort(key=lambda x: x['f'])

    def _get_val(self, key, t, color=False):
        """
        Locates the specific interpolation value for a given frame 't'.
        Handles hold frames by returning the outer bounds if 't' exceeds track limits.
        """
        track = self.tracks.get(key, [])
        if not track: return None
        if t <= track[0]['f']: return track[0]['val']
        if t >= track[-1]['f']: return track[-1]['val']
        for i in range(len(track) - 1):
            if track[i]['f'] <= t <= track[i+1]['f']:
                k1, k2 = track[i], track[i+1]
                break
        alpha = (t - k1['f']) / (k2['f'] - k1['f'])
        if color:
            # Color vectors must be evaluated in Oklab to prevent muddy gradients.
            return oklab_to_linear(linear_to_oklab(k1['val']) + (linear_to_oklab(k2['val']) - linear_to_oklab(k1['val'])) * alpha)
        return k1['val'] + (k2['val'] - k1['val']) * alpha

    def get_state(self, t):
        """
        Returns the absolute Master keyframe parameters for a specific float time 't'.
        """
        if not any(self.tracks.values()): return self.get_default_state()
        return {
            'p': self._get_val('pos', t), 'r': self._get_val('rot', t),
            'lp': np.zeros(3, 'f4'), 'lr': np.zeros(3, 'f4'),
            'pg': self._get_val('pg', t, True), 'cg': self._get_val('cg', t, True),
            'exp': float(self._get_val('exp', t) or 1.0), 'sd': float(self._get_val('sd', t) or 1.0),
            'ph': float(self._get_val('ph', t) or 0.5)
        }

    def get_mds_state(self, frame_num, t_norm):
        """
        Calculates the exact sub-frame parameter offset for Dual-Key evaluations.
        't_norm' represents the shutter fraction (0.0 to 1.0) inside the current exposure.
        """
        st_base = self.get_state(frame_num)
        
        # 1. Evaluate the tweened position of the Master bounds at this exact frame
        start_p = self._get_val('start_p', frame_num)
        stop_p = self._get_val('stop_p', frame_num)
        start_r = self._get_val('start_r', frame_num)
        stop_r = self._get_val('stop_r', frame_num)
        start_c = self._get_val('start_c', frame_num, True)
        stop_c = self._get_val('stop_c', frame_num, True)
        start_cg = self._get_val('start_cg', frame_num, True)
        stop_cg = self._get_val('stop_cg', frame_num, True)
        
        # 2. Interpolate from Start to Stop using the fractional shutter progression
        local_p = start_p + (stop_p - start_p) * t_norm
        local_r = start_r + (stop_r - start_r) * t_norm
        
        # 3. Oklab evaluation for exact color shifts inside the physical smear
        c_start_lab = linear_to_oklab(start_c)
        c_stop_lab = linear_to_oklab(stop_c)
        c_lerp = oklab_to_linear(c_start_lab + (c_stop_lab - c_start_lab) * t_norm)
        
        # CRITICAL FIX: Treat Dual-Key color attributes as absolute overrides.
        # Do NOT multiply by st_base['pg'] to avoid clamping the RGB channels to zero.
        pg_val = c_lerp 

        cg_start_lab = linear_to_oklab(start_cg)
        cg_stop_lab = linear_to_oklab(stop_cg)
        cg_lerp = oklab_to_linear(cg_start_lab + (cg_stop_lab - cg_start_lab) * t_norm)
        cg_val = cg_lerp 
        
        return {
            'p': st_base['p'], 'r': st_base['r'], 
            'lp': local_p, 'lr': local_r, 
            'pg': pg_val, 'cg': cg_val, 
            'exp': st_base['exp'], 'sd': st_base['sd'], 'ph': st_base['ph']
        }

    def get_default_state(self):
        """
        Fallback safe dictionary if tracks fail to populate.
        """
        return {
            'p': np.array([0, 0, -1.0], dtype='f4'), 'r': np.array([0, 0, 0], dtype='f4'),
            'lp': np.array([0, 0, 0], dtype='f4'), 'lr': np.array([0, 0, 0], dtype='f4'),
            'pg': np.array([1, 1, 1], dtype='f4'), 'cg': np.array([1, 1, 1], dtype='f4'),
            'exp': 1.0, 'sd': 1.0, 'ph': 0.5
        }

    def calculate_playhead_at(self, target_frame):
        """
        Calculates the active source image playhead.
        Step (STP) increments from the last defined explicit Source Anchor (SRC).
        """
        src_track = self.tracks.get('src', [])
        if not src_track: return 0.0
        anchor_val, anchor_frame = 0.0, 1
        for k in reversed(src_track):
            if k['f'] <= target_frame and k['val'] >= 0:
                anchor_val, anchor_frame = k['val'], k['f']
                break
        if target_frame > anchor_frame:
            for f in range(int(anchor_frame), int(target_frame)):
                anchor_val += self._get_val('stp', f)
        return anchor_val