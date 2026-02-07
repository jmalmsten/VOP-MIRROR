"""
VOP Module:     color_utils.py
Version:        v0.0.1
Description:    Oklab color space utilities for perceptual lerping.
"""
import numpy as np

def linear_srgb_to_oklab(rgb):
    m1 = np.array([
        [0.4122214708, 0.5363325363, 0.0514459929],
        [0.2119034982, 0.6806995451, 0.1073969566],
        [0.0883024619, 0.2817188376, 0.6299787005]
    ])
    lms = np.dot(m1, rgb)
    lms_cube = np.cbrt(np.maximum(lms, 0))
    m2 = np.array([
        [0.2104542553, 0.7936177850, -0.0040720468],
        [1.9779984951, -2.4285922050, 0.4505937099],
        [0.0259040371, 0.7827717662, -0.8086757660]
    ])
    return np.dot(m2, lms_cube)

def oklab_to_linear_srgb(lab):
    m1 = np.array([
        [1.0, 0.3963377774, 0.2158037573],
        [1.0, -0.1055613458, -0.0638541728],
        [1.0, -0.0894841775, -1.2914855480]
    ])
    lms_cube = np.dot(m1, lab)
    lms = lms_cube**3
    m2 = np.array([
        [4.0767416621, -3.3077115913, 0.2309699292],
        [-1.2684380046, 2.6097574011, -0.3413193965],
        [-0.0041960863, -0.7034190430, 1.7076127025]
    ])
    return np.dot(m2, lms)

def get_perceptual_color(t, c1, c2):
    lab1 = linear_srgb_to_oklab(np.array(c1))
    lab2 = linear_srgb_to_oklab(np.array(c2))
    mixed_lab = lab1 + (lab2 - lab1) * t
    return np.clip(oklab_to_linear_srgb(mixed_lab), 0, 1)