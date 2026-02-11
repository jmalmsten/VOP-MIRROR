"""
VOP Module:     interpolator.py
Version:        v0.0.6
Description:    Handles linear/smooth tweening for the VOP fleet.
"""
import numpy as np

def hex_to_rgb(h):
    h = h.lstrip('#')
    return np.array([int(h[i:i+2], 16)/255.0 for i in (0, 2, 4)])

def lerp(a, b, t): return a + (b - a) * t

def smoothstep(t): return t * t * (3 - 2 * t)

def get_state_at_t(t, data):
    # Clamping t to 0-1 range
    t = max(0, min(1, t))
    
    p_m = smoothstep(t) if data.get('p_mode') == 'smooth' else t
    r_m = smoothstep(t) if data.get('r_mode') == 'smooth' else t
    c_m = smoothstep(t) if data.get('c_mode') == 'smooth' else t

    if t <= 0.5:
        sub_t = t * 2.0
        p = lerp(np.array([float(x) for x in data['p1'].split(',')]), np.array([float(x) for x in data['p2'].split(',')]), p_m * 2.0 if t < 0.5 else 1.0)
        r = lerp(np.array([float(x) for x in data['r1'].split(',')]), np.array([float(x) for x in data['r2'].split(',')]), r_m * 2.0 if t < 0.5 else 1.0)
        c = lerp(hex_to_rgb(data['c1_hex']), hex_to_rgb(data['c2_hex']), c_m * 2.0 if t < 0.5 else 1.0)
        cg = lerp(hex_to_rgb(data['cg1_hex']), hex_to_rgb(data['cg2_hex']), c_m * 2.0 if t < 0.5 else 1.0)
        s = lerp(float(data['s1']), float(data['s2']), sub_t)
        sd = lerp(float(data['sd1']), float(data['sd2']), sub_t)
        ph = lerp(float(data['ph1']), float(data['ph2']), sub_t)
    else:
        sub_t = (t - 0.5) * 2.0
        p = lerp(np.array([float(x) for x in data['p2'].split(',')]), np.array([float(x) for x in data['p3'].split(',')]), (p_m - 0.5) * 2.0)
        r = lerp(np.array([float(x) for x in data['r2'].split(',')]), np.array([float(x) for x in data['r3'].split(',')]), (r_m - 0.5) * 2.0)
        c = lerp(hex_to_rgb(data['c2_hex']), hex_to_rgb(data['c3_hex']), (c_m - 0.5) * 2.0)
        cg = lerp(hex_to_rgb(data['cg2_hex']), hex_to_rgb(data['cg3_hex']), (c_m - 0.5) * 2.0)
        s = lerp(float(data['s2']), float(data['s3']), sub_t)
        sd = lerp(float(data['sd2']), float(data['sd3']), sub_t)
        ph = lerp(float(data['ph2']), float(data['ph3']), sub_t)

    return {"p": p, "r": r, "c": c, "cg": cg, "s": s, "sd": sd, "ph": ph}