"""
VOP Module:     dre_sequencer.py
Description:    Dynamic Range Extender frame sequencer
                Converts a single 16-bit-per-channel source frame into a
                temporal sequence of 8-bit frames whose integrated photon
                output (across a camera exposure window) reconstructs the
                full 16-bit tonal range on an 8-bit projection monitor.

                Per-pixel temporal scheduling (see VOP issue #169):
                each step in the sequence raises a luminance threshold;
                pixels with source values above the threshold contribute
                light for that step, pixels below it go black. Higher-
                valued pixels stay lit for more of the exposure, lower-
                valued pixels for less. The camera, integrating over the 
                whole sequence, sees a weighted sum that preserves the
                original 16-bit precision (modulo screen non-linearity,
                which a future calibration LUT will correct).
"""
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

# Default number of sub-exposure steps. 256 steps = an extra 8 bits of
# effective dynamic range beyon the 8-bit screen, giving an effective
# 16-bit output. The user can request fewer steps to trade precision
# for exposure time, or more for over-sampling (which mostly helps SNR
# rather than precision once the screen non-linearity dominates).
DEFAULT_STEPS = 256

# Placeholder dumb-gamma. The screen is not linear in code value vs. emitted
# photons; a value of 128 emits noticeably less than half the light of 
# 255 on a typical 8-bit panel. A real per-screen calibration LUT (issue
# #184) will replace this number eventually. Until then, a single
# global gamma constant lets us twist one knob and re-test rather than
# rebuilding the pipeline. 2.2 is the rec.709-ish default; the actual
# panel will probably want something different once measured.
DEFAULT_GAMMA = 2.2


def sequence_frame(source_16bpc, steps=DEFAULT_STEPS, gamma=DEFAULT_GAMMA):
    """
    Generator. Yields successive 8-bit RGB numpy frames that together
    encode the supplied 16-bit source via temporal luminance modulation.

    Args:
        source_16bpc : numpy.ndarray, dtype=uint16, shape=(H, W, 3).
                       The high-bit-depth source frame, already in RGB
                       order (TextureManager hands us this after its
                       BGR->RGB conversion). Other dtypes raise TypeError
                       so we fail loud on misconfiguration rather than
                       silently corrupting the temporal encoding.
        steps        : int. Number of sub-exposure frames in the sequence.
                       More steps = finer effective bit depth and longer
                       exposure budget. Must be >= 2 (1 step is just a
                       single 8-bit frame, which defeats the purpose).
        gamma        : float. Screen-response gamma correction applied to
                       the threshold values. The screen is non-linear in
                       code value vs. emitted photons; raising thresholds
                       to gamma 2.2 approximates a perceptually-linear
                       photon ramp. Replace with a measured LUT in a
                       future phase (issue #184).

    Yields:
        numpy.ndarray, dtype=uint8, shape=(H, W, 3).
        One 8-bit RGB frame per call. Caller is responsible for pushing
        each yielded frame to the projection monitor and holding it for
        the appropriate fraction of the camera exposure window.

    The integration math:
        Let v be a source uint16 value in [0, 65535]. For step s in
        [0, steps), let T_s = (s / steps) * 65535 be the step's
        threshold. Pixel output at step s is:
            out_s = clip( (v - T_s) * 255 / (65535 / steps), 0, 255 )
        Over the full sequence, sum(out_s) is monotonic in v with
        roughly log2(steps) extra bits of effective precision beyond 8.

        Gamma correction is applied to T_s before subtraction so that
        equal increments of T_s correspond to equal increments of
        *emitted photons*, not equal increments of code value.
    """
    # Input validation. We fail loud here because a quietly-wrong dtype
    # would produce output that *looks* okay but doesn't actually encode
    # 16-bit range - which would be very hard to debug from the captured
    # results alone.
    if source_16bpc.dtype != np.uint16:
        raise TypeError(
            f"dre_sequencer expects a uint16 source, got {source_16bpc.dtype}. "
            f"(If you passed a uint8 frame, the DRE encoding will not work - "
            f"check the ingestion pixel format and TextureManager paths.)"
        )
    # Shape validation. Must be (H, W, 3).
    if source_16bpc.ndim != 3 or source_16bpc.shape[2] != 3:
        raise ValueError(
            f"dre_sequencer expects shape (H, W, 3), got {source_16bpc.shape}."
        )
    if steps < 2:
        raise ValueError(f"dre_sequencer requires steps>=2, got {steps}.")

    # Cast to float32 once at the start. uint16 arithmetic would overflow
    # on the (v - T) subtraction for low pixel values, and the (* 255)
    # multiplication for high ones. float32 has plenty of headroom and
    # the per-frame allocation cost is negligible compared to disk I/O
    # and texture upload.
    src_f = source_16bpc.astype(np.float32)

    # Per-step linear threshold spacing across the 16-bit range. Step 0
    # has threshold 0 (every nonzero pixel contributes), final step has
    # threshold approaching 65535 (only the very brightest pixels still
    # contribute). We exclude the endpoint via endpoint=False so the
    # last step is the brightest-only step, not a no-op pure-black step.
    thresholds_linear = np.linspace(0.0, 65535.0, steps, endpoint=False)

    # Apply screen-response gamma. We want equal-photon steps, not equal-
    # code-value steps. Normalize to 0..1, apply gamma, denormalize back.
    # This is the "dumb LUT" approximation - a measured LUT will replace
    # this curve with per-screen calibrated values in a later phase.
    thresholds = (np.power(thresholds_linear / 65535.0, gamma) * 65535.0)

    # The per-step scaling factor that maps the residual (v - T) range
    # of (65535 / steps) up to the full 8-bit projector range of 255.
    # This is what gives each step the maximum possible SNR on the
    # projection monitor: every sub-exposure uses the full 0..255 code
    # range, never a compressed sub-range, so the screen's own bit
    # depth is fully exploited at every step.
    step_range = 65535.0 / steps
    scale = 255.0 / step_range  # constant across all steps

    # Generate frames in dark-first order: step 0 lights every pixel
    # with any signal at all, later steps progressively drop the dim
    # pixels. This matches the original concept ("darker pixels first,
    # lighter pixels last") - after step 0, the darks have already
    # contributed their full quota of photons and are turned off so
    # they can't drift up from sensor noise.
    for s in range(steps):
        T = thresholds[s]
        # Subtract threshold, scale to 0..255, clip negative values to
        # zero (pixels below the threshold) and overshoots to 255.
        # Cast to uint8 last; the clip ensures the cast is safe (no
        # wraparound from negative floats).
        frame = np.clip((src_f - T) * scale, 0.0, 255.0).astype(np.uint8)
        yield frame


def total_steps_for_exposure(exposure_seconds, min_step_seconds=0.01):
    """
    Helper for later wiring. Given a target exposure window and a 
    minimum per step screen-hold time (limited by HDMI refresh rate and
    sensor integration smoothness), returns the largest number of DRE
    steps that fit cleanly inside the window.

    Caps at DEFAULT_STEPS because more than 256 steps gives diminishing
    returns once screen non-linearity dominates - the marginal precision
    gain isn't worth the exposure time.

    """
    max_steps_by_time = int(exposure_seconds / min_step_seconds)
    return max(2, min(DEFAULT_STEPS, max_steps_by_time))