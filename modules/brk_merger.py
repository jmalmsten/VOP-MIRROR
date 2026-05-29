""""
VOP Module:     brk_merger.py
Description:    Bracketed-exposure frame merger for BRK mode.

                Given N camera captures (uint16 (H,W,3) arrays)
                and the BracketSpec list they correspond to, this
                module produces one merged uint16 (H,W,3) array
                that combines the brackets into a single linear-
                gamma latent image.

                Algorithm: simple per-pixel float-precision average
                of the captures, clipped and rounded back to uint16
                at the end.

                Mental model: each bracket is one exposure of the
                source through the projection monitor, with the
                screen showing a different source-range slice for
                each bracket. The deeper brackets amplify shadow
                detail (by remapping a smaller source range to
                fill the screen), but they also saturate quickly
                for brighter source values. Averaging the captures
                directly turns this into an additive-like merge
                that:
                  - keeps shadows clean (true-black source pixels
                    average to black across all brackets);
                  - preserves linear gamma (linear average of
                    linear values is linear) so the result feeds
                    correctly back into MDS/SSS for further
                    exposure accumulation;
                  - softly mixes brackets across the dynamic range
                    without sharp seams (since all brackets always
                    contribute, no per-bracket weighting needed).

                Earlier iterations of this module did weighted-
                average reconstruction in source space via per-
                bracket slice geometry. That approach introduced a
                black floor at the deepest bracket's slice_low_norm
                (any pixel below that value got reported as exactly
                that value) and required complex weight curves that
                were a source of bugs. The current simple average
                trades off some mid-bright differentiation for
                cleanliness; the trade is acceptable for current
                screen calibration and is addressable later via
                targeted highlight scaling once HDMI monitor LUT
                calibration lands.

                Numerical hygiene: all math runs in float32
                internally. The uint16 cast happens only at the
                very end, with a clip-to-range and a round-to-
                nearest. This avoids the silent wraparound that
                would occur if intermediate sums went above 1.0
                even momentarily, and preserves bit-accurate
                rounding at the boundary.
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


# Overlap fraction between adjacent brackets, in normalized source
# space, measured as a fraction of each slice's width.
#
# 0.2 = 20%. The peak bracket's slice extends 20% of its width down
# into the next bracket's territory, and the shadow bracket extends
# 20% of its width up into the peak's territory. So adjacent
# brackets see roughly 20% of overlapping source content, and the
# blend within that band cross-fades from "100% peak" at the
# peak-side edge to "100% shadow" at the shadow-side edge.
#
# Tuned during planning, not user-exposed - moving it requires
# code change. The 20% number is a "feels right" default with no
# strong theoretical justification; bumping it up makes seams
# softer but wastes more screen resolution on duplicated coverage,
# bumping it down sharpens transitions but risks visible banding
# at the boundaries when screen linearity is imperfect.
OVERLAP_FRACTION = 0.20


def merge(captures, brackets):
    """
    Merge N bracketed captures into one 16bpc latent array.

    Algorithm: simple per-pixel average of the captures in float32,
    clipped to [0, 1] and rounded to uint16 at the end. Linear gamma
    is preserved end-to-end so the merged output remains a valid
    latent image suitable for further accumulation via MDS/SSS exposure.

    Each bracket's capture is one exposure of the source through the
    projection monitor, with the screen showing a different source-range
    slice per bracket. The brackets are NOT recombined in source space -
    that approach (used in earlier iterations) introduced a black floor
    at the deepest bracket's slice_low_norm because the bracket's slice
    geometry assigned weight 1.0 to source estimates that were really
    just "the bracket saw black, source is somewhere at or below my
    slice's lower edge." Averaging captures directly sidesteps this:
    a pixel where every bracket sees black averages to black, which
    is the correct "I don't know what's down there" answer.

    The trade-off is some loss of mid-bright differentiation - bright
    patches that saturate the deeper brackets pull the average up
    less aggressively than they should. This shows up as a slightly
    compressed mid-bright range in the merged output. Acceptable
    given the alternatives, and addressable later via screen
    calibration / targeted highlight scaling (parked as a future
    polish item).

    Args:
        captures : list of numpy.ndarray, each dtype=uint16,
                   shape=(H, W, 3). One per bracket, in the
                   same order as `brackets`. Captures are the
                   raw camera output for each bracket; the
                   engine is responsible for any pre-processing
                   (hot pixel mapping, etc.) BEFORE handing
                   them here.
        brackets : list of brk_sequencer.BracketSpec, same
                   length as captures, same ordering (peak-
                   first). Currently UNUSED by the merge math
                   but accepted in the signature to preserve
                   the engine's call site shape. May be
                   reintroduced for targeted weighting in a
                   future iteration.

    Returns:
        numpy.ndarray, dtype=uint16, shape=(H, W, 3) in RGB
        channel order (matching the captures' channel order
        coming out of cutil.dng_to_uint16_rgb).

    Raises:
        ValueError if captures and brackets disagree in length,
        or if any capture has an unexpected dtype/shape.
    """
    # Input validation. The engine should never call us with
    # mismatched inputs but defensive checking here means a bug
    # in the engine surfaces as a clear exception instead of a
    # silently-wrong latent.
    if len(captures) != len(brackets):
        raise ValueError(
            f"brk_merger: captures count ({len(captures)}) does not "
            f"match brackets count ({len(brackets)})."
        )
    if len(captures) == 0:
        raise ValueError("brk_merger: at least one capture is required.")

    ref_shape = captures[0].shape
    for i, cap in enumerate(captures):
        if cap.dtype != np.uint16:
            raise ValueError(
                f"brk_merger: capture[{i}] has dtype {cap.dtype}, "
                f"expected uint16."
            )
        if cap.shape != ref_shape:
            raise ValueError(
                f"brk_merger: capture[{i}] shape {cap.shape} does "
                f"not match capture[0] shape {ref_shape}."
            )
        if cap.ndim != 3 or cap.shape[2] != 3:
            raise ValueError(
                f"brk_merger: capture[{i}] must be (H, W, 3), "
                f"got {cap.shape}."
            )

    # Accumulate in float32 for headroom. Each capture contributes
    # its normalized [0..1] value; the running sum can exceed 1.0
    # for pixels where multiple brackets saturate, which is fine
    # at this point - we clip only at the final cast to uint16.
    #
    # We could use the more obvious idiom:
    #   sum_norm = np.mean([c.astype(np.float32) / 65535.0 for c in
    #                       captures], axis=0)
    # but that materializes all N float arrays in memory at once,
    # which on the Pi's 4GB RAM with 2028x1520x3 float32 (37MB
    # each) is a meaningful cost for 3+ brackets. The explicit
    # loop accumulates one bracket at a time and reuses the
    # accumulator buffer.
    accumulator = np.zeros(ref_shape, dtype=np.float32)
    for cap in captures:
        accumulator += cap.astype(np.float32) / 65535.0
    accumulator /= float(len(captures))

    # Clip-and-quantize. Even though the accumulator can never
    # exceed 1.0 under exact arithmetic (it's a mean of values in
    # [0, 1]), float rounding could push it slightly above; the
    # clip guards against that. The +0.5 in the cast is round-to-
    # nearest (numpy's default cast truncates).
    out_clipped = np.clip(accumulator, 0.0, 1.0)
    out_uint16 = (out_clipped * 65535.0 + 0.5).astype(np.uint16)
    return out_uint16


def _compute_weights(source_estimate, bracket, is_first, is_last):
    """
    Per-pixel weight array for one bracket's contribution to
    the merged output. Pure numpy, no Python loops.

    Args:
        source_estimate : float32 array, shape (H, W, 3),
                          values in [0.0, 1.0]. The bracket's
                          un-remapped capture, expressing its
                          best guess for each pixel's
                          source value in normalized source
                          space.
        bracket         : the BracketSpec for this bracket.
                          Used for slice_low_norm and
                          slice_high_norm.
        is_first        : bool. True for the peak bracket
                          (index 0). Disables the upper-edge
                          taper since there's nothing above
                          to overlap with.
        is_last         : bool. True for the deepest bracket.
                          Disables the lower-edge taper.

    Returns:
        float32 array, same shape as source_estimate. Values
        in [0.0, 1.0]. Higher = this bracket should dominate
        the merged result at that pixel.
    """
    low = float(bracket.slice_low_norm)
    high = float(bracket.slice_high_norm)
    slice_width = high - low

    # Overlap width on each side of the slice, in normalized
    # source space. Same width on both sides because the
    # geometric series of slices is symmetric in log-space.
    overlap = OVERLAP_FRACTION * slice_width

    # Edges of the "full weight" core region. Inside [core_low,
    # core_high] this bracket has weight 1.0; outside, weight
    # tapers down to 0 across the overlap zone or clips to 0
    # entirely past the overlap.
    #
    # Without the is_first/is_last special cases the peak
    # bracket's core_high would be inside its slice, leaving
    # the topmost source values incompletely covered. So
    # is_first removes the upper taper (core_high = high)
    # and is_last removes the lower taper (core_low = low).
    
    # Core region: weight 1.0 wherever source_estimate is
    # inside [core_low, core_high]. Edges are inset from the
    # slice edges by `overlap` UNLESS the bracket is on the
    # outer edge of the source range (peak bracket on top,
    # deepest bracket on bottom), in which case the slice
    # edge IS the source-space edge and there's no neighbor
    # to taper into.
    #
    # ORIGINAL STATE (intentionally unchanged after snippets
    # 2E/2F were reverted): the deepest bracket is treated
    # as having full information all the way to slice_low.
    # This is known to lift true-black source pixels to
    # roughly slice_low_norm * 65535 in the merged output.
    # That bug is real but stable; the alternative attempts
    # to fix it (strict > comparison in 2E, lower taper in
    # 2F) both introduced worse problems. Leaving as-is
    # while we build proper diagnostics.
    core_low = low if is_last else (low + overlap)
    core_high = high if is_first else (high - overlap)

    # Initialize weights to zero. Below we'll set them to 1
    # in the core region and to a linear taper in the
    # overlap regions.
    weights = np.zeros_like(source_estimate)

    # Core region: weight 1.0 wherever source_estimate is
    # inside [core_low, core_high].
    in_core = (source_estimate >= core_low) & (source_estimate <= core_high)
    weights[in_core] = 1.0

    # Lower taper: linear ramp from 0 at (core_low - overlap)
    # to 1 at core_low. Only relevant when is_last is False -
    # otherwise core_low IS low and the slice has no
    # lower-side overlap zone.
    if not is_last:
        taper_low_start = core_low - overlap  # equivalently: low (the slice's actual bottom)
        in_lower_taper = (source_estimate >= taper_low_start) & (source_estimate < core_low)
        # Linear ramp 0..1 across the overlap. We add a
        # tiny epsilon to the denominator only conceptually;
        # numpy handles div-by-zero with infs, which would
        # propagate badly. Since overlap > 0 by construction
        # (it's OVERLAP_FRACTION * slice_width with both
        # factors positive), no guard is actually needed
        # here in code.
        weights[in_lower_taper] = (
            (source_estimate[in_lower_taper] - taper_low_start) / overlap
        )

    # Upper taper: linear ramp from 1 at core_high to 0 at
    # (core_high + overlap). Only relevant when is_first is
    # False - peak bracket extends all the way to source top.
    if not is_first:
        taper_high_end = core_high + overlap  # equivalently: high
        in_upper_taper = (source_estimate > core_high) & (source_estimate <= taper_high_end)
        weights[in_upper_taper] = (
            (taper_high_end - source_estimate[in_upper_taper]) / overlap
        )

    return weights