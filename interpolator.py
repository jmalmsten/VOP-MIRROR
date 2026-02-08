"""
VOP Module:     interpolator.py
Version:        v0.0.5
Description:    Pass-through Quadratic Bézier & Linear interpolation (Numpy Fixed).
"""
import numpy as np

def quadratic_bezier_pass_through(p0, p_target, p2, t):
    """Force curve through p_target at t=0.5."""
    p1 = 2 * p_target - 0.5 * p0 - 0.5 * p2
    return (1-t)**2 * p0 + 2*(1-t)*t * p1 + t**2 * p2

def hex_to_rgb(hex_str):
    """Converts hex to numpy array for valid math operations."""
    h = hex_str.lstrip('#')
    return np.array([int(h[i:i+2], 16)/255.0 for i in (0, 2, 4)])

def get_state_at_t(t, data):
    f1, f2, f3 = int(data['f1']), int(data['f2']), int(data['f3'])
    total_f = f3 - f1
    mid_t = (f2 - f1) / total_f if total_f > 0 else 0.5
    
    if t <= mid_t:
        seg_t = t / mid_t if mid_t > 0 else 0
        ks, ke = "1", "2"
    else:
        seg_t = (t - mid_t) / (1.0 - mid_t) if mid_t < 1.0 else 0
        ks, ke = "2", "3"

    def calc(key, is_vec=False, is_color=False):
        if is_color:
            v1, v2, v3 = [hex_to_rgb(data[f'c{i}_hex']) for i in [1,2,3]]
        elif is_vec:
            v1, v2, v3 = [np.array([float(x) for x in data[f'{key}{i}'].split(',')]) for i in [1,2,3]]
        else:
            # Standard floats are fine for subtraction
            v1, v2, v3 = [float(data[f'{key}{i}']) for i in [1,2,3]]
            
        if data.get(f'{key}_mode') == 'smooth' or (is_color and data.get('c_mode') == 'smooth'):
            return quadratic_bezier_pass_through(v1, v2, v3, t)
        
        vs, ve = (v1, v2) if ks == "1" else (v2, v3)
        return vs + (ve - vs) * seg_t

    return {
        "p": calc('p', True), "r": calc('r', True), "s": calc('s'),
        "ph": calc('ph'), "sd": calc('sd'), "c": calc('c', is_color=True)
    }