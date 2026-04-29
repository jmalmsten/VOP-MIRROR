"""
VOP Module:     interpolator.py
Description:    Timeline state evaluation.
                Integrated independent ProjBiPack (BP) spatial tracks.
                And added video functionality.
"""
#
###########################################################################
#
#                                   VOP
#                       Copyright (C) 2025  jmalmsten
#
#     This program is free software: you can redistribute it and/or modify 
#     it under the terms of the GNU Affero General Public License as 
#     published by the Free Software Foundation, either version 3 of the 
#     License, or (at your option) any later version.
#
#     This program is distributed in the hope that it will be useful, but 
#     WITHOUT ANY WARRANTY; without even the implied warranty of 
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU 
#     Affero General Public License for more details.
#
#     You should have received a copy of the GNU Affero General Public 
#     License along with this program.  If not, see 
#     <http://www.gnu.org/licenses/>.
#
#     Source code for this application can be found at 
#     https://codeberg.org/jmalmsten-com/VOP
#
###########################################################################


import numpy as np

def hex_to_rgb(h):
    h = h.lstrip('#')
    return np.array([int(h[i:i+2], 16)/255.0 for i in (0, 2, 4)], dtype='f4')

def ensure_vec3(arr_str, default_z=0.0):
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
    m1 = np.array([[0.41222, 0.53633, 0.05145], [0.21190, 0.68071, 0.10740], [0.08830, 0.28172, 0.62998]], dtype='f4')
    m2 = np.array([[0.21045, 0.79362, -0.00407], [1.97799, -2.42860, 0.45060], [0.02590, 0.78277, -0.80867]], dtype='f4')
    lms = np.dot(m1, rgb)
    return np.dot(m2, np.cbrt(np.maximum(lms, 0)))

def oklab_to_linear(lab):
    m1_inv = np.array([[1.0, 0.39633, 0.21580], [1.0, -0.10556, -0.06385], [1.0, -0.08948, -1.29148]], dtype='f4')
    m2_inv = np.array([[4.07674, -3.30771, 0.23097], [-1.26843, 2.60975, -0.34131], [-0.00419, -0.70347, 1.70760]], dtype='f4')
    return np.clip(np.dot(m2_inv, np.dot(m1_inv, lab) ** 3), 0.0, 1.0)

