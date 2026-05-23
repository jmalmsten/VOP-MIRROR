"""
VOP Module:     interpolator.py
Description:    Timeline state evaluation.
                Integrated independent ProjBiPack (BP) spatial tracks.
                And added video functionality.
                Renamed bp_* tracks to bp1_* and added parallel bp2_* tracks 
                to support a third optical layer (v0.8.0).
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
            'm': [], 'pos': [], 'rot': [], 
            # Per-bipack-layer spatial tracks. bp1_* replaces the old single-bipack 
            # 'bp_*' set; bp2_* is added for the new third optical layer.
            'bp1_pos': [], 'bp1_rot': [], 
            'bp2_pos': [], 'bp2_rot': [], 
            'pg': [], 'cg': [], 
            'exp': [], 'sd': [], 'ph': [], 'dre_steps': [],
            # JK Optical Printer playhead inputs (per-layer: PM=ProjMag, BP1/BP2=BiPack reels)
            'pm_gate': [], 'pm_cam': [], 'pm_stp': [],
            'bp1_gate': [], 'bp1_cam': [], 'bp1_stp': [],
            'bp2_gate': [], 'bp2_cam': [], 'bp2_stp': [],
            'start_p': [], 'stop_p': [], 'start_r': [], 'stop_r': [],
            # MDS smear start/stop offsets per bipack layer
            'start_bp1_p': [], 'stop_bp1_p': [], 'start_bp1_r': [], 'stop_bp1_r': [],
            'start_bp2_p': [], 'stop_bp2_p': [], 'start_bp2_r': [], 'stop_bp2_r': [],
            'start_c': [], 'stop_c': [], 'start_cg': [], 'stop_cg': []
        }

        self.mode = job_data.get('smear_mode', 'SSS').lower()
        if self.mode == 'mds':
            prefix = "mds_"
        elif self.mode == 'sss':
            prefix = "sss_"
        elif self.mode == 'dre':
            # DRE mode (Dynamic Range Extender, issue #169). The exposure
            # sheet schema is intentionally minimal: frame number, exposure
            # time, DRE step count, and per-keyframe projector/camera gels.
            # No spatial transforms, no smear start/stop, no JK printer
            # columns - the frame is held stationary while luminance is
            # animated by the engine's DRE path.
            prefix = "dre_"
        elif self.mode == 'brk':
            # BRK mode (Bracketed exposures).
            #
            # BRK keyframes populate self.tracks via the same
            # shared parser loop as SSS / MDS / DRE - the BRK
            # xsheet field names (brk_pm_pos<n>, brk_pm_gate<n>,
            # brk_c<n>_hex, etc.) were designed to match the
            # existing track-naming convention precisely so this
            # works out of the box.
            #
            # BRK-specific behaviour relative to the other modes:
            #
            #   - No per-keyframe EXP field. The exposure time is
            #     governed by t_peak from calibration.json (a
            #     job-global hardware value, not a timeline value).
            #     require_float's fallback handles the missing
            #     brk_exp<n> key - we set the default to 1.0 so
            #     the track has a sane value even though the engine
            #     never reads it.
            #
            #   - Frame-locked hold semantics across keyframes
            #     instead of smooth or linear interpolation. The
            #     engine reads BRK state via get_brk_state() (below
            #     in this file), which uses step-hold lookup
            #     against self.tracks - it returns the most recent
            #     keyframe's values rather than interpolating
            #     between adjacent ones.
            #
            # Everything else (POS, ROT, JK printer GATE/CAM/STP,
            # per-bipack-layer fields, gels) flows through the
            # shared parser unchanged. So this branch is just a
            # one-liner: set the prefix and fall through.
            prefix = "brk_"
        else:
            raise ValueError(
                f"Unknown smear_mode '{self.mode}' in job data. "
                f"Expected one of: SSS, MDS, DRE, BRK."
            )

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
            # Per-bipack-layer pos/rot. Keys: 'sss_bp1_p1', 'mds_bp2_r3', etc.
            self.tracks['bp1_pos'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}bp1_p{idx}", "0,0,-1.0"), -1.0)})
            self.tracks['bp1_rot'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}bp1_r{idx}", "0,0,0"), 0.0)})
            self.tracks['bp2_pos'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}bp2_p{idx}", "0,0,-1.0"), -1.0)})
            self.tracks['bp2_rot'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}bp2_r{idx}", "0,0,0"), 0.0)})
            
            self.tracks['pg'].append({'f': f_val, 'val': hex_to_rgb(job_data.get(f"{prefix}c{idx}_hex", "#ffffff"))})
            self.tracks['cg'].append({'f': f_val, 'val': hex_to_rgb(job_data.get(f"{prefix}cg{idx}_hex", "#ffffff"))})
            
            # --- THESE LINES ENFORCE STRICT PARSING ---
            # EXP field name varies by mode:
            #   sss_exp<n>  (SSS)
            #   mds_s<n>    (MDS; legacy short name)
            #   dre_exp<n>  (DRE; matches SSS convention)
            # Both SSS and DRE use the long "exp" name; only MDS uses "s".
            if self.mode == 'mds':
                exp_key = f"{prefix}s{idx}"
            else:
                exp_key = f"{prefix}exp{idx}"
            # DRE-only field. SSS/MDS jobs skip this (the key won't 
            # exist; require_float falls back to the default of 256). 
            # Parsing it unconditionally keeps the track-array lengths 
            # aligned across all rows regardless of mode, which is what 
            # _get_val expects.
            self.tracks['dre_steps'].append({'f': f_val, 'val': require_float(f"{prefix}steps{idx}", 256.0)})
            # BRK has no per-keyframe EXP field (uses t_peak from
            # calibration instead). Pass a 1.0 fallback so a missing
            # brk_exp<n> key doesn't trip require_float's strict-blank
            # check. The 1.0 value goes into self.tracks['exp'] for
            # shape consistency with the other modes but the engine
            # never reads it for BRK (see execute_brk_exposure).
            self.tracks['exp'].append({'f': f_val, 'val': require_float(exp_key, fallback_if_unsubmitted=1.0)})
            self.tracks['sd'].append({'f': f_val, 'val': require_float(f"{prefix}sd{idx}", 1.0)})
            self.tracks['ph'].append({'f': f_val, 'val': require_float(f"{prefix}ph{idx}", 0.5)})
            
            # JK Optical Printer playhead tracks - parsed per-layer.
            # These keys come from the UI as e.g. "sss_pm_gate3", "mds_bp1_cam7", "sss_bp2_stp2".
            self.tracks['pm_gate'].append({'f': f_val, 'val': parse_optional_int(f"{prefix}pm_gate{idx}")})
            self.tracks['pm_cam'].append({'f': f_val, 'val': parse_cam(f"{prefix}pm_cam{idx}")})
            self.tracks['pm_stp'].append({'f': f_val, 'val': parse_stp(f"{prefix}pm_stp{idx}")})
            self.tracks['bp1_gate'].append({'f': f_val, 'val': parse_optional_int(f"{prefix}bp1_gate{idx}")})
            self.tracks['bp1_cam'].append({'f': f_val, 'val': parse_cam(f"{prefix}bp1_cam{idx}")})
            self.tracks['bp1_stp'].append({'f': f_val, 'val': parse_stp(f"{prefix}bp1_stp{idx}")})
            self.tracks['bp2_gate'].append({'f': f_val, 'val': parse_optional_int(f"{prefix}bp2_gate{idx}")})
            self.tracks['bp2_cam'].append({'f': f_val, 'val': parse_cam(f"{prefix}bp2_cam{idx}")})
            self.tracks['bp2_stp'].append({'f': f_val, 'val': parse_stp(f"{prefix}bp2_stp{idx}")})

            # MDS Start/Stop offsets (Ignored during SSS execution)
            self.tracks['start_p'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}start_p{idx}", "0,0,0"))})
            self.tracks['stop_p'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}stop_p{idx}", "0,0,0"))})
            self.tracks['start_r'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}start_r{idx}", "0,0,0"))})
            self.tracks['stop_r'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}stop_r{idx}", "0,0,0"))})
            
            # Per-bipack-layer MDS smear offsets
            self.tracks['start_bp1_p'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}start_bp1_p{idx}", "0,0,0"))})
            self.tracks['stop_bp1_p'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}stop_bp1_p{idx}", "0,0,0"))})
            self.tracks['start_bp1_r'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}start_bp1_r{idx}", "0,0,0"))})
            self.tracks['stop_bp1_r'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}stop_bp1_r{idx}", "0,0,0"))})
            self.tracks['start_bp2_p'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}start_bp2_p{idx}", "0,0,0"))})
            self.tracks['stop_bp2_p'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}stop_bp2_p{idx}", "0,0,0"))})
            self.tracks['start_bp2_r'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}start_bp2_r{idx}", "0,0,0"))})
            self.tracks['stop_bp2_r'].append({'f': f_val, 'val': ensure_vec3(job_data.get(f"{prefix}stop_bp2_r{idx}", "0,0,0"))})

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
            'bp1_p': safe_val('bp1_pos', np.array([0, 0, -1.0], dtype='f4')), 
            'bp1_r': safe_val('bp1_rot', np.array([0, 0, 0], dtype='f4')),
            'bp2_p': safe_val('bp2_pos', np.array([0, 0, -1.0], dtype='f4')), 
            'bp2_r': safe_val('bp2_rot', np.array([0, 0, 0], dtype='f4')),
            # Local offsets (lp/lr) are held at zero during SSS execution.
            # One l*_p/l*_r pair per layer; engine multiplies these into the 
            # master pos/rot to produce the per-smear-tick local offset.
            'lp': np.zeros(3, 'f4'), 'lr': np.zeros(3, 'f4'),
            'lbp1_p': np.zeros(3, 'f4'), 'lbp1_r': np.zeros(3, 'f4'),
            'lbp2_p': np.zeros(3, 'f4'), 'lbp2_r': np.zeros(3, 'f4'),
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
        # Per-bipack-layer MDS smear offsets. Pulled from the start_bp{N}_* / 
        # stop_bp{N}_* tracks, which the parser above populated from the UI.
        start_bp1_p = safe_val('start_bp1_p', np.zeros(3, 'f4'))
        stop_bp1_p  = safe_val('stop_bp1_p',  np.zeros(3, 'f4'))
        start_bp1_r = safe_val('start_bp1_r', np.zeros(3, 'f4'))
        stop_bp1_r  = safe_val('stop_bp1_r',  np.zeros(3, 'f4'))
        start_bp2_p = safe_val('start_bp2_p', np.zeros(3, 'f4'))
        stop_bp2_p  = safe_val('stop_bp2_p',  np.zeros(3, 'f4'))
        start_bp2_r = safe_val('start_bp2_r', np.zeros(3, 'f4'))
        stop_bp2_r  = safe_val('stop_bp2_r',  np.zeros(3, 'f4'))

        lp     = start_p     + (stop_p     - start_p)     * t_norm
        lr     = start_r     + (stop_r     - start_r)     * t_norm
        lbp1_p = start_bp1_p + (stop_bp1_p - start_bp1_p) * t_norm
        lbp1_r = start_bp1_r + (stop_bp1_r - start_bp1_r) * t_norm
        lbp2_p = start_bp2_p + (stop_bp2_p - start_bp2_p) * t_norm
        lbp2_r = start_bp2_r + (stop_bp2_r - start_bp2_r) * t_norm
        pg_start = safe_col('start_c', np.array([1,1,1],'f4'))
        pg_stop = safe_col('stop_c', np.array([1,1,1],'f4'))
        pg_val = oklab_to_linear(linear_to_oklab(pg_start) + (linear_to_oklab(pg_stop) - linear_to_oklab(pg_start)) * t_norm)
        
        cg_start = safe_col('start_cg', np.array([1,1,1],'f4'))
        cg_stop = safe_col('stop_cg', np.array([1,1,1],'f4'))
        cg_val = oklab_to_linear(linear_to_oklab(cg_start) + (linear_to_oklab(cg_stop) - linear_to_oklab(cg_start)) * t_norm)
        
        return {
            'p': st_base['p'], 'r': st_base['r'], 'lp': lp, 'lr': lr,
            'bp1_p': st_base['bp1_p'], 'bp1_r': st_base['bp1_r'], 'lbp1_p': lbp1_p, 'lbp1_r': lbp1_r,
            'bp2_p': st_base['bp2_p'], 'bp2_r': st_base['bp2_r'], 'lbp2_p': lbp2_p, 'lbp2_r': lbp2_r,
            'pg': pg_val, 'cg': cg_val, 'exp': st_base['exp'], 'sd': st_base['sd'], 'ph': st_base['ph']
        }
    
    def get_dre_state(self, frame_num):
        """
        Returns the resolved DRE state at a given frame.
        
        DRE (Dynamic Range Extender) mode schema is minimal compared 
        to SSS / MDS:
            exp        : exposure window in seconds (interpolated)
            dre_steps  : number of temporal luminance sub-exposures 
                         (interpolated, then cast to int)
            pg         : projector gel as RGB float array (interpolated)
            cg         : camera gel as RGB float array (interpolated)
        
        No position, rotation, scale, smear start/stop, or JK printer 
        columns - the frame is held stationary while luminance is 
        animated by engine.py's execute_dre_exposure path.
        
        Phase 3 of issue #169.
        """
        # No keyframes at all -> sane defaults so the engine can at 
        # least try to render. Matches the behavior of get_state's 
        # empty-tracks short-circuit.
        if not any(self.tracks.values()):
            return {
                'exp': 1.0,
                'dre_steps': 256,
                'pg': np.array([1, 1, 1], dtype='f4'),
                'cg': np.array([1, 1, 1], dtype='f4'),
            }
        
        # Use the real interpolation helper _get_val. Pass True as the 
        # third arg for color fields (signals RGB-array interpolation 
        # rather than scalar). Default fallbacks mirror get_state's 
        # safe_val / safe_col / safe_float pattern.
        def safe_float(key, default_val):
            v = self._get_val(key, frame_num)
            return float(v) if v is not None else default_val
        
        def safe_col(key, default_arr):
            v = self._get_val(key, frame_num, True)
            return v if v is not None else default_arr
        
        exp       = safe_float('exp', 1.0)
        dre_steps_f = safe_float('dre_steps', 256.0)
        # Round to nearest int; engine will further clamp against the 
        # panel refresh floor at exposure time.
        dre_steps = max(2, int(round(dre_steps_f)))
        
        pg = safe_col('pg', np.array([1, 1, 1], dtype='f4'))
        cg = safe_col('cg', np.array([1, 1, 1], dtype='f4'))
        
        return {
            'exp': exp,
            'dre_steps': dre_steps,
            'pg': pg,
            'cg': cg,
        }

    def get_brk_state(self, frame_num):
        """
        BRK mode per-frame state lookup.

        Frame-locked-hold semantics: returns the values of the
        most recent keyframe whose frame number is <= frame_num.
        No interpolation between keyframes - BRK keyframes are
        discrete settings that snap into effect at their frame
        number and stay until the next keyframe (or end of job).
        This matches how a real optical printer holds a setup
        while it cranks through frames at that setup, then
        re-pegs for the next setup.

        Reads from self.tracks (populated by the shared parser
        loop, same as SSS / MDS / DRE). Empty-tracks fallback
        returns identity defaults so the engine can render a
        BRK job that has no keyframes at all without crashing.

        Returns a dict with the same shape as get_state() /
        get_dre_state() so downstream engine code can consume
        BRK state without mode-specific branching at most
        callsites:
            'p'     : PM position (numpy vec3, default 0,0,-1.0)
            'r'     : PM rotation (numpy vec3, default 0,0,0)
            'bp1_p' : BP1 position
            'bp1_r' : BP1 rotation
            'bp2_p' : BP2 position
            'bp2_r' : BP2 rotation
            'lp', 'lr', 'lbp1_p', 'lbp1_r', 'lbp2_p', 'lbp2_r'
                    : local-offset versions, all zero for BRK
                      (no smear / no per-tick local motion)
            'pg'    : projector gel (numpy float RGB, default
                      identity white)
            'cg'    : camera gel (numpy float RGB, default
                      identity white)
            'exp'   : exposure time. NOT used by the engine for
                      BRK (engine reads t_peak from calibration
                      instead), but populated so the state dict
                      shape matches the other modes.
            'sd', 'ph' : smear duration / playhead-phase. Defaults
                      (1.0 / 0.5), unused by BRK but kept for
                      shape consistency.
        """
        # No keyframes parsed -> sane defaults so the engine
        # can at least try to render. Matches get_state's and
        # get_dre_state's empty-tracks short-circuit pattern.
        if not any(self.tracks.values()):
            return self.get_default_state()

        # Step-hold lookup for each track. _get_step_held is
        # the existing helper used by calculate_playhead_at
        # for JK printer CAM/STP, so we're reusing an
        # already-tested code path. The pattern: pass the
        # track name and frame_num, get back the most-recent
        # keyframe's value (or the default if frame_num
        # precedes all keyframes).
        def hold(key, default):
            v = self._get_step_held(key, frame_num, default=None)
            return v if v is not None else default

        return {
            # PM spatial
            'p':  hold('pos', np.array([0, 0, -1.0], dtype='f4')),
            'r':  hold('rot', np.array([0, 0,  0.0], dtype='f4')),
            # BP1 spatial
            'bp1_p': hold('bp1_pos', np.array([0, 0, -1.0], dtype='f4')),
            'bp1_r': hold('bp1_rot', np.array([0, 0,  0.0], dtype='f4')),
            # BP2 spatial
            'bp2_p': hold('bp2_pos', np.array([0, 0, -1.0], dtype='f4')),
            'bp2_r': hold('bp2_rot', np.array([0, 0,  0.0], dtype='f4')),
            # Local-offset slots, always zero for BRK (no smear,
            # no per-tick motion within an exposure).
            'lp':     np.zeros(3, 'f4'),
            'lr':     np.zeros(3, 'f4'),
            'lbp1_p': np.zeros(3, 'f4'),
            'lbp1_r': np.zeros(3, 'f4'),
            'lbp2_p': np.zeros(3, 'f4'),
            'lbp2_r': np.zeros(3, 'f4'),
            # Gels
            'pg': hold('pg', np.array([1, 1, 1], dtype='f4')),
            'cg': hold('cg', np.array([1, 1, 1], dtype='f4')),
            # Shape-consistency fields. The engine reads t_peak
            # from calibration.json for BRK; 'exp' is here only
            # so callsites that destructure state['exp'] don't
            # KeyError when handed a BRK state dict.
            'exp': float(hold('exp', 1.0)),
            'sd':  float(hold('sd',  1.0)),
            'ph':  float(hold('ph',  0.5)),
        }

    

    def get_default_state(self):
        return {
            'p': np.array([0, 0, -1.0], dtype='f4'), 'r': np.array([0, 0, 0], dtype='f4'),
            'bp1_p': np.array([0, 0, -1.0], dtype='f4'), 'bp1_r': np.array([0, 0, 0], dtype='f4'),
            'bp2_p': np.array([0, 0, -1.0], dtype='f4'), 'bp2_r': np.array([0, 0, 0], dtype='f4'),
            'lp': np.zeros(3, 'f4'), 'lr': np.zeros(3, 'f4'),
            'lbp1_p': np.zeros(3, 'f4'), 'lbp1_r': np.zeros(3, 'f4'),
            'lbp2_p': np.zeros(3, 'f4'), 'lbp2_r': np.zeros(3, 'f4'),
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