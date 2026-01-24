"""
VOP Module:     vop_color_math.py
Version:        v0.0.1
Description:    Converts Kelvin (Temperature) and Tint (Green/Magenta) 
                into R,B gains for rpicam-apps.
"""

def kelvin_to_gains(kelvin, tint=0):
    """
    kelvin: 1000 to 15000 (standard is 6500)
    tint: -100 (more green) to 100 (more magenta)
    Returns: (red_gain, blue_gain)
    """
    # Normalized temperature
    temp = kelvin / 1000.0
    
    # Calculate Red Gain
    if temp <= 6.6:
        r = 2.5  # Base for warm light
    else:
        # As it gets colder (blue), we need more red gain to balance
        r = 2.5 + (temp - 6.6) * 0.15

    # Calculate Blue Gain
    if temp <= 6.6:
        b = 1.0 + (6.6 - temp) * 0.4
    else:
        b = 1.0  # Base for cold light

    # Apply Tint (Magenta/Green axis)
    # Positive tint adds magenta (increases R and B relative to G)
    # Negative tint adds green (decreases R and B relative to G)
    tint_factor = 1 + (tint / 500.0)
    
    return round(r * tint_factor, 3), round(b * tint_factor, 3)

if __name__ == "__main__":
    # Quick test
    k, t = 4000, -10
    rg, bg = kelvin_to_gains(k, t)
    print(f"Photography Settings: {k}K, {t} Tint")
    print(f"Command Flag: --awbgains {rg},{bg}")