class Timeline:
    def __init__(self, job_data):
        self.job = job_data
        
        #   *_gate : Optional integer. The hardcoded gate frame anchor.
        #            None means "inherit from earlier anchor / continue accumulating".
        #   *_cam  : Positive integer >= 1. Number of camera (timeline) frames to
        #            HOLD each gate frame before advancing. The "x" in CAM:STP.
        #   *_stp  : Signed integer. Number of gate frames to ADVANCE after each hold.
        #            Can be negative (reverse) or 0 (pause). The "y" in CAM:STP.
        self.tracks = {
            'm': [], 'pos': [], 'rot': [], 'bp_pos': [], 'bp_rot': [], 'pg': [], 'cg': [], 
            'exp': [], 'sd': [], 'ph': [],
            # JK Optical Printer playhead inputs (per-layer: PM=ProjMag, BP=BiPack)
            'pm_gate': [], 'pm_cam': [], 'pm_stp': [],
            'bp_gate': [], 'bp_cam': [], 'bp_stp': [],
            'start_p': [], 'stop_p': [], 'start_r': [], 'stop_r': [],
            'start_bp_p': [], 'stop_bp_p': [], 'start_bp_r': [], 'stop_bp_r': [],
            'start_c': [], 'stop_c': [], 'start_cg': [], 'stop_cg': []
        }
        
        self.mode = job_data.get('smear_mode', 'SSS').lower()
        prefix = "mds_" if self.mode == 'mds' else "sss_"
        
        row_ids = set()
        for k in job_data.keys():
            if k.startswith(prefix + "f"):
                idx = k.replace(prefix + "f", "")
                if idx.isdigit(): row_ids.add(idx)
        
        def parse_optional_int(key):
            """
            GATE parser. Returns int or None.
            
            Empty input or missing key => None (meaning "no anchor at this keyframe;
            inherit from the most recent earlier anchor and keep accumulating).

            Any integer value (including 0 and negatives) => int (a hardcoded anchor).

            This is how the user signals 'don't reset the playhead here' vs
            'snap the gate to this exact frame number'.
            """
            if key not in job_data:
                return None
            raw = job_data.get(key)
            if raw == "" or raw is None:
                return None
            try:
                return int(raw)
            except (ValueError, TypeError):
                raise ValueError(
                    f"Input '{key}' contains invalid data: '{raw}'. "
                    f"GATE must be an integer or empty (empty = inherit)."
                )

        def parse_cam(key, default=1):
            """
            CAM parser of CAM:STP. Must be a positive integer >= 1.

            CAM=0 would be a divide-by-zero ('advance every 0 frames').
            Empty/missing falls back to the default of 1 (normal 1:1 playback). 
            """                
            if key not in job_data:
                return default
            raw = job_data.get(key)
            if raw == "" or raw is None:
                return default
            try:
                val = int(raw)
            except (ValueError, TypeError):
                raise ValueError(
                    f"Input '{key}' contains invalid data: '{raw}'. CAM must be an integer."
                )
            if val < 1:
                raise ValueError(
                    f"Input '{key}' is {val}. CAM must be 1 or greater. "
                    f"CAM is the camera-frame divisor and zero or negative values "
                    f"have no physical meaning in JK Optical Printer logic."
                )
            return val

        def parse_stp(key, default=1):
            """
            STP parser in CAM:STP. Signed integer. Can be:
                positive => forward gate advance
                negative => reverse gate advance
                zero (0) => pause/hold
            Empty/missing falls back to the default of 1 (normal 1:1 playback).
            """
            if key not in job_data:
                return default
            raw = job_data.get(key)
            if raw == "" or raw is None:
                return default
            try:
                return int(raw)
            except (ValueError, TypeError):
                raise ValueError(
                    f"Input '{key}' contains invalid data: '{raw}'. STP must be an integer."
                )

        def require_float(key, fallback_if_unsubmitted=None):
            """
            Strict float parser.
            This explicitly raises a ValueError with the exact UI element ID.
            vop.py catches this exception, prints it to the terminal, and halts the engine cleanly.
            """
            # If the key wasn't submitted in the JSON at all, permit the fallback.
            if key not in job_data and fallback_if_unsubmitted is not None:
                return float(fallback_if_unsubmitted)
                
            raw = job_data.get(key)
            
            # If the user explicitly left the input box blank ("") or it evaluates to None
            if raw == "" or raw is None:
                raise ValueError(f"Input '{key}' is empty! Halting execution. Please provide a value.")
                
            try:
                return float(raw)
            except ValueError:
                raise ValueError(f"Input '{key}' contains invalid data: '{raw}'. Must be a number.")

        for idx in sorted(list(row_ids), key=int):

            # f_val can still use safe_f or require_float, but since it dictates the loop, we ensure it's strictly parsed
            f_val = require_float(f"{prefix}f{idx}")
            
            # Extract Interpolation Mode (S = Smooth, L = Linear)
            self.tracks['m'].append({'f': f_val, 'val': job_data.get(f"{prefix}m{idx}", "S")})
            
            self.tracks['pos'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}p{idx}", "0,0,-1.0"), -1.0)})
            self.tracks['rot'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}r{idx}", "0,0,0"), 0.0)})
            self.tracks['bp_pos'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}bp_p{idx}", "0,0,-1.0"), -1.0)})
            self.tracks['bp_rot'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}bp_r{idx}", "0,0,0"), 0.0)})
            
            self.tracks['pg'].append({'f': f_val, 'val': hex_to_rgb(job_data.get(f"{prefix}c{idx}_hex", "#ffffff"))})
            self.tracks['cg'].append({'f': f_val, 'val': hex_to_rgb(job_data.get(f"{prefix}cg{idx}_hex", "#ffffff"))})
            
            # --- THESE LINES ENFORCE STRICT PARSING ---
            exp_key = f"{prefix}s{idx}" if self.mode == 'mds' else f"{prefix}exp{idx}"
            self.tracks['exp'].append({'f': f_val, 'val': require_float(exp_key)})
            self.tracks['sd'].append({'f': f_val, 'val': require_float(f"{prefix}sd{idx}", 1.0)})
            self.tracks['ph'].append({'f': f_val, 'val': require_float(f"{prefix}ph{idx}", 0.5)})
            
            # JK Optical Printer playhead tracks - parsed per-layer.
            # These keys come from the UI as e.g. "sss_pm_gate3" or "mds_bp_cam7".
            self.tracks['pm_gate'].append({'f': f_val, 'val': parse_optional_int(f"{prefix}pm_gate{idx}")})
            self.tracks['pm_cam'].append({'f': f_val, 'val': parse_cam(f"{prefix}pm_cam{idx}")})
            self.tracks['pm_stp'].append({'f': f_val, 'val': parse_stp(f"{prefix}pm_stp{idx}")})
            self.tracks['bp_gate'].append({'f': f_val, 'val': parse_optional_int(f"{prefix}bp_gate{idx}")})
            self.tracks['bp_cam'].append({'f': f_val, 'val': parse_cam(f"{prefix}bp_cam{idx}")})
            self.tracks['bp_stp'].append({'f': f_val, 'val': parse_stp(f"{prefix}bp_stp{idx}")})

            # MDS Start/Stop offsets (Ignored during SSS execution)
            self.tracks['start_p'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}start_p{idx}", "0,0,0"))})
            self.tracks['stop_p'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}stop_p{idx}", "0,0,0"))})
            self.tracks['start_r'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}start_r{idx}", "0,0,0"))})
            self.tracks['stop_r'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}stop_r{idx}", "0,0,0"))})
            
            self.tracks['start_bp_p'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}start_bp_p{idx}", "0,0,0"))})
            self.tracks['stop_bp_p'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}stop_bp_p{idx}", "0,0,0"))})
            self.tracks['start_bp_r'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}start_bp_r{idx}", "0,0,0"))})
            self.tracks['stop_bp_r'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}stop_bp_r{idx}", "0,0,0"))})

            self.tracks['start_c'].append({'f': f_val, 'val': hex_to_rgb(job_data.get(f"{prefix}start_c{idx}_hex", "#ffffff"))})
            self.tracks['stop_c'].append({'f': f_val, 'val': hex_to_rgb(job_data.get(f"{prefix}stop_c{idx}_hex", "#ffffff"))})
            self.tracks['start_cg'].append({'f': f_val, 'val': hex_to_rgb(job_data.get(f"{prefix}start_cg{idx}_hex", "#ffffff"))})
            self.tracks['stop_cg'].append({'f': f_val, 'val': hex_to_rgb(job_data.get(f"{prefix}stop_cg{idx}_hex", "#ffffff"))})

        for track in self.tracks.values():
            track.sort(key=lambda x: x['f'])

    def _get_interp_mode(self, t):
        """Helper to find if the current interval is set to Smooth ('S') or Linear ('L')"""
        m_track = self.tracks.get('m', [])
        if not m_track: return 'S'
        
        # Find the interpolation mode of the keyframe immediately preceding or equal to 't'
        for i in range(len(m_track) - 1):
            if m_track[i]['f'] <= t < m_track[i+1]['f']:
                return m_track[i]['val']
        return m_track[-1]['val']

    def _get_val(self, key, t, is_color=False):
        track = self.tracks.get(key, [])
        if not track: return None
        if t <= track[0]['f']: return track[0]['val']
        if t >= track[-1]['f']: return track[-1]['val']
        
        for i in range(len(track) - 1):
            if track[i]['f'] <= t <= track[i+1]['f']:
                k1, k2 = track[i], track[i+1]
                break
                
        # Base Linear Alpha (0.0 to 1.0 representing percentage traversed between k1 and k2)
        alpha = (t - k1['f']) / (k2['f'] - k1['f'])
        
        # SSS Core Interpolation Logic:
        # If the origin keyframe is 'S' (Smooth), apply Cosine Easing.
        # This transforms the linear ramp into an S-curve, ensuring zero velocity 
        # at the exact moment of the keyframe, producing fluid motion without mechanical stops.
        if self.mode == 'sss':
            if self._get_interp_mode(k1['f']) == 'S':
                alpha = (1.0 - np.cos(alpha * np.pi)) / 2.0
                
        if is_color:
            return oklab_to_linear(linear_to_oklab(k1['val']) + (linear_to_oklab(k2['val']) - linear_to_oklab(k1['val'])) * alpha)
        return k1['val'] + (k2['val'] - k1['val']) * alpha

    def get_state(self, t):
        """
        SSS Time Domain Mapping:
        In SSS mode, 't' is not a whole integer, it is a fractional frame decimal.
        engine.py calculates this 't' continuously during the physical exposure loop based on:
        
        1. SD (Shutter Duration): Multiplier of the standard frame interval. 
           (e.g., SD = 1.0 means shutter is open for a full 1/24th distance, SD = 0.5 means half distance).
        2. PH (Playhead Phase): Offsets the center point of the exposure. 
           (e.g., PH = 0.5 centers the exposure symmetrically on the frame number. PH = 0.0 pushes the exposure to start exactly AT the frame number).
           
        This continuous 't' is passed to _get_val(), which smoothly interpolates absolute positions.
        """
        if not any(self.tracks.values()): return self.get_default_state()
        
        def safe_val(key, default_arr):
            v = self._get_val(key, t)
            return v if v is not None else default_arr
            
        def safe_col(key, default_arr):
            v = self._get_val(key, t, True)
            return v if v is not None else default_arr

        # Checks for None explicitly so that 0.0 is passed through correctly
        def safe_float(key, default_val):
            v = self._get_val(key, t)
            return float(v) if v is not None else default_val

        return {
            'p': safe_val('pos', np.array([0, 0, -1.0], dtype='f4')), 
            'r': safe_val('rot', np.array([0, 0, 0], dtype='f4')),
            'bp_p': safe_val('bp_pos', np.array([0, 0, -1.0], dtype='f4')), 
            'bp_r': safe_val('bp_rot', np.array([0, 0, 0], dtype='f4')),
            # Local offsets (lp/lr) are held at zero during SSS execution.
            'lp': np.zeros(3, 'f4'), 'lr': np.zeros(3, 'f4'),
            'lbp_p': np.zeros(3, 'f4'), 'lbp_r': np.zeros(3, 'f4'),
            'pg': safe_col('pg', np.array([1, 1, 1], dtype='f4')), 
            'cg': safe_col('cg', np.array([1, 1, 1], dtype='f4')),

            'exp': safe_float('exp', 1.0),
            'sd': safe_float('sd', 1.0),
            'ph': safe_float('ph', 0.5)
        }

    def get_mds_state(self, frame_num, t_norm):
        if not any(self.tracks.values()): return self.get_default_state()
        
        st_base = self.get_state(frame_num)
        
        def safe_val(key, default_arr):
            v = self._get_val(key, frame_num)
            return v if v is not None else default_arr
            
        def safe_col(key, default_arr):
            v = self._get_val(key, frame_num, True)
            return v if v is not None else default_arr
            
        start_p    = safe_val('start_p',    np.zeros(3, 'f4'))
        stop_p     = safe_val('stop_p',     np.zeros(3, 'f4'))
        start_r    = safe_val('start_r',    np.zeros(3, 'f4'))
        stop_r     = safe_val('stop_r',     np.zeros(3, 'f4'))
        start_bp_p = safe_val('start_bp_p', np.zeros(3, 'f4'))
        stop_bp_p  = safe_val('stop_bp_p',  np.zeros(3, 'f4'))
        start_bp_r = safe_val('start_bp_r', np.zeros(3, 'f4'))
        stop_bp_r  = safe_val('stop_bp_r',  np.zeros(3, 'f4'))

        lp    = start_p    + (stop_p    - start_p)    * t_norm
        lr    = start_r    + (stop_r    - start_r)    * t_norm
        lbp_p = start_bp_p + (stop_bp_p - start_bp_p) * t_norm
        lbp_r = start_bp_r + (stop_bp_r - start_bp_r) * t_norm
        pg_start = safe_col('start_c', np.array([1,1,1],'f4'))
        pg_stop = safe_col('stop_c', np.array([1,1,1],'f4'))
        pg_val = oklab_to_linear(linear_to_oklab(pg_start) + (linear_to_oklab(pg_stop) - linear_to_oklab(pg_start)) * t_norm)
        
        cg_start = safe_col('start_cg', np.array([1,1,1],'f4'))
        cg_stop = safe_col('stop_cg', np.array([1,1,1],'f4'))
        cg_val = oklab_to_linear(linear_to_oklab(cg_start) + (linear_to_oklab(cg_stop) - linear_to_oklab(cg_start)) * t_norm)
        
        return {
            'p': st_base['p'], 'r': st_base['r'], 'lp': lp, 'lr': lr,
            'bp_p': st_base['bp_p'], 'bp_r': st_base['bp_r'], 'lbp_p': lbp_p, 'lbp_r': lbp_r,
            'pg': pg_val, 'cg': cg_val, 'exp': st_base['exp'], 'sd': st_base['sd'], 'ph': st_base['ph']
        }

    def get_default_state(self):
        return {
            'p': np.array([0, 0, -1.0], dtype='f4'), 'r': np.array([0, 0, 0], dtype='f4'),
            'bp_p': np.array([0, 0, -1.0], dtype='f4'), 'bp_r': np.array([0, 0, 0], dtype='f4'),
            'lp': np.zeros(3, 'f4'), 'lr': np.zeros(3, 'f4'),
            'lbp_p': np.zeros(3, 'f4'), 'lbp_r': np.zeros(3, 'f4'),
            'pg': np.array([1, 1, 1], dtype='f4'), 'cg': np.array([1, 1, 1], dtype='f4'),
            'exp': 1.0, 'sd': 1.0, 'ph': 0.5
        }

    def _get_step_held(self, key, t, default=None):
        """
        Step-hold (no interpolation) lookup. returns the value of the most recent
        keyframe at or before t. Used for discrete inputs like CAM and STP that 
        should HOLD their value between keyframes rather than smoothly transition.

        Why not _get_val? _get_val does linear/cosine interpolation between
        keyframes - correct for spatial values like position and rotation, but 
        wrong for integer rate controls. If the user sets CAM:STP to 3:2 at
        keyframe 1 and 1:1 at keyframe 5 we want a hard switch at frame 5,
        not a gradual ease from 3:2 to 1:1
        """
        track = self.tracks.get(key, [])
        if not track:
            return default
        
        # Walk forward; the last keyframe whose frame <= t wins.
        val = track[0]['val'] if track[0]['val'] is not None else default
        for k in track:
            if k['f'] <= t:
                if k['val'] is not None:
                    val = k['val']
            else:
                break
        return val

    def calculate_playhead_at(self, target_frame, layer='pm'):
        """
        JK Optical Printer playhead resolution for the specified layer.

        Returns:
            Integer gate frame index that the texture manager should load for this
            layer at this timeline frame.
        
        Algorithm (mirrors mechanical JK Optical Printer behavior):

        1. Walk BACKWARD through the gate track to find the most recent keyframe
           with a hardcoded Gate value (val is not None). That becomes our anchor.
           If no anchor exists anywhere, default to gate=0 at frame=1.

        2. If target_frame is at or before the anchor frame, return the anchor
           value directly. This is the 'hard cut' behavior: when a keyframe
           declares a hardcoded gate, the playhead snaps to it without smoothing.

        3. Otherwise, walk FORWARD from anchor to target one camera frame at a
           time. At each camera frame, look up the current CAM:STP rate (which
           may have changed mid-stream due to other keyframes) and increment a
           hold_counter. When hold_counter reaches CAM, advance the gate by STP
           and reset the counter.

           This produces the staccato judder of a real JK printer:
           3:2 yields gate values 1,1,1,3,3,3,5,5,5... rather than smoothly
           interpolating between rates.
        """
        gate_key = f'{layer}_gate'
        cam_key  = f'{layer}_cam'
        stp_key  = f'{layer}_stp'

        gate_track = self.tracks.get(gate_key, [])

        # ---- Step 1: locate the anchor ----
        # Default fallback: if no keyframe ever sets a hardcoded gate, start from
        # gate frame 0 at timeline frame 1. this gives sensible behavior for jobs
        # that just want plain 1:1 playback without explicitly anchoring.
        anchor_gate = 0
        anchor_frame = 1
        for k in reversed(gate_track):
            if k['f'] <= target_frame and k['val'] is not None:
                anchor_gate = int(k['val'])
                anchor_frame = int(k['f'])
                break
        
        # ---- Step 2: hard cut at or before anchor ----
        if target_frame <= anchor_frame:
            return anchor_gate
        
        # ---- Step 3: walk forward with staccato hold logic ----
        gate = anchor_gate
        hold_counter = 0

        for f in range (int(anchor_frame), int(target_frame)):
            # Look up CAM:STP at this specific camera frame. The values come from
            # the most recent keyframe at or before f (step-hold semantics, no
            # interpolation), so a mid-stream rate change kicks in cleanly.
            cam = self._get_step_held(cam_key, f, default=1)
            stp = self._get_step_held(stp_key, f, default=1)

            # Defensive clamp: parser already enforces cam>=1, but if the track is
            # somehow empty or returns None, fall back to 1 to avoid an infinite hold.
            if cam is None or cam < 1:
                cam = 1
            if stp is None:
                stp = 1
            
            hold_counter += 1
            if hold_counter >= cam:
                gate += stp
                hold_counter = 0
        
        return gate