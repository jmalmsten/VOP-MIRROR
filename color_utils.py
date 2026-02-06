import numpy as np

def linear_to_oklab(rgb):
    """Converts Linear RGB [0-1] to Oklab coordinates."""
    l = 0.4122*rgb[0] + 0.5363*rgb[1] + 0.0514*rgb[2]
    m = 0.2119*rgb[0] + 0.6807*rgb[1] + 0.1074*rgb[2]
    s = 0.0883*rgb[0] + 0.2817*rgb[1] + 0.6300*rgb[2]
    l_, m_, s_ = np.cbrt([l, m, s])
    return [
        0.2104*l_ + 0.7936*m_ - 0.0040*s_,
        1.9779*l_ - 2.4285*m_ + 0.4505*s_,
        0.0259*l_ + 0.7827*m_ - 0.8086*s_
    ]

def oklab_to_linear(ok):
    """Converts Oklab back to Linear RGB [0-1]."""
    L, a, b = ok
    l_ = L + 0.3963*a + 0.2158*b
    m_ = L - 0.1055*a - 0.0638*b
    s_ = L - 0.0894*a - 1.2914*b
    l, m, s = l_**3, m_**3, s_**3
    r = 4.0767*l - 3.3077*m + 0.2309*s
    g = -1.2684*l + 2.6097*m - 0.3413*s
    b = -0.0041*l - 0.7034*m + 1.7076*s
    return [np.clip(r, 0, 1), np.clip(g, 0, 1), np.clip(b, 0, 1)]

def get_perceptual_color(t, c1, c2):
    """Linearly interpolates between two colors in Oklab space."""
    ok1, ok2 = linear_to_oklab(c1), linear_to_oklab(c2)
    mix = [ok1[i] + (ok2[i] - ok1[i]) * t for i in range(3)]
    return oklab_to_linear(mix